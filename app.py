"""
app.py — AI Bill Splitter

Entry point: page config + navigation wiring only. The actual UI lives in
views/chat_view.py (multi-bill ingestion + assignment) and
views/summary_view.py (all-bills summary, on its own page/URL).
"""
import streamlit as st

from state import init_state
from views import chat_view, summary_view

st.set_page_config(
    page_title="AI Bill Splitter",
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed",
)

init_state()

# Each page's render function takes the *other* page's StreamlitPage object so
# it can st.switch_page() across — the lambdas close over these module-level
# names, which are both bound by the time st.navigation() actually runs a page.
chat_page = st.Page(
    lambda: chat_view.render_chat(summary_page),
    title="Chat", icon="🧾", url_path="chat", default=True,
)
summary_page = st.Page(
    lambda: summary_view.render_summary(chat_page),
    title="Summary", icon="💰", url_path="summary",
)

nav = st.navigation([chat_page, summary_page], position="hidden")
nav.run()
