"""
app.py — AI Bill Splitter
Agents 0-2 + Edit UI + Type-based split flow (names → assign → summary)
"""
import pandas as pd
import streamlit as st

from agents.extractor import BillItem, ExtractedBill, extract
from agents.router import route
from agents.validator import validate
from services.whisper import transcribe

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Bill Splitter",
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }
.block-container { max-width: 740px; padding-top: 2rem; padding-bottom: 5.5rem; }
.attach-pill {
    display: inline-flex; align-items: center; gap: 6px;
    background: #eef2ff; border: 1px solid #c7d2fe;
    border-radius: 999px; padding: 4px 14px;
    font-size: 0.83rem; color: #3730a3; font-weight: 500;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
_WELCOME = (
    "Hi! I'm your AI bill splitter. 👋\n\n"
    "Send me a bill and I'll split it fairly between everyone in your group:\n\n"
    "- 📎 **Attach** a receipt photo or PDF\n"
    "- ⌨️  **Type** the items and prices directly\n"
    "- 🎤  **Speak** your bill — record a voice note"
)

_STATE_DEFAULTS = {
    "messages":       [{"role": "assistant", "content": _WELCOME}],
    "file_bytes":     None,
    "file_name":      None,
    "file_type":      None,
    "pending_input":  None,
    "extracted_bill": None,
    "edit_mode":      False,
    # split flow
    "split_mode":     None,        # None | "choosing" | "type" | "converse"
    "split_step":     "names",     # "names" | "assign" | "summary"
    "participants":   [],          # list[str]
    "assignments":    {},          # {item_index: set(participant_name)}
}

for _k, _v in _STATE_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Full reset ────────────────────────────────────────────────────────────────
def _reset() -> None:
    for k in _STATE_DEFAULTS:
        st.session_state.pop(k, None)
    # Clear input widgets so a prior recording/upload doesn't auto-reattach
    for widget_key in ("mic", "uploader"):
        st.session_state.pop(widget_key, None)
    st.rerun()


# ── Bill card (read-only, stored in message for persistence) ──────────────────
def _render_bill_card(bill: dict) -> None:
    df = pd.DataFrame([
        {"Item": i["name"], "Qty": i["quantity"], "Price": f"${i['price']:.2f}"}
        for i in bill["items"]
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    parts = [f"Subtotal **${bill['subtotal']:.2f}**"]
    if bill["tax"] > 0: parts.append(f"Tax **${bill['tax']:.2f}**")
    if bill["tip"] > 0: parts.append(f"Tip **${bill['tip']:.2f}**")
    parts.append(f"Total **${bill['total']:.2f}**")
    st.caption("  ·  ".join(parts))

    if not bill.get("validation_passed", True) and bill.get("validation_note"):
        st.warning(f"⚠️ {bill['validation_note']}")


# ── Save edits ────────────────────────────────────────────────────────────────
def _save_edits(edited_df: pd.DataFrame, tax: float, tip: float, total: float) -> None:
    items = []
    for _, row in edited_df.iterrows():
        name = row.get("Item", "")
        if pd.isna(name) or str(name).strip() == "":
            continue
        qty   = row.get("Qty", 1)
        price = row.get("Price ($)", 0.0)
        items.append(BillItem(
            name=str(name).strip(),
            quantity=max(1, int(qty) if not pd.isna(qty) else 1),
            price=round(float(price) if not pd.isna(price) else 0.0, 2),
        ))

    subtotal = round(sum(i.price for i in items), 2)  # price is the line total
    new_bill = ExtractedBill(
        items=items, subtotal=subtotal,
        tax=round(tax, 2), tip=round(tip, 2), total=round(total, 2),
        validation_passed=True, validation_note=None,
    )
    st.session_state.extracted_bill = new_bill
    st.session_state.assignments    = {}  # reset assignments when bill changes

    bill_dict = {
        "items":             [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in items],
        "subtotal": subtotal, "tax": round(tax, 2), "tip": round(tip, 2),
        "total": round(total, 2), "validation_passed": True, "validation_note": None,
    }
    for msg in reversed(st.session_state.messages):
        if msg.get("bill"):
            msg["bill"] = bill_dict
            break

    st.session_state.edit_mode = False
    st.rerun()


# ── Math engine ───────────────────────────────────────────────────────────────
def _calculate_splits() -> list[dict]:
    bill         = st.session_state.extracted_bill
    participants = st.session_state.participants
    assignments  = st.session_state.assignments   # {item_index: set(name)}

    person_subtotals: dict[str, float] = {n: 0.0 for n in participants}

    for idx, item in enumerate(bill.items):
        assigned = assignments.get(idx, set())
        if assigned:
            share = item.price / len(assigned)
            for name in assigned:
                person_subtotals[name] = person_subtotals.get(name, 0.0) + share

    group_sub = sum(person_subtotals.values())
    results   = []

    for name in participants:
        ps = round(person_subtotals[name], 2)
        if group_sub > 0:
            prop = person_subtotals[name] / group_sub
            ptax = round(bill.tax * prop, 2)
            ptip = round(bill.tip * prop, 2)
        else:
            n    = len(participants)
            ptax = round(bill.tax / n, 2) if n else 0.0
            ptip = round(bill.tip / n, 2) if n else 0.0
        results.append({
            "name": name, "subtotal": ps,
            "tax": ptax, "tip": ptip,
            "total": round(ps + ptax + ptip, 2),
        })

    # Absorb rounding discrepancy into first person
    if results:
        diff = round(bill.total - sum(r["total"] for r in results), 2)
        if diff:
            results[0]["total"] = round(results[0]["total"] + diff, 2)

    return results


# ── Split sub-steps ───────────────────────────────────────────────────────────
def _render_names_step() -> None:
    st.markdown("**Who's splitting this bill?**")
    st.caption("Add everyone who shared the bill.")

    # Participant chips
    if st.session_state.participants:
        cols = st.columns(min(len(st.session_state.participants), 4))
        for i, name in enumerate(list(st.session_state.participants)):
            with cols[i % min(len(st.session_state.participants), 4)]:
                if st.button(f"{name}  ✕", key=f"rm_p_{i}", use_container_width=True):
                    st.session_state.participants.remove(name)
                    for asgn in st.session_state.assignments.values():
                        asgn.discard(name)
                    st.rerun()

    add_col, btn_col = st.columns([5, 1])
    with add_col:
        new_name = st.text_input(
            "name", placeholder="Enter a name…",
            label_visibility="collapsed", key="name_input",
        )
    with btn_col:
        if st.button("Add", use_container_width=True):
            n = new_name.strip()
            if n and n not in st.session_state.participants:
                st.session_state.participants.append(n)
                st.rerun()

    st.write("")
    back_col, next_col = st.columns(2)
    with back_col:
        if st.button("← Back", use_container_width=True):
            st.session_state.split_mode = "choosing"
            st.rerun()
    with next_col:
        if st.button(
            "Assign Items →", type="primary", use_container_width=True,
            disabled=len(st.session_state.participants) == 0,
        ):
            # Initialise assignment sets keyed by item index
            for idx in range(len(st.session_state.extracted_bill.items)):
                st.session_state.assignments.setdefault(idx, set())
            st.session_state.split_step = "assign"
            st.rerun()


def _render_assign_step() -> None:
    bill         = st.session_state.extracted_bill
    participants = st.session_state.participants
    assignments  = st.session_state.assignments

    st.markdown("**Tap names to assign each item:**")
    st.caption("Select everyone who should share each item.")

    for idx, item in enumerate(bill.items):
        assigned = assignments.get(idx, set())

        label_col, price_col = st.columns([7, 3])
        with label_col:
            qty_tag = f"  ×{item.quantity}" if item.quantity > 1 else ""
            st.markdown(f"**{item.name}**{qty_tag}")
        with price_col:
            st.markdown(f"**${item.price:.2f}**")

        p_cols = st.columns(len(participants))
        for j, name in enumerate(participants):
            with p_cols[j]:
                selected = name in assigned
                if st.button(
                    f"✓ {name}" if selected else name,
                    key=f"asgn_{idx}_{j}",
                    type="primary" if selected else "secondary",
                    use_container_width=True,
                ):
                    if selected:
                        assigned.discard(name)
                    else:
                        assigned.add(name)
                    assignments[idx] = assigned
                    st.rerun()

        if assigned:
            share = item.price / len(assigned)
            st.caption(f"${share:.2f} each · {', '.join(sorted(assigned))}")
        else:
            st.caption("⚠️ Not assigned yet")

        st.divider()

    unassigned_names = [
        bill.items[i].name
        for i in range(len(bill.items))
        if not assignments.get(i)
    ]

    back_col, next_col = st.columns(2)
    with back_col:
        if st.button("← Back", use_container_width=True):
            st.session_state.split_step = "names"
            st.rerun()
    with next_col:
        if unassigned_names:
            st.warning(f"Still unassigned: {', '.join(unassigned_names)}")
        if st.button(
            "See Summary →", type="primary", use_container_width=True,
            disabled=bool(unassigned_names),
        ):
            st.session_state.split_step = "summary"
            st.rerun()


def _render_summary_step() -> None:
    results = _calculate_splits()

    st.markdown("### 💰 Who owes what")

    for r in results:
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"**{r['name']}**")
            parts = [f"items ${r['subtotal']:.2f}"]
            if r["tax"] > 0: parts.append(f"tax ${r['tax']:.2f}")
            if r["tip"] > 0: parts.append(f"tip ${r['tip']:.2f}")
            st.caption("  +  ".join(parts))
        with right:
            st.markdown(f"### ${r['total']:.2f}")

    st.divider()

    back_col, new_col = st.columns(2)
    with back_col:
        if st.button("← Reassign items", use_container_width=True):
            st.session_state.split_step = "assign"
            st.rerun()
    with new_col:
        if st.button("＋ New bill", type="primary", use_container_width=True):
            _reset()


# ── Action area ───────────────────────────────────────────────────────────────
def _render_action_area() -> None:
    if not st.session_state.extracted_bill:
        return

    st.divider()

    # ── Edit mode ─────────────────────────────────────────────────────────────
    if st.session_state.edit_mode:
        bill = st.session_state.extracted_bill
        st.markdown("**Edit your bill — fix prices, rename items, or add missing rows:**")

        df = pd.DataFrame([
            {"Item": i.name, "Qty": i.quantity, "Price ($)": i.price}
            for i in bill.items
        ])
        edited = st.data_editor(
            df, num_rows="dynamic", use_container_width=True,
            column_config={
                "Item":      st.column_config.TextColumn("Item", required=True),
                "Qty":       st.column_config.NumberColumn("Qty",       min_value=1,   step=1,    format="%d"),
                "Price ($)": st.column_config.NumberColumn("Price ($)", min_value=0.0, step=0.01, format="$%.2f"),
            },
            key="items_editor",
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            new_tax = st.number_input("Tax ($)",  min_value=0.0, value=float(bill.tax), step=0.01, format="%.2f", key="edit_tax")
        with c2:
            new_tip = st.number_input("Tip ($)",  min_value=0.0, value=float(bill.tip), step=0.01, format="%.2f", key="edit_tip")
        with c3:
            item_sum = sum(
                float(row["Price ($)"] or 0)  # price is the line total, not unit price
                for _, row in edited.iterrows()
                if not pd.isna(row.get("Price ($)"))
            )
            new_total = round(item_sum + new_tax + new_tip, 2)
            st.metric("Total ($)", f"${new_total:.2f}")

        save_col, cancel_col = st.columns(2)
        with save_col:
            if st.button("💾  Save changes", type="primary", use_container_width=True):
                _save_edits(edited, new_tax, new_tip, new_total)
        with cancel_col:
            if st.button("✕  Cancel", use_container_width=True):
                st.session_state.edit_mode = False
                st.rerun()

    # ── Choose split method ───────────────────────────────────────────────────
    elif st.session_state.split_mode == "choosing":
        st.markdown("**How would you like to split the bill?**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⌨️  Type", use_container_width=True, help="Enter names and click to assign items"):
                st.session_state.split_mode = "type"
                st.session_state.split_step = "names"
                st.rerun()
        with col2:
            if st.button("🎤  Converse", type="primary", use_container_width=True, help="Voice-guided assignment"):
                st.session_state.split_mode = "converse"
                st.rerun()

    # ── Type flow ─────────────────────────────────────────────────────────────
    elif st.session_state.split_mode == "type":
        step = st.session_state.split_step
        if step == "names":
            _render_names_step()
        elif step == "assign":
            _render_assign_step()
        elif step == "summary":
            _render_summary_step()

    # ── Converse placeholder ──────────────────────────────────────────────────
    elif st.session_state.split_mode == "converse":
        st.info("🎤 Voice assignment agent coming in the next phase!")
        if st.button("← Back", use_container_width=False):
            st.session_state.split_mode = "choosing"
            st.rerun()

    # ── Default: main action buttons ──────────────────────────────────────────
    else:
        col_edit, col_split = st.columns(2)
        with col_edit:
            if st.button("✏️  Need more edits?", use_container_width=True):
                st.session_state.edit_mode = True
                st.rerun()
        with col_split:
            if st.button("✅  Ready to Split it?", type="primary", use_container_width=True):
                st.session_state.split_mode = "choosing"
                st.rerun()


# ── Submit handler ────────────────────────────────────────────────────────────
def _submit(text: str | None) -> None:
    fb    = st.session_state.file_bytes
    fname = st.session_state.file_name
    ftype = st.session_state.file_type

    if not text and not fb:
        return

    parts = []
    if fb and ftype and ftype.startswith("audio/"):
        parts.append("🎤 **Voice note**")
    elif fname:
        parts.append(f"📎 **{fname}**")
    if text:  parts.append(text)

    user_msg: dict = {"role": "user", "content": "\n\n".join(parts)}
    if fb and ftype and ftype.startswith("image/"):
        user_msg["image_bytes"] = fb
        user_msg["file_name"]   = fname
    elif fb and ftype and ftype.startswith("audio/"):
        user_msg["audio_bytes"] = fb
        user_msg["audio_type"]  = ftype

    st.session_state.messages.append(user_msg)
    st.session_state.pending_input = {
        "text": text, "file_bytes": fb, "file_name": fname, "file_type": ftype,
    }
    # Reset everything downstream when a new bill is submitted
    st.session_state.file_bytes    = None
    st.session_state.file_name     = None
    st.session_state.file_type     = None
    st.session_state.edit_mode     = False
    st.session_state.split_mode    = None
    st.session_state.split_step    = "names"
    st.session_state.participants  = []
    st.session_state.assignments   = {}


# ── Header ────────────────────────────────────────────────────────────────────
h_col, btn_col = st.columns([8, 2])
with h_col:
    st.markdown("## 🧾 AI Bill Splitter")
    st.caption("Upload a receipt, type items, or speak — split any bill fairly.")
with btn_col:
    st.write("")
    if st.button("＋ New bill", use_container_width=True):
        _reset()

st.divider()

# ── Chat messages ─────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    avatar = "🧾" if msg["role"] == "assistant" else "👤"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        if msg.get("image_bytes"):
            st.image(msg["image_bytes"], width=260, caption=msg.get("file_name", ""))
        if msg.get("audio_bytes"):
            st.audio(msg["audio_bytes"], format=msg.get("audio_type", "audio/wav"))
        if msg.get("bill"):
            _render_bill_card(msg["bill"])

# ── Agent pipeline ────────────────────────────────────────────────────────────
if st.session_state.pending_input:
    pending = st.session_state.pending_input

    with st.chat_message("assistant", avatar="🧾"):

        # Agent 0: Router
        with st.status("Routing your input…", expanded=True) as s:
            try:
                decision = route(
                    text=pending.get("text"),
                    file_bytes=pending.get("file_bytes"),
                    file_type=pending.get("file_type"),
                )
                s.update(label=f"✓ {decision.status_label}", state="complete", expanded=False)
            except Exception as exc:
                s.update(label=f"Routing error: {exc}", state="error", expanded=True)
                decision = None

        # Whisper STT: transcribe audio → text before the extractor runs
        effective_text = pending.get("text")
        if decision and decision.route == "whisper_then_text_pipeline":
            with st.status("Transcribing your voice…", expanded=True) as s:
                try:
                    effective_text = transcribe(
                        pending.get("file_bytes"),
                        pending.get("file_name"),
                    )
                    if effective_text:
                        st.write(f"🗣️ “{effective_text}”")
                        s.update(label="✓ Transcribed your voice note", state="complete", expanded=False)
                    else:
                        s.update(label="⚠️ Couldn't hear anything — try recording again", state="error", expanded=True)
                        decision = None
                except Exception as exc:
                    s.update(label=f"Transcription error: {exc}", state="error", expanded=True)
                    decision = None

        # Agent 1: Extractor
        bill = None
        if decision:
            with st.status("Extracting bill items…", expanded=True) as s:
                try:
                    bill = extract(
                        route=decision.route,
                        text=effective_text,
                        file_bytes=pending.get("file_bytes"),
                        file_type=pending.get("file_type"),
                    )
                    s.update(
                        label=f"✓ Found {len(bill.items)} item{'s' if len(bill.items) != 1 else ''}",
                        state="complete", expanded=False,
                    )
                except Exception as exc:
                    s.update(label=f"Extraction error: {exc}", state="error", expanded=True)

        # Agent 2: Validator
        if bill:
            with st.status("Validating numbers…", expanded=True) as s:
                try:
                    bill, attempt_log = validate(
                        bill=bill, route=decision.route,
                        text=effective_text,
                        file_bytes=pending.get("file_bytes"),
                        file_type=pending.get("file_type"),
                    )
                    for entry in attempt_log:
                        st.write(entry)
                    if bill.validation_passed:
                        s.update(label="✓ Numbers verified", state="complete", expanded=False)
                    else:
                        retries = len([e for e in attempt_log if e.startswith("Attempt")])
                        s.update(
                            label=f"⚠️ Could not reconcile after {retries} retr{'y' if retries == 1 else 'ies'}",
                            state="error", expanded=True,
                        )
                        st.session_state.edit_mode = True
                except Exception as exc:
                    s.update(label=f"Validation error: {exc}", state="error", expanded=True)

        # Display result
        bill_msg = None
        if bill:
            if not bill.validation_passed:
                st.warning(
                    "📸 The image may be blurry or some prices couldn't be read clearly. "
                    "The editable table below is open — fix any incorrect amounts."
                )
            st.markdown("Here's what I found on your bill:")
            bill_dict = {
                "items":             [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in bill.items],
                "subtotal":          bill.subtotal, "tax": bill.tax, "tip": bill.tip,
                "total":             bill.total,
                "validation_passed": bill.validation_passed,
                "validation_note":   bill.validation_note,
            }
            _render_bill_card(bill_dict)
            summary = (
                f"Found **{len(bill.items)} item{'s' if len(bill.items) != 1 else ''}** "
                f"— total **${bill.total:.2f}**."
            )
            st.markdown(summary)
            bill_msg = {"role": "assistant", "content": summary, "bill": bill_dict}
            st.session_state.extracted_bill = bill
        elif decision:
            reply = "Sorry, I couldn't extract the bill items. Please try again or rephrase."
            st.markdown(reply)
            bill_msg = {"role": "assistant", "content": reply}
        else:
            reply = "Sorry, something went wrong. Please try again."
            st.markdown(reply)
            bill_msg = {"role": "assistant", "content": reply}

        if bill_msg:
            st.session_state.messages.append(bill_msg)

    st.session_state.pending_input = None

# ── Action area ───────────────────────────────────────────────────────────────
if st.session_state.extracted_bill and not st.session_state.pending_input:
    _render_action_area()

# ── Input controls (hidden once a bill is submitted) ──────────────────────────
if not st.session_state.extracted_bill and not st.session_state.pending_input:
    c_att, c_mic, _ = st.columns([1.6, 1.6, 6.8])

    with c_att:
        with st.popover("📎  Attach", use_container_width=True):
            st.caption("PNG · JPG · PDF — max 10 MB")
            up = st.file_uploader(
                "file", type=["jpg", "jpeg", "png", "pdf"],
                label_visibility="collapsed", key="uploader",
            )
            if up is not None:
                raw = up.read()
                if len(raw) > 10 * 1024 * 1024:
                    st.error("File exceeds the 10 MB limit.")
                else:
                    st.session_state.file_bytes = raw
                    st.session_state.file_name  = up.name
                    st.session_state.file_type  = up.type
                    st.success(f"✓  {up.name} — ready to send")

    with c_mic:
        with st.popover("🎤  Voice", use_container_width=True):
            st.caption("Record your bill, then send")
            rec = st.audio_input("Record", label_visibility="collapsed", key="mic")
            if rec is not None:
                st.session_state.file_bytes = rec.read()
                st.session_state.file_name  = "voice-note.wav"
                st.session_state.file_type  = "audio/wav"

    if st.session_state.file_name:
        _is_audio   = (st.session_state.file_type or "").startswith("audio/")
        _pill_icon  = "🎤" if _is_audio else "📎"
        _pill_label = "Voice note" if _is_audio else st.session_state.file_name
        _send_label = "📤  Send recording" if _is_audio else "📤  Send receipt"

        pill_col, clr_col = st.columns([11, 1])
        with pill_col:
            st.markdown(
                f'<span class="attach-pill">{_pill_icon}&nbsp; {_pill_label}</span>',
                unsafe_allow_html=True,
            )
        with clr_col:
            if st.button("✕", key="rm_attach", help="Remove attachment"):
                st.session_state.file_bytes = None
                st.session_state.file_name  = None
                st.session_state.file_type  = None
                st.session_state.pop("mic", None)
                st.rerun()
        if st.button(_send_label, type="primary", key="send_file", use_container_width=True):
            _submit(None)
            st.rerun()

    if prompt := st.chat_input("Type items, paste a bill, or use 📎 above to attach a receipt…"):
        _submit(prompt)
        st.rerun()
