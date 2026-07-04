# AI Bill Splitter

Voice-driven, AI-powered bill splitting app. Upload a receipt photo, speak naturally to assign items to people, get instant accurate splits.

---

## Build Phases

### Phase 1 — Backend Foundation + Receipt Parsing ✅
**Goal:** Get a working API that takes a receipt image and returns structured JSON.

What we build:
- [x] FastAPI project structure
- [x] Claude Vision API integration via tool use (receipt → structured JSON)
- [x] `POST /receipts/parse` endpoint
- [x] Pydantic schemas for receipt data
- [x] Simple HTML upload UI at `/`
- [x] `.env` config setup

Deliverable: Upload a receipt photo → get items, prices, tax, tip, total displayed in browser

---

### Phase 2 — Data Layer + Math Engine ✅
**Goal:** Persist expenses and calculate accurate per-person splits.

What we build:
- [x] SQLite database via SQLAlchemy
- [x] Tables: `expenses`, `participants`, `items`, `assignments`
- [x] CRUD API routes: create expense, add/remove participants, assign items, get summary
- [x] Math engine: per-item splits + proportional tax/tip + rounding correction
- [x] 4-step UI: Upload → Add People → Assign Items → Summary

Deliverable: Full working manual bill splitter in the browser

---

### Phase 3 — UI Improvements + Edge Case Handling
**Goal:** Make the assignment flow more accurate and handle real-world receipt edge cases.

What we build:
- [ ] **Quantity expansion** — when an item has quantity > 1 (e.g. "Milk ×2 — $3.00"),
      show an "Expand" button that splits it into individual rows ($1.50 each) so each
      unit can be assigned to a different person independently.
      > _Example: Alice gets 1 milk, Bob gets 1 milk → each assigned separately at $1.50_
- [ ] Edit parsed items before saving (fix OCR mistakes in item name or price)
- [ ] "Select All" / "Split Equally" shortcut per item
- [ ] Show running per-person total on the assign screen (updates as you tap)
- [ ] Handle unassigned items warning before reaching summary
- [ ] Tax/tip split toggle: proportional (default) vs equal

Deliverable: Accurate, user-friendly assignment flow that handles real receipts cleanly

---

### Phase 4 — Voice Layer
**Goal:** Replace tapping with speaking. Say "bananas — me and Aarav" and it assigns automatically.

What we build:
- [ ] Microphone recording button in the browser
- [ ] Stream audio to OpenAI Whisper API (speech-to-text)
- [ ] Claude intent extraction: transcript → structured assignment `{item, people}`
- [ ] Fuzzy item matching (user says "milk", receipt says "OAT MLK ORG 64OZ")
- [ ] Live UI updates as voice assignments come in
- [ ] Editable chips to correct misheard names
- [ ] Undo last voice command

Deliverable: Voice-driven assignment that feels magical

---

### Phase 5 — Polish + Sharing
**Goal:** Make it production-ready and shareable.

What we build:
- [ ] PDF export with itemized breakdown per person
- [ ] WhatsApp share (formatted message)
- [ ] Venmo/PayPal deep links
- [ ] Loading states, error messages, empty states
- [ ] Smooth animations as items get assigned
- [ ] Settings: tax/tip split method, currency symbol
- [ ] Dark mode

Deliverable: Polished MVP ready to show in a portfolio or use with friends

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python + FastAPI |
| Receipt Parsing | Claude API (Anthropic) — Vision |
| Speech-to-Text | OpenAI Whisper API |
| Intent Extraction | Claude API — structured output |
| Database | SQLite (dev) → PostgreSQL (prod) |
| Frontend | Next.js |
| Hosting | Vercel (frontend) + Railway (backend) |

---

## Project Structure

```
ai-splitwise-main/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic request/response models
│   │   ├── routes/
│   │   │   └── receipts.py      # Receipt parsing endpoints
│   │   └── services/
│   │       └── ocr.py           # Claude Vision integration
│   └── tests/
├── frontend/                    # Added in Phase 3
├── .env                         # Your API keys (never commit this)
├── .env.example                 # Template for API keys
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
