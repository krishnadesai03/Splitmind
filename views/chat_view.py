"""
views/chat_view.py — Chat page: multi-bill ingestion + per-bill assignment flow

Handles attaching one or more receipts (or typing/speaking a bill) in a
single chat, extracting each into its own BillRecord, and letting the user
switch between bills via chips to run an independent Type or Converse
(voice) assignment flow for each.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import state
from agents.extractor import BillItem, ExtractedBill, extract
from agents.router import route
from agents.validator import validate
from agents.voice_intent import parse_assignment
from services.elevenlabs import speak
from services.whisper import transcribe
from state import BillRecord

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
<style>
#MainMenu, footer, header { visibility: hidden; }
.block-container { max-width: 740px; padding-top: 2rem; padding-bottom: 5.5rem; }
</style>
"""


# ── Bill card (read-only, stored in message for persistence) ──────────────────
def render_bill_card(bill: dict) -> None:
    df = pd.DataFrame([
        {"Item": i["name"], "Qty": i["quantity"], "Price": f"${i['price']:.2f}"}
        for i in bill["items"]
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Escape "$" — Streamlit markdown renders two or more literal "$" in one
    # string as LaTeX/KaTeX math, garbling amounts like "Subtotal $9.48".
    parts = [f"Subtotal **\\${bill['subtotal']:.2f}**"]
    if bill["tax"] > 0: parts.append(f"Tax **\\${bill['tax']:.2f}**")
    if bill["tip"] > 0: parts.append(f"Tip **\\${bill['tip']:.2f}**")
    parts.append(f"Total **\\${bill['total']:.2f}**")
    st.caption("  ·  ".join(parts))

    if not bill.get("validation_passed", True) and bill.get("validation_note"):
        st.warning(f"⚠️ {bill['validation_note']}")


# ── Save edits ────────────────────────────────────────────────────────────────
def _save_edits(rec: BillRecord, edited_df: pd.DataFrame, tax: float, tip: float, total: float) -> None:
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
            price=round(price_each * qty, 2),
        ))

    subtotal = round(sum(i.price for i in items), 2)
    rec.bill = ExtractedBill(
        items=items, subtotal=subtotal,
        tax=round(tax, 2), tip=round(tip, 2), total=round(total, 2),
        validation_passed=True, validation_note=None,
    )
    rec.assignments = {}  # reset assignments when bill changes

    bill_dict = state.to_bill_dict(rec)
    for msg in reversed(st.session_state.messages):
        for b in msg.get("bills", []):
            if b.get("bill_id") == rec.id:
                b.update(bill_dict)
                break

    rec.edit_mode = False
    st.rerun()


# ── Voice assignment state helpers ────────────────────────────────────────────
def _switch_to_manual(rec: BillRecord) -> None:
    rec.split_mode = "type"
    state.reset_voice_state(rec)
    st.rerun()


def _speak_once(rec: BillRecord, step_key: str, text: str) -> None:
    """Play `text` via ElevenLabs the first time `step_key` is seen this turn;
    on later reruns for the same step_key, show a non-autoplaying replay control."""
    cache = rec.voice_audio_cache
    if step_key not in cache:
        try:
            cache[step_key] = speak(text)
        except Exception as exc:
            st.warning(f"Voice playback unavailable: {exc}")
            rec.voice_played_key = step_key
            return

    if rec.voice_played_key != step_key:
        st.audio(cache[step_key], format="audio/mpeg", autoplay=True)
        rec.voice_played_key = step_key
    else:
        st.audio(cache[step_key], format="audio/mpeg")


# ── Converse-mode phrasing — rotated by item index / attempt so the same
# exact question isn't read out on every single turn ──────────────────────────
_QUESTION_VARIANTS = [
    "Who should this be split between?",
    "Who's this one for?",
    "Who had this?",
    "Who's sharing this?",
]
_SILENCE_VARIANTS = [
    "Didn't catch that — go ahead.",
    "Still listening — who was that?",
]


# ── Completion panel (shared by Type + Converse flows) ─────────────────────────
def _render_completion_panel(rec: BillRecord, summary_page) -> None:
    next_id = state.next_unfinished_bill(rec.id)
    if next_id:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💰 View Summary", type="primary", use_container_width=True, key=f"summary_btn_{rec.id}"):
                st.switch_page(summary_page)
        with c2:
            next_label = st.session_state.bills[next_id].label
            if st.button(f"Continue to {next_label} →", use_container_width=True, key=f"next_btn_{rec.id}"):
                st.session_state.active_bill_id = next_id
                st.rerun()
    else:
        if st.button("💰 View Summary", type="primary", use_container_width=True, key=f"summary_btn_{rec.id}"):
            st.switch_page(summary_page)


# ── Split sub-steps ───────────────────────────────────────────────────────────
def _render_names_step(rec: BillRecord) -> None:
    st.markdown("**Who's splitting this bill?**")
    st.caption("Add everyone who shared this bill.")

    if rec.participants:
        cols = st.columns(min(len(rec.participants), 4))
        for i, name in enumerate(list(rec.participants)):
            with cols[i % min(len(rec.participants), 4)]:
                if st.button(f"{name}  ✕", key=f"rm_p_{rec.id}_{i}", use_container_width=True):
                    rec.participants.remove(name)
                    for asgn in rec.assignments.values():
                        asgn.discard(name)
                    st.rerun()

    # st.form + clear_on_submit=True so pressing Enter in the text box (or
    # clicking Add) both submit AND reset the input back to empty — otherwise
    # the typed name lingers and has to be cleared by hand before the next one.
    with st.form(key=f"add_participant_form_{rec.id}", clear_on_submit=True):
        add_col, btn_col = st.columns([5, 1])
        with add_col:
            new_name = st.text_input(
                "name", placeholder="Enter a name…",
                label_visibility="collapsed", key=f"name_input_{rec.id}",
            )
        with btn_col:
            submitted = st.form_submit_button("Add", use_container_width=True)
        if submitted:
            n = new_name.strip()
            if n and n not in rec.participants:
                rec.participants.append(n)
                st.rerun()

    st.write("")
    back_col, next_col = st.columns(2)
    with back_col:
        if st.button("← Back", use_container_width=True, key=f"names_back_{rec.id}"):
            rec.split_mode = "choosing"
            st.rerun()
    with next_col:
        is_converse = rec.split_mode == "converse"
        next_label  = "🎤 Start Voice Assignment →" if is_converse else "Assign Items →"
        if st.button(
            next_label, type="primary", use_container_width=True,
            disabled=len(rec.participants) == 0, key=f"names_next_{rec.id}",
        ):
            for idx in range(len(rec.bill.items)):
                rec.assignments.setdefault(idx, set())
            if is_converse:
                state.reset_voice_state(rec)
            rec.split_step = "assign"
            st.rerun()


def _render_assign_step(rec: BillRecord, summary_page) -> None:
    bill         = rec.bill
    participants = rec.participants
    assignments  = rec.assignments

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
                    key=f"asgn_{rec.id}_{idx}_{j}",
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

    if st.button("← Back", use_container_width=True, key=f"assign_back_{rec.id}"):
        rec.split_step = "names"
        st.rerun()

    if unassigned_names:
        st.warning(f"Still unassigned: {', '.join(unassigned_names)}")
    else:
        st.success("✅ All items assigned for this bill!")
        _render_completion_panel(rec, summary_page)


def _render_converse_step(rec: BillRecord, summary_page) -> None:
    bill         = rec.bill
    participants = rec.participants
    assignments  = rec.assignments

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
            if assigned and st.button("↺", key=f"redo_{rec.id}_{i}", help="Redo this item's assignment"):
                assignments[i] = set()
                state.reset_voice_state(rec)
                st.rerun()

    st.divider()

    # ── All items assigned ─────────────────────────────────────────────────────
    if not pending:
        _speak_once(rec, "all-done", "That's everything — take a look whenever you're ready.")
        st.success("All items assigned! Take a look above, or tap ↺ to redo one.")
        _render_completion_panel(rec, summary_page)
        if st.button("⌨️  Assign manually instead", use_container_width=True, key=f"manual_{rec.id}"):
            _switch_to_manual(rec)
        return

    # ── Current item prompt ────────────────────────────────────────────────────
    idx     = pending[0]
    item    = bill.items[idx]
    attempt = rec.voice_attempt
    is_bills_first_prompt = (
        len(st.session_state.bill_order) > 1
        and idx == 0
        and not any(assignments.values())
    )
    bill_intro = f"Let's split {rec.label}. " if is_bills_first_prompt else ""

    if rec.voice_clarify_msg:
        message  = rec.voice_clarify_msg
        step_key = f"{idx}-clarify-{attempt}"
    else:
        # Deterministic per item index (not random) so a rerun before the user
        # answers can't change the displayed text out from under the already-
        # cached spoken audio for this step_key.
        question   = _QUESTION_VARIANTS[idx % len(_QUESTION_VARIANTS)]
        message    = f"{bill_intro}{item.name}, ${item.price:.2f}. {question}"
        step_key   = f"{idx}-prompt-fresh"

    _speak_once(rec, step_key, message)
    st.info(f"🗣️ {message}")

    # Items still open, in prompting order — passed to the intent parser so it
    # can resolve "this and the next two", "the rest", or a specific item by
    # name, not just the single current item.
    pending_items = [
        {"index": i, "name": bill.items[i].name, "price": bill.items[i].price}
        for i in pending
    ]

    mic_key = f"voice_mic_{rec.id}_{idx}_{attempt}"
    audio_rec = st.audio_input("Speak your answer", key=mic_key)
    if not rec.voice_log:
        st.caption(
            "Tip: you can also say things like \"split the rest between all of us\" "
            "or \"this and the tomatoes go to Sam and Priya.\""
        )

    if audio_rec is not None:
        with st.spinner("Listening…"):
            try:
                transcript = transcribe(audio_rec.read(), "response.wav")
            except Exception as exc:
                st.error(f"Transcription error: {exc}")
                transcript = ""

        if not transcript:
            rec.voice_clarify_msg = _SILENCE_VARIANTS[attempt % len(_SILENCE_VARIANTS)]
            rec.voice_attempt    += 1
            st.rerun()

        rec.voice_log.append({"role": "user", "text": transcript})

        with st.spinner("Thinking…"):
            try:
                intent = parse_assignment(transcript, pending_items, participants)
            except Exception as exc:
                st.error(f"Intent parsing error: {exc}")
                intent = None

        if (
            intent is None or intent.needs_clarification
            or not intent.matched_participants or not intent.item_indices
        ):
            rec.voice_clarify_msg = (
                f"Not sure I got that — the group is {', '.join(participants)}."
            )
            rec.voice_attempt += 1
            st.rerun()

        # No spoken confirmation before moving on — the live item list above
        # (plus the ↺ redo button) already shows what was just assigned, and
        # repeating it back on every turn read as robotic/templated.
        matched = intent.matched_participants
        for i in intent.item_indices:
            assignments[i] = set(matched)
        assigned_names = [bill.items[i].name for i in intent.item_indices]
        rec.voice_log.append({
            "role": "assistant",
            "text": f"{', '.join(assigned_names)} → {', '.join(matched)}",
        })
        rec.voice_clarify_msg = None
        rec.voice_attempt     = 0
        st.rerun()

    if rec.voice_log:
        with st.expander("Conversation so far", expanded=False):
            for entry in rec.voice_log[-8:]:
                who = "🧑 You" if entry["role"] == "user" else "🧾 Assistant"
                st.caption(f"**{who}:** {entry['text']}")

    st.divider()
    if st.button("⌨️  Assign manually instead", use_container_width=True, key=f"manual_{rec.id}"):
        _switch_to_manual(rec)


# ── Bill chips ────────────────────────────────────────────────────────────────
def _render_bill_chips(summary_page) -> None:
    order = st.session_state.bill_order
    if not order:
        return

    st.write("")
    cols = st.columns(len(order))
    for i, bid in enumerate(order):
        rec = st.session_state.bills[bid]
        status = "✅" if state.is_fully_assigned(rec) else ("🔄" if rec.split_mode else "🆕")
        is_active = bid == st.session_state.active_bill_id
        with cols[i]:
            if st.button(
                f"{status} {rec.label}", key=f"chip_{bid}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                st.session_state.active_bill_id = bid
                st.rerun()

    ready = [b for b in order if state.is_fully_assigned(st.session_state.bills[b])]
    if ready:
        if st.button(
            f"💰 View Summary ({len(ready)}/{len(order)} ready)",
            use_container_width=True, key="summary_btn_persistent",
        ):
            st.switch_page(summary_page)

    st.divider()


# ── Per-bill workspace (edit / choosing / type / converse / default) ──────────
def _render_bill_workspace(rec: BillRecord, summary_page) -> None:
    st.markdown(f"### {rec.label}")

    if rec.edit_mode:
        st.markdown("**Edit your bill — fix prices, rename items, or add missing rows:**")
        st.caption("Price (each) is per-unit. \"Price (n items)\" below updates automatically with Qty.")

        df = pd.DataFrame([
            {
                "Item": i.name,
                "Qty": i.quantity,
                "Price (each)": round(i.price / i.quantity, 2) if i.quantity else i.price,
            }
            for i in rec.bill.items
        ])
        edited = st.data_editor(
            df, num_rows="dynamic", use_container_width=True,
            column_config={
                "Item":         st.column_config.TextColumn("Item", required=True),
                "Qty":          st.column_config.NumberColumn("Qty", min_value=1, step=1, format="%d"),
                "Price (each)": st.column_config.NumberColumn("Price (each)", min_value=0.0, step=0.01, format="$%.2f"),
            },
            key=f"items_editor_{rec.id}",
        )

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
            new_tax = st.number_input("Tax ($)", min_value=0.0, value=float(rec.bill.tax), step=0.01, format="%.2f", key=f"edit_tax_{rec.id}")
        with c2:
            new_tip = st.number_input("Tip ($)", min_value=0.0, value=float(rec.bill.tip), step=0.01, format="%.2f", key=f"edit_tip_{rec.id}")
        with c3:
            item_sum  = round(sum(line_totals), 2)
            new_total = round(item_sum + new_tax + new_tip, 2)
            st.metric("Total ($)", f"${new_total:.2f}")

        save_col, cancel_col = st.columns(2)
        with save_col:
            if st.button("💾  Save changes", type="primary", use_container_width=True, key=f"save_{rec.id}"):
                _save_edits(rec, edited, new_tax, new_tip, new_total)
        with cancel_col:
            if st.button("✕  Cancel", use_container_width=True, key=f"cancel_edit_{rec.id}"):
                rec.edit_mode = False
                st.rerun()

    elif rec.split_mode == "choosing":
        st.markdown("**How would you like to split this bill?**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⌨️  Type", use_container_width=True, key=f"choose_type_{rec.id}", help="Enter names and click to assign items"):
                rec.split_mode = "type"
                rec.split_step = "names"
                st.rerun()
        with col2:
            if st.button("🎤  Converse", type="primary", use_container_width=True, key=f"choose_converse_{rec.id}", help="Voice-guided assignment"):
                rec.split_mode = "converse"
                st.rerun()

    elif rec.split_mode == "type":
        if rec.split_step == "names":
            _render_names_step(rec)
        elif rec.split_step == "assign":
            _render_assign_step(rec, summary_page)

    elif rec.split_mode == "converse":
        if rec.split_step == "names":
            _render_names_step(rec)
        elif rec.split_step == "assign":
            _render_converse_step(rec, summary_page)

    else:
        col_edit, col_split = st.columns(2)
        with col_edit:
            if st.button("✏️  Need more edits?", use_container_width=True, key=f"edit_toggle_{rec.id}"):
                rec.edit_mode = True
                st.session_state.pop(f"items_editor_{rec.id}", None)
                st.rerun()
        with col_split:
            if st.button("✅  Ready to Split it?", type="primary", use_container_width=True, key=f"split_toggle_{rec.id}"):
                rec.split_mode = "choosing"
                st.rerun()


# ── Submit handler ────────────────────────────────────────────────────────────
def _submit(text: str | None, staged_files: list[dict]) -> None:
    if not text and not staged_files:
        return

    parts:         list[str] = []
    attachments:   list[dict] = []
    pending_inputs: list[dict] = []
    # Echoed back via st.markdown — escape "$" so typed amounts like "$10, $4"
    # don't get interpreted as a LaTeX/KaTeX math span (see render_bill_card).
    display_text = text.replace("$", "\\$") if text else text

    if staged_files:
        for f in staged_files:
            attachments.append(f)
            if f["type"] and f["type"].startswith("audio/"):
                parts.append("🎤 **Voice note**")
            else:
                parts.append(f"📎 **{f['name']}**")
            pending_inputs.append({
                "text": None, "file_bytes": f["bytes"],
                "file_name": f["name"], "file_type": f["type"],
            })
        if display_text:
            parts.append(display_text)
    elif display_text:
        parts.append(display_text)
        pending_inputs.append({"text": text, "file_bytes": None, "file_name": None, "file_type": None})

    st.session_state.messages.append({
        "role": "user", "content": "\n\n".join(parts), "attachments": attachments,
    })
    st.session_state.pending_inputs = pending_inputs


# ── Agent pipeline (runs once per pending bill) ────────────────────────────────
def _run_pipeline_for(pending: dict, multi: bool) -> ExtractedBill | None:
    if multi:
        label = pending.get("file_name") or "this bill"
        st.markdown(f"**📎 {label}**")

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

    effective_text = pending.get("text")
    if decision and decision.route == "whisper_then_text_pipeline":
        with st.status("Transcribing your voice…", expanded=True) as s:
            try:
                effective_text = transcribe(pending.get("file_bytes"), pending.get("file_name"))
                if effective_text:
                    st.write(f"🗣️ “{effective_text}”")
                    s.update(label="✓ Transcribed your voice note", state="complete", expanded=False)
                else:
                    s.update(label="⚠️ Couldn't hear anything — try recording again", state="error", expanded=True)
                    decision = None
            except Exception as exc:
                s.update(label=f"Transcription error: {exc}", state="error", expanded=True)
                decision = None

    bill = None
    if decision:
        with st.status("Extracting bill items…", expanded=True) as s:
            try:
                bill = extract(
                    route=decision.route, text=effective_text,
                    file_bytes=pending.get("file_bytes"), file_type=pending.get("file_type"),
                )
                s.update(
                    label=f"✓ Found {len(bill.items)} item{'s' if len(bill.items) != 1 else ''}",
                    state="complete", expanded=False,
                )
            except Exception as exc:
                s.update(label=f"Extraction error: {exc}", state="error", expanded=True)

    if bill:
        with st.status("Validating numbers…", expanded=True) as s:
            try:
                bill, attempt_log = validate(
                    bill=bill, route=decision.route, text=effective_text,
                    file_bytes=pending.get("file_bytes"), file_type=pending.get("file_type"),
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
            except Exception as exc:
                s.update(label=f"Validation error: {exc}", state="error", expanded=True)

    return bill


def _render_ingestion() -> None:
    pending_list = st.session_state.pending_inputs
    multi = len(pending_list) > 1
    new_bill_dicts: list[dict] = []

    with st.chat_message("assistant", avatar="🧾"):
        for i, pending in enumerate(pending_list):
            bill = _run_pipeline_for(pending, multi)

            if bill:
                if not bill.validation_passed:
                    st.warning(
                        "📸 The image may be blurry or some prices couldn't be read clearly. "
                        "Use \"Need more edits?\" below to fix any incorrect amounts."
                    )
                rec = state.new_bill_record(bill, pending.get("file_name"))
                st.session_state.bills[rec.id] = rec
                st.session_state.bill_order.append(rec.id)
                if st.session_state.active_bill_id is None:
                    st.session_state.active_bill_id = rec.id

                bill_dict = state.to_bill_dict(rec)
                new_bill_dicts.append(bill_dict)

                st.markdown(f"Here's what I found in **{rec.label}**:")
                render_bill_card(bill_dict)
            else:
                st.markdown("Sorry, I couldn't extract the bill items from this one. Please try again.")

            if i < len(pending_list) - 1:
                st.divider()

        if len(new_bill_dicts) >= 2:
            st.markdown(f"Found **{len(new_bill_dicts)} bills** — tap a chip below to start splitting each one.")
        elif len(new_bill_dicts) == 1:
            b = new_bill_dicts[0]
            n_items = len(b["items"])
            st.markdown(f"Found **{n_items} item{'s' if n_items != 1 else ''}** — total **${b['total']:.2f}**.")

        summary_line = (
            f"Found **{len(new_bill_dicts)} bill{'s' if len(new_bill_dicts) != 1 else ''}**."
            if new_bill_dicts else "Sorry, I couldn't extract that bill."
        )
        st.session_state.messages.append({
            "role": "assistant", "content": summary_line, "bills": new_bill_dicts,
        })

    st.session_state.pending_inputs = None


# ── Page entry point ────────────────────────────────────────────────────────────
def render_chat(summary_page) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    state.init_state()

    h_col, btn_col = st.columns([8, 2])
    with h_col:
        st.markdown("## 🧾 AI Bill Splitter")
        st.caption("Upload receipts, type items, or speak — split any number of bills fairly.")
    with btn_col:
        st.write("")
        if st.button("＋ New bill", use_container_width=True, key="new_bill_header"):
            state.reset_all()
            st.rerun()

    st.divider()

    for msg in st.session_state.messages:
        avatar = "🧾" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            for att in msg.get("attachments", []):
                atype = att.get("type") or ""
                if atype.startswith("image/"):
                    st.image(att["bytes"], width=260, caption=att.get("name", ""))
                elif atype.startswith("audio/"):
                    st.audio(att["bytes"], format=atype)
            bills = msg.get("bills", [])
            for i, bill_dict in enumerate(bills):
                if len(bills) > 1:
                    st.markdown(f"**🧾 {bill_dict['label']}**")
                render_bill_card(bill_dict)
                if i < len(bills) - 1:
                    st.divider()

    if st.session_state.pending_inputs:
        _render_ingestion()

    if st.session_state.bill_order and not st.session_state.pending_inputs:
        _render_bill_chips(summary_page)
        active_id = st.session_state.active_bill_id
        if active_id and active_id in st.session_state.bills:
            _render_bill_workspace(st.session_state.bills[active_id], summary_page)

    if not st.session_state.pending_inputs:
        chat_val = st.chat_input(
            "Type items, paste a bill, attach one or more receipts, or record your voice…",
            accept_file="multiple",
            file_type=["jpg", "jpeg", "png", "pdf"],
            max_upload_size=10,
            accept_audio=True,
        )

        if chat_val:
            text   = chat_val.text.strip() if chat_val.text else None
            staged: list[dict] = []

            if chat_val.files:
                for up in chat_val.files:
                    staged.append({"bytes": up.read(), "name": up.name, "type": up.type})
            elif chat_val.audio:
                staged.append({"bytes": chat_val.audio.read(), "name": "voice-note.wav", "type": "audio/wav"})

            _submit(text, staged)
            st.rerun()
