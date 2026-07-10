"""
views/summary_view.py — Summary page: all bills' splits, clearly separated

A dedicated page (reached via st.switch_page) rather than a step inside the
chat flow, so results survive independently of the conversation and can show
every bill — done or still in progress — at a glance.
"""
from __future__ import annotations

import streamlit as st

import state

_CSS = """
<style>
#MainMenu, footer, header { visibility: hidden; }
.block-container { max-width: 740px; padding-top: 2rem; padding-bottom: 3rem; }
</style>
"""


def _render_bill_summary(rec) -> None:
    st.markdown(f"### {rec.label}")

    if not state.is_fully_assigned(rec):
        st.info("Still being split — go back to Chat to finish assigning items.")
        return

    results = state.calculate_splits(rec)
    for r in results:
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"**{r['name']}**")
            # Escaped "$" — two-or-more literal "$" in one markdown string
            # otherwise renders as LaTeX/KaTeX math (see chat_view.render_bill_card).
            parts = [f"items \\${r['subtotal']:.2f}"]
            if r["tax"] > 0: parts.append(f"tax \\${r['tax']:.2f}")
            if r["tip"] > 0: parts.append(f"tip \\${r['tip']:.2f}")
            st.caption("  +  ".join(parts))
        with right:
            st.markdown(f"### ${r['total']:.2f}")


def _render_grand_total(completed: list) -> None:
    st.divider()
    st.markdown("### 🧮 Grand total per person (all bills)")
    grand: dict[str, float] = {}
    for rec in completed:
        for r in state.calculate_splits(rec):
            grand[r["name"]] = grand.get(r["name"], 0.0) + r["total"]

    for name, total in sorted(grand.items(), key=lambda kv: -kv[1]):
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"**{name}**")
        with right:
            st.markdown(f"### ${total:.2f}")


def render_summary(chat_page) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    state.init_state()

    h_col, btn_col = st.columns([8, 2])
    with h_col:
        st.markdown("## 💰 Summary")
        st.caption("Who owes what, across every bill in this session.")
    with btn_col:
        st.write("")
        if st.button("← Back to Chat", use_container_width=True, key="back_to_chat"):
            st.switch_page(chat_page)

    st.divider()

    order = st.session_state.bill_order
    if not order:
        st.info("No bills yet. Head back to Chat to attach, type, or speak a bill.")
        if st.button("Go to Chat →", type="primary", use_container_width=True, key="go_chat_empty"):
            st.switch_page(chat_page)
        return

    bills = [st.session_state.bills[bid] for bid in order]

    for i, rec in enumerate(bills):
        _render_bill_summary(rec)
        if i < len(bills) - 1:
            st.divider()

    completed = [rec for rec in bills if state.is_fully_assigned(rec)]
    if len(completed) >= 2:
        _render_grand_total(completed)

    st.divider()
    back_col, new_col = st.columns(2)
    with back_col:
        if st.button("← Back to Chat", use_container_width=True, key="back_to_chat_footer"):
            st.switch_page(chat_page)
    with new_col:
        if st.button("＋ New session", type="primary", use_container_width=True, key="new_session"):
            state.reset_all()
            st.switch_page(chat_page)
