"""
app.py — AI Bill Splitter
Agents 0-2 + Edit UI + Type-based split flow (names → assign → summary)
"""
import pandas as pd
import streamlit as st

from agents.extractor import BillItem, ExtractedBill, extract
from agents.router import route
from agents.validator import validate
from agents.voice_intent import parse_assignment
from services.elevenlabs import speak
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
    # voice assignment loop (converse mode)
    "voice_clarify_msg":     None,  # str | None — clarification line to speak/show for the current item
    "voice_confirm_pending": None,  # str | None — confirmation line from the last successful assignment
    "voice_attempt":         0,     # retry counter for the current item (also busts the mic widget key)
    "voice_played_key":      None,  # last step_key whose audio was auto-played, to avoid replaying on every rerun
    "voice_audio_cache":     {},    # {step_key: mp3 bytes} so we don't re-call ElevenLabs for the same line
    "voice_log":             [],    # [{"role": "user"|"assistant", "text": str}] — transcript for the UI
}

for _k, _v in _STATE_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Full reset ────────────────────────────────────────────────────────────────
def _reset() -> None:
    for k in _STATE_DEFAULTS:
        st.session_state.pop(k, None)
    st.session_state.pop("items_editor", None)
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
        qty        = row.get("Qty", 1)
        qty        = max(1, int(qty) if not pd.isna(qty) else 1)
        price_each = row.get("Price (each)", 0.0)
        price_each = float(price_each) if not pd.isna(price_each) else 0.0
        items.append(BillItem(
            name=str(name).strip(),
            quantity=qty,
            price=round(price_each * qty, 2),  # BillItem.price stays the line total everywhere else
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


# ── Voice assignment state helpers ────────────────────────────────────────────
def _reset_voice_state() -> None:
    st.session_state.voice_clarify_msg     = None
    st.session_state.voice_confirm_pending = None
    st.session_state.voice_attempt         = 0
    st.session_state.voice_played_key      = None
    st.session_state.voice_audio_cache     = {}
    st.session_state.voice_log             = []


def _switch_to_manual() -> None:
    st.session_state.split_mode = "type"
    _reset_voice_state()
    st.rerun()


def _speak_once(step_key: str, text: str) -> None:
    """Play `text` via ElevenLabs the first time `step_key` is seen this turn;
    on later reruns for the same step_key, show a non-autoplaying replay control."""
    cache = st.session_state.voice_audio_cache
    if step_key not in cache:
        try:
            cache[step_key] = speak(text)
        except Exception as exc:
            st.warning(f"Voice playback unavailable: {exc}")
            st.session_state.voice_played_key = step_key
            return

    if st.session_state.voice_played_key != step_key:
        st.audio(cache[step_key], format="audio/mpeg", autoplay=True)
        st.session_state.voice_played_key = step_key
    else:
        st.audio(cache[step_key], format="audio/mpeg")


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
        is_converse  = st.session_state.split_mode == "converse"
        next_label   = "🎤 Start Voice Assignment →" if is_converse else "Assign Items →"
        if st.button(
            next_label, type="primary", use_container_width=True,
            disabled=len(st.session_state.participants) == 0,
        ):
            # Initialise assignment sets keyed by item index
            for idx in range(len(st.session_state.extracted_bill.items)):
                st.session_state.assignments.setdefault(idx, set())
            if is_converse:
                _reset_voice_state()
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


def _render_converse_step() -> None:
    bill         = st.session_state.extracted_bill
    participants = st.session_state.participants
    assignments  = st.session_state.assignments

    pending = [i for i in range(len(bill.items)) if not assignments.get(i)]

    st.markdown("**🎤 Voice assignment**")
    st.caption("Listen to each item and speak who it should be split between.")

    # ── Live-updating item list ────────────────────────────────────────────────
    for i, item in enumerate(bill.items):
        assigned   = assignments.get(i, set())
        qty_tag    = f"  ×{item.quantity}" if item.quantity > 1 else ""
        is_current = bool(pending) and i == pending[0]
        marker     = "👉" if is_current else ("✅" if assigned else "⏳")

        m_col, name_col, status_col, redo_col = st.columns([1, 5, 4, 1])
        with m_col:
            st.markdown(marker)
        with name_col:
            st.markdown(f"**{item.name}**{qty_tag}")
        with status_col:
            if assigned:
                share = item.price / len(assigned)
                st.caption(f"${share:.2f} each · {', '.join(sorted(assigned))}")
            else:
                st.caption(f"${item.price:.2f} · pending")
        with redo_col:
            if assigned and st.button("↺", key=f"redo_{i}", help="Redo this item's assignment"):
                assignments[i] = set()
                _reset_voice_state()
                st.rerun()

    st.divider()

    # ── All items assigned ─────────────────────────────────────────────────────
    if not pending:
        _speak_once(
            "all-done",
            "All done! Here's a summary of how everything is split. "
            "Take a look and confirm when you're ready.",
        )
        st.success("All items assigned! Take a look above, or tap ↺ to redo one.")
        if st.button("See Summary →", type="primary", use_container_width=True):
            st.session_state.split_step = "summary"
            st.rerun()
        if st.button("⌨️  Assign manually instead", use_container_width=True):
            _switch_to_manual()
        return

    # ── Current item prompt ────────────────────────────────────────────────────
    idx     = pending[0]
    item    = bill.items[idx]
    attempt = st.session_state.voice_attempt

    if st.session_state.voice_clarify_msg:
        message  = st.session_state.voice_clarify_msg
        step_key = f"{idx}-clarify-{attempt}"
    elif st.session_state.voice_confirm_pending:
        message = (
            f"{st.session_state.voice_confirm_pending} "
            f"Next — {item.name}, ${item.price:.2f}. Who should this be split between?"
        )
        step_key = f"{idx}-prompt-confirmed"
    else:
        message  = f"{item.name}, ${item.price:.2f}. Who should this be split between?"
        step_key = f"{idx}-prompt-fresh"

    _speak_once(step_key, message)
    st.info(f"🗣️ {message}")

    mic_key = f"voice_mic_{idx}_{attempt}"
    rec = st.audio_input("Speak your answer", key=mic_key)

    if rec is not None:
        with st.spinner("Listening…"):
            try:
                transcript = transcribe(rec.read(), "response.wav")
            except Exception as exc:
                st.error(f"Transcription error: {exc}")
                transcript = ""

        if not transcript:
            st.session_state.voice_clarify_msg     = "I didn't catch that — could you say the names again?"
            st.session_state.voice_confirm_pending = None
            st.session_state.voice_attempt        += 1
            st.rerun()

        st.session_state.voice_log.append({"role": "user", "text": transcript})

        with st.spinner("Thinking…"):
            try:
                intent = parse_assignment(transcript, item.name, participants)
            except Exception as exc:
                st.error(f"Intent parsing error: {exc}")
                intent = None

        if intent is None or intent.needs_clarification or not intent.matched_participants:
            st.session_state.voice_clarify_msg = (
                f"I didn't catch that — who did you mean? The participants are "
                f"{', '.join(participants)}."
            )
            st.session_state.voice_confirm_pending = None
            st.session_state.voice_attempt        += 1
            st.rerun()

        matched              = intent.matched_participants
        assignments[idx]     = set(matched)
        share                = item.price / len(matched)
        confirm_line         = f"Got it — {item.name} split between {', '.join(matched)}, ${share:.2f} each."
        st.session_state.voice_log.append({"role": "assistant", "text": confirm_line})
        st.session_state.voice_confirm_pending = confirm_line + " Moving on."
        st.session_state.voice_clarify_msg     = None
        st.session_state.voice_attempt         = 0
        st.rerun()

    if st.session_state.voice_log:
        with st.expander("Conversation so far", expanded=False):
            for entry in st.session_state.voice_log[-8:]:
                who = "🧑 You" if entry["role"] == "user" else "🧾 Assistant"
                st.caption(f"**{who}:** {entry['text']}")

    st.divider()
    if st.button("⌨️  Assign manually instead", use_container_width=True):
        _switch_to_manual()


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
        st.caption("Price (each) is per-unit. \"Price (n items)\" below updates automatically with Qty.")

        # The base df passed to data_editor must stay stable across reruns (always
        # derived from the saved bill, never re-injected with pending edits) —
        # otherwise Streamlit treats the new "default" as already matching the
        # tracked edit and silently clears its own edit-tracking for that key,
        # which loses the edit the next time this reruns (e.g. on Save click).
        df = pd.DataFrame([
            {
                "Item": i.name,
                "Qty": i.quantity,
                "Price (each)": round(i.price / i.quantity, 2) if i.quantity else i.price,
            }
            for i in bill.items
        ])
        edited = st.data_editor(
            df, num_rows="dynamic", use_container_width=True,
            column_config={
                "Item":         st.column_config.TextColumn("Item", required=True),
                "Qty":          st.column_config.NumberColumn("Qty", min_value=1, step=1, format="%d"),
                "Price (each)": st.column_config.NumberColumn("Price (each)", min_value=0.0, step=0.01, format="$%.2f"),
            },
            key="items_editor",
        )

        # Derived "Price (n items)" preview — computed from `edited` (safe: this is
        # a plain local read, not fed back into the widget's own `data` argument).
        valid_rows = [
            row for _, row in edited.iterrows()
            if not (pd.isna(row.get("Item")) or str(row.get("Item", "")).strip() == "")
        ]
        line_totals = [
            round(float(row.get("Qty") or 1) * float(row.get("Price (each)") or 0.0), 2)
            for row in valid_rows
        ]
        if valid_rows:
            st.dataframe(
                pd.DataFrame({
                    "Item": [row["Item"] for row in valid_rows],
                    "Price (n items)": [f"${t:.2f}" for t in line_totals],
                }),
                use_container_width=True, hide_index=True,
            )

        c1, c2, c3 = st.columns(3)
        with c1:
            new_tax = st.number_input("Tax ($)",  min_value=0.0, value=float(bill.tax), step=0.01, format="%.2f", key="edit_tax")
        with c2:
            new_tip = st.number_input("Tip ($)",  min_value=0.0, value=float(bill.tip), step=0.01, format="%.2f", key="edit_tip")
        with c3:
            item_sum  = round(sum(line_totals), 2)
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

    # ── Converse flow ─────────────────────────────────────────────────────────
    elif st.session_state.split_mode == "converse":
        step = st.session_state.split_step
        if step == "names":
            _render_names_step()
        elif step == "assign":
            _render_converse_step()
        elif step == "summary":
            _render_summary_step()

    # ── Default: main action buttons ──────────────────────────────────────────
    else:
        col_edit, col_split = st.columns(2)
        with col_edit:
            if st.button("✏️  Need more edits?", use_container_width=True):
                st.session_state.edit_mode = True
                st.session_state.pop("items_editor", None)
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
    st.session_state.pop("items_editor", None)
    _reset_voice_state()


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
                        st.session_state.pop("items_editor", None)
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
    chat_val = st.chat_input(
        "Type items, paste a bill, attach a receipt, or record your voice…",
        accept_file=True,
        file_type=["jpg", "jpeg", "png", "pdf"],
        max_upload_size=10,
        accept_audio=True,
    )

    if chat_val:
        text       = chat_val.text.strip() if chat_val.text else None
        file_bytes = file_name = file_type = None

        if chat_val.files:
            up = chat_val.files[0]
            file_bytes = up.read()
            file_name  = up.name
            file_type  = up.type
        elif chat_val.audio:
            file_bytes = chat_val.audio.read()
            file_name  = "voice-note.wav"
            file_type  = "audio/wav"

        st.session_state.file_bytes = file_bytes
        st.session_state.file_name  = file_name
        st.session_state.file_type  = file_type
        _submit(text)
        st.rerun()
