"""
state.py — Multi-bill session state

Each attached/typed/spoken bill becomes an independent `BillRecord` with its
own extraction result, participants, assignments, and voice-conversation
state, keyed by a unique id. `st.session_state.bills` holds all of them for
the session; `bill_order` tracks insertion order; `active_bill_id` tracks
which bill's chip is currently selected in the chat view.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import streamlit as st

from agents.extractor import BillItem, ExtractedBill

_WELCOME = (
    "Hi! I'm your AI bill splitter. 👋\n\n"
    "Send me one or more bills and I'll split each one fairly between everyone in your group:\n\n"
    "- 📎 **Attach** one or more receipt photos or PDFs at once\n"
    "- ⌨️  **Type** the items and prices directly\n"
    "- 🎤  **Speak** your bill — record a voice note"
)


@dataclass
class BillRecord:
    id:          str
    label:       str
    source_name: str | None
    bill:        ExtractedBill

    edit_mode:  bool = False
    split_mode: str | None = None   # None | "choosing" | "type" | "converse"
    split_step: str = "names"       # "names" | "assign"

    participants: list[str] = field(default_factory=list)
    assignments:  dict[int, set[str]] = field(default_factory=dict)

    # voice assignment loop (converse mode)
    voice_clarify_msg: str | None = None
    voice_attempt:      int = 0
    voice_played_key:   str | None = None
    voice_audio_cache:  dict = field(default_factory=dict)
    voice_log:          list = field(default_factory=list)


_TOP_LEVEL_DEFAULTS_KEYS = ["messages", "bills", "bill_order", "active_bill_id", "pending_inputs"]
_WIDGET_KEY_PREFIXES = (
    "items_editor_", "voice_mic_", "chip_", "asgn_", "rm_p_",
    "redo_", "name_input_", "edit_tax_", "edit_tip_",
    "summary_btn_", "next_btn_",
)


def init_state() -> None:
    if "bill_counter" not in st.session_state:
        st.session_state.bill_counter = 0
    defaults = {
        "messages":       [{"role": "assistant", "content": _WELCOME}],
        "bills":          {},
        "bill_order":     [],
        "active_bill_id": None,
        "pending_inputs": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset_all() -> None:
    """Full reset — clears every bill and starts a brand-new session.
    Does not rerun/switch pages itself; the caller decides what to do next
    (st.rerun() to stay put, or st.switch_page() to also navigate)."""
    keep_counter = st.session_state.get("bill_counter", 0)
    for k in _TOP_LEVEL_DEFAULTS_KEYS:
        st.session_state.pop(k, None)
    for k in list(st.session_state.keys()):
        if k.startswith(_WIDGET_KEY_PREFIXES):
            st.session_state.pop(k, None)
    st.session_state.bill_counter = keep_counter
    init_state()


def new_bill_record(bill: ExtractedBill, source_name: str | None) -> BillRecord:
    st.session_state.bill_counter += 1
    n  = st.session_state.bill_counter
    ts = time.strftime("%Y%m%d_%H%M%S")
    label = f"Receipt {n}" + (f" — {source_name}" if source_name else "")
    return BillRecord(id=f"bill_{ts}_{n}", label=label, source_name=source_name, bill=bill)


def reset_voice_state(rec: BillRecord) -> None:
    rec.voice_clarify_msg = None
    rec.voice_attempt     = 0
    rec.voice_played_key  = None
    rec.voice_audio_cache = {}
    rec.voice_log         = []


def is_fully_assigned(rec: BillRecord) -> bool:
    # A bill with no line items (e.g. a failed extraction) has nothing left
    # to assign, so it's vacuously done — matches the assign-step UI, which
    # shows the same "all assigned" completion state for an empty item list.
    return all(rec.assignments.get(i) for i in range(len(rec.bill.items)))


def next_unfinished_bill(current_id: str) -> str | None:
    order = st.session_state.bill_order
    idx   = order.index(current_id)
    for bid in order[idx + 1:] + order[:idx]:
        if not is_fully_assigned(st.session_state.bills[bid]):
            return bid
    return None


def to_bill_dict(rec: BillRecord) -> dict:
    bill = rec.bill
    return {
        "bill_id":            rec.id,
        "label":              rec.label,
        "items":              [{"name": i.name, "quantity": i.quantity, "price": i.price} for i in bill.items],
        "subtotal":           bill.subtotal,
        "tax":                bill.tax,
        "tip":                bill.tip,
        "total":              bill.total,
        "validation_passed":  bill.validation_passed,
        "validation_note":    bill.validation_note,
    }


def calculate_splits(rec: BillRecord) -> list[dict]:
    bill         = rec.bill
    participants = rec.participants
    assignments  = rec.assignments

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

    if results:
        diff = round(bill.total - sum(r["total"] for r in results), 2)
        if diff:
            results[0]["total"] = round(results[0]["total"] + diff, 2)

    return results
