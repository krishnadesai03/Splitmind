# AI Bill Splitter

Voice-driven, AI-powered bill splitting app. Upload a receipt photo, speak naturally to assign items to people, get instant accurate splits.

---

## Build Phases

### Phase 1 — Multimodal Input + Extraction ✅
Upload a receipt (image/PDF), paste text, or speak — Agent 0 routes the input, Agent 1 extracts items/prices/tax/tip/total via OpenAI vision + structured outputs.

### Phase 2 — Validation + Review ✅
Agent 2 checks subtotal + tax + tip == total (self-corrects, up to 2 retries); editable items table lets you fix names/qty/price before splitting.

### Phase 3 — Assignment + Math Engine ✅
Tap-to-assign items per person, or use the conversational voice flow (ElevenLabs speaks each item, Whisper transcribes your reply, Agent 3 parses intent); math engine computes proportional tax/tip splits.

### Phase 4 — Fine-Tuned Classifier + A/B Tab 🚧
Clean up abbreviated receipt text ("OAT MLK ORG 64Z" → "Oat Milk (Organic, 64oz)") with a fine-tuned model, with a comparison tab against the base model.

### Phase 5 — Output + Polish 🚧
PDF export, WhatsApp-formatted summary, Venmo deep links, README + demo video for the portfolio.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| App / UI | Streamlit |
| Receipt Parsing | OpenAI GPT-4o — Vision + structured outputs |
| Text / Intent Extraction | OpenAI GPT-4o-mini — structured outputs |
| Speech-to-Text | OpenAI Whisper API |
| Text-to-Speech | ElevenLabs |
| State | Streamlit session state (in-memory) |
| Hosting | Streamlit Community Cloud |

---

## Project Structure

```
ai-splitwise-main/
├── app.py                     # Streamlit entry point
├── state.py                   # Session state helpers
├── views/
│   ├── chat_view.py           # Main chat UI: input, review table, assignment
│   └── summary_view.py        # Final per-person split summary
├── agents/
│   ├── router.py              # Agent 0: classify input (image/audio/text)
│   ├── extractor.py           # Agent 1: extract items+prices (vision + text)
│   ├── validator.py           # Agent 2: math validation + self-correction
│   └── voice_intent.py        # Agent 3: voice reply → assignment intent
├── services/
│   ├── whisper.py             # OpenAI Whisper STT wrapper
│   └── elevenlabs.py          # ElevenLabs TTS wrapper
├── .env.example                # Template for API keys
├── requirements.txt
└── README.md
```

---

## Setup

```bash
# 1. Activate virtual environment
source venv/Scripts/activate      # Windows (Git Bash)
# or
venv\Scripts\activate             # Windows (CMD/PowerShell)

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env file and add your API key
cp .env.example .env
# Edit .env and paste your Anthropic API key

# 4. Run the backend
cd backend
uvicorn app.main:app --reload
```

API docs available at: http://localhost:8000/docs
