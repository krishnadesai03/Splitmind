# AI Bill Splitter — Full Project Workflow & Build Specification

This document is the single source of truth for building the AI-powered bill splitter.
It captures every architectural decision, agent design, UI flow, and tech choice made
during planning. Read this fully before writing any code.

---

## Project Overview

An AI-powered expense splitting application with a multimodal chat interface. Users
submit a bill via text, voice, or file attachment. Three AI agents extract and validate
the bill data. The user reviews and edits items. A conversational voice agent then
guides the user through assigning each item to the people who should share it. The
final output shows exactly how much each person owes.

The goal is a backend-heavy, AI-dense portfolio project demonstrating: multimodal input
handling, agentic pipelines, LLM prompt engineering, fine-tuned model integration,
conversational voice AI (STT + TTS), and a clean Streamlit UI.

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Backend | Python + FastAPI |
| Database | SQLite via SQLAlchemy |
| LLM | Anthropic Claude API (claude-sonnet-4-6) |
| Vision | Claude Vision (image + PDF parsing) |
| Speech-to-text | OpenAI Whisper API |
| Text-to-speech | ElevenLabs API |
| Fine-tuning | OpenAI fine-tuning API (GPT-3.5-turbo) or Together AI (Llama 3.1 8B) |
| Environment | Python-dotenv for API key management |

---

## Data Models

Four core database models:

```
Expense       — id, title, subtotal, tax, tip, total, created_at
Participant   — id, expense_id, name, total_owed
Item          — id, expense_id, name, clean_name, category, price, quantity
Assignment    — id, item_id, participant_id, share
```

---

## UI Layout — Chat Interface

The app opens on a single chat-style screen modelled after Claude / ChatGPT.

The screen has:
- A message thread area (top, scrollable) showing the conversation between user and app
- A bottom input bar with exactly three controls:
  - Text box — type or paste anything
  - Mic button — hold to record a voice note
  - Attachment button — opens file picker (accepts PNG, JPG, PDF)

Every interaction happens inside this chat interface. Review screens, assignment
screens, and the final summary all appear as chat messages or inline cards within
the thread — not as separate pages.

When the user submits any input, a small status indicator appears in the chat:
- "Analyzing image..." for file attachments
- "Processing voice note..." for audio
- "Reading your bill..." for text

This status indicator is the only visible signal of the routing decision. The user
does not see which agent ran or why.

---

## Input Modes — Three Paths

### Mode 1 — Text input
User types or pastes bill content directly into the text box. This can be:
- A structured list: "Bananas $3.49, Oat Milk $5.99, Tax $0.87"
- A paragraph description: "We had dinner, pizza was $22, pasta $18, drinks $20, tip $8"
- A forwarded WhatsApp message with prices
- Any free-form text describing a bill

The text is passed directly to the Text LLM pipeline.

### Mode 2 — Voice note
User taps the mic button and records a voice note describing the bill. For example:
"Bananas three forty-nine, oat milk five ninety-nine, bread two forty-nine, tax
eighty-seven cents."

User releases the mic when done. Whisper transcribes the full recording. The
transcript is then passed to the same Text LLM pipeline as Mode 1.

This is a one-shot voice note — not a back-and-forth conversation. The entire bill
is described in one recording. The user does not need to speak item by item here;
this is just for inputting the bill contents.

### Mode 3 — File attachment
User attaches a PNG, JPG, or PDF of their receipt. The file is base64-encoded
and passed to the Vision LLM pipeline (Claude Vision).

### URL handling
URLs are not a separate input mode. If a user pastes a URL into the text box,
the text pipeline detects it, fetches and scrapes the page, strips HTML, and
treats the resulting text as a normal text input. No separate URL button exists.

---

## The Three Agents

### Agent 0 — Router
**When it runs:** Immediately on every user submission, before anything else.
**What it does:** Examines the incoming input and classifies it as one of three types:
image/PDF, audio, or text. Returns a routing decision as structured JSON.
**Output format:**
```json
{"input_type": "image", "route": "vision_pipeline"}
{"input_type": "audio", "route": "whisper_then_text_pipeline"}
{"input_type": "text", "route": "text_pipeline"}
```
**Implementation:** Lightweight Claude call. Does not extract items. Does not parse
anything. Its only job is classification and routing.
**Note:** If input is audio, Agent 0 triggers Whisper transcription first, then routes
the transcript to the text pipeline. The audio never reaches Agent 1 directly.

---

### Agent 1 — Item Extractor
**When it runs:** After routing, once input has been normalized to either clean text
or a base64 image.
**What it does:** The core LLM call of the entire project. Extracts all line items
with names, prices, and quantities. Also extracts subtotal, tax, tip, and total.
Returns structured JSON.
**Output format:**
```json
{
  "items": [
    {"name": "Organic Bananas", "price": 3.49, "quantity": 1},
    {"name": "Oat Milk 64oz", "price": 5.99, "quantity": 1},
    {"name": "Whole Wheat Bread", "price": 2.49, "quantity": 1}
  ],
  "subtotal": 11.97,
  "tax": 0.87,
  "tip": 0.00,
  "total": 12.84
}
```
**Implementation:**
- For image/PDF: Claude Vision API with a structured output prompt
- For text: Claude text API with a structured output prompt
- Both prompts use few-shot examples of receipts to improve accuracy
- Both prompts use Claude tool use / function calling to enforce JSON schema
**Prompt technique:** Chain-of-thought — "First identify the receipt type, then list
every line item, then identify the subtotal, tax, tip, and total separately."

---

### Agent 2 — Validator
**When it runs:** Immediately after Agent 1 returns its output.
**What it does:** Checks whether the extracted numbers add up correctly.
Specifically: subtotal + tax + tip must equal total (within $0.02 tolerance for
rounding). If the check fails, Agent 2 retries the extraction with a correction
prompt that tells the LLM specifically what was wrong. Maximum 2 retries.
**Self-correction prompt example:**
"Your previous extraction returned subtotal $11.97 + tax $0.87 + tip $0.00 = $12.84,
but the receipt total shows $13.84. Please re-examine the receipt and correct the
discrepancy. A line item price may have been misread."
**Output:** Either a validated JSON object identical in structure to Agent 1's output,
or an error flag if validation still fails after retries (in which case the user is
shown the items with a warning to check prices manually).

---

## Fine-Tuned Classifier

**What it does:** After Agent 2 validates the items, each item name is passed through
a fine-tuned model that maps receipt abbreviations to clean human-readable names and
assigns a food category.

Examples:
- "OAT MLK ORG 64Z" → clean_name: "Oat Milk (Organic, 64oz)", category: "dairy"
- "CHKN BRST BNLS" → clean_name: "Chicken Breast (Boneless)", category: "meat"
- "EVOO 500ML" → clean_name: "Olive Oil (Extra Virgin, 500ml)", category: "pantry"

**Training data:** 500–1000 synthetic examples generated by Claude, mapping
abbreviated receipt text to clean names and categories. Supplemented with real
receipt data collected during development.

**Model:** GPT-3.5-turbo via OpenAI fine-tuning API (primary option) or
Llama 3.1 8B via Together AI (alternative).

**A/B comparison tab:** Streamlit includes a dedicated tab showing base model vs
fine-tuned model side by side — response time, cost per call, and output quality.
This is for portfolio demonstration purposes.

**When it runs:** After Agent 2 validates. Before the review screen is shown to the user.

---

## Step-by-Step User Flow

### Step 1 — User submits bill
User types, records voice, or attaches a file in the chat interface.
Agent 0 routes. Status indicator appears. Whisper runs if audio.
Agents 1 and 2 run. Fine-tuned classifier runs.

### Step 2 — Review screen (editable items table)
The chat shows a message: "Here's what I found on your bill. Edit anything that
looks wrong before we continue."

Below it, an inline editable table shows every extracted item with:
- Item name (editable)
- Price (editable)
- Quantity (editable)
- Clean name from fine-tuned classifier (shown as a suggestion)
- Category badge

The user can:
- Edit any cell directly
- Delete a row
- Add a new row manually
- Change the subtotal, tax, tip, or total values

There is a "Looks good" confirm button. The user cannot proceed until they confirm.
This is the human-in-the-loop checkpoint. No AI runs during this step.

### Step 3 — Enter participant names
After confirming items, the chat prompts: "Who are we splitting this between?
Enter the names of everyone in your group."

User types the names (e.g. "Me, Aarav, Priya, Sam, Jordan"). These are parsed
and stored as participants. The user can add or remove names before proceeding.

### Step 4 — Conversational voice assignment
This is the most technically significant step of the project.

A conversational voice agent activates. It works as a back-and-forth loop:

**The loop:**
1. Agent speaks the item name and price via TTS (ElevenLabs)
   Example: "First item — Organic Bananas, three forty-nine. Who should this be
   split between?"
2. User responds by speaking the names
   Example: "Me and Aarav"
3. Whisper transcribes the user's response
4. Claude parses the intent and maps names to participants
5. The assignment is saved and shown on screen
6. Agent confirms via TTS: "Got it — Bananas split between you and Aarav,
   one seventy-five each. Moving on."
7. Agent moves to the next unassigned item and repeats

**State management:** The agent tracks which items are assigned and which are
pending. It always knows what to ask next. If a name is not recognized (e.g.
user says "Raj" but no participant named Raj exists), the agent asks for
clarification: "I didn't catch that — who did you mean? The participants are
you, Aarav, Priya, Sam, and Jordan."

**Live screen updates:** As each item is assigned, the assignment appears on
screen in real time — the user can see the split updating alongside the voice
conversation.

**Manual override:** At any point the user can stop the voice conversation and
tap-assign items manually. Both modes update the same underlying state.

**Implementation:**
- STT: OpenAI Whisper API (one call per user turn)
- Intent extraction: Claude API with participant names + item list in context
- TTS: ElevenLabs API (one call per agent turn)
- State: Python dict tracking assigned/unassigned items, updated each turn

**Voice agent system prompt context (passed every turn):**
```
You are a friendly bill-splitting assistant.
Current item: {item_name}, ${item_price}
Participants: {participant_list}
Already assigned: {assigned_items_summary}
Remaining items: {remaining_count}
Your job: confirm the assignment for the current item only.
If names are unclear, ask for clarification.
Keep responses short — one or two sentences maximum.
```

### Step 5 — Assignment review screen
Once all items are assigned, the voice agent says: "All done! Here's a summary
of how everything is split. Take a look and confirm when you're ready."

The chat shows an inline summary card listing every item, its price, and exactly
who it's split between with the per-person share for that item.

The user can:
- Go back and re-assign any item (tapping it reopens the assignment)
- Confirm everything is correct

### Step 6 — Final summary screen
After confirmation, the final output appears in the chat as a card showing:

```
Aarav owes you:   $12.40
Priya owes you:   $8.75
Sam owes you:     $15.20
Jordan owes you:  $11.85
```

Below the totals:
- Itemized breakdown toggle (expand to see each person's items)
- Tax and tip allocation shown separately
- Export as PDF button
- Copy WhatsApp message button (formatted text summary)
- Payment links for Venmo / UPI (one per person)

---

## Math Engine

Already built. Kept with the following rules:

**Tax and tip split:** Proportional by default (each person pays tax/tip in
proportion to their item subtotal). Toggle in settings to switch to equal split.

**Quantity handling:** If an item has quantity > 1 and the number of assigned
people equals the quantity, each person gets one unit. If quantities don't match
people count, the total price is split equally among assigned people.

**Rounding:** Always round per-person amounts to 2 decimal places. Absorb any
penny discrepancy ($0.01) into the payer's (bill owner's) total.

**Validation:** sum(person_totals) must equal bill total. If not, adjust payer's
share by the discrepancy before displaying.

**Unassigned items:** The assignment step will not allow proceeding to the final
summary if any item has no people assigned to it. The voice agent will not skip
items — it will always ask about every item.

---

## Streamlit UI Structure

```
app.py                  — Main Streamlit entry point
pages/
  chat.py               — Main chat interface (input bar + message thread)
  ab_comparison.py      — Fine-tuned vs base model comparison tab
components/
  items_table.py        — Editable items review table
  assignment_card.py    — Per-item assignment display
  summary_card.py       — Final totals card
  voice_recorder.py     — Mic input component
agents/
  router.py             — Agent 0: input classification
  extractor.py          — Agent 1: item extraction (vision + text)
  validator.py          — Agent 2: validation and self-correction
  voice_assignment.py   — Conversational voice agent loop
services/
  whisper.py            — OpenAI Whisper STT wrapper
  elevenlabs.py         — ElevenLabs TTS wrapper
  classifier.py         — Fine-tuned model wrapper
  math_engine.py        — Split calculation logic (already built)
  scraper.py            — URL fetch and HTML strip (for URL-in-text-box case)
models/
  db.py                 — SQLAlchemy ORM models
  schemas.py            — Pydantic schemas
database.py             — SQLite connection
.env                    — API keys (never committed)
requirements.txt        — All dependencies
```

---

## API Keys Required

```
ANTHROPIC_API_KEY       — Claude API (Agents 0, 1, 2, voice intent extraction)
OPENAI_API_KEY          — Whisper STT + fine-tuning
ELEVENLABS_API_KEY      — TTS for voice agent responses
```

---

## Build Phases

### Phase 0 — Project setup
- Folder structure as above
- Virtual environment + requirements.txt
- .env with placeholder keys
- SQLite database initialisation
- Confirm all API keys work with a basic ping test

### Phase 1 — Chat UI shell
- Build the Streamlit chat interface with three input controls
- No AI yet — dummy responses to confirm UI works
- Status indicator component
- Message thread rendering

### Phase 2 — Agent 0 (Router)
- Build router.py
- Test all three classification paths with sample inputs
- Wire up Whisper for audio path
- Wire up HTML scraper for URL-in-text case
- Confirm all three paths return unified text or image format

### Phase 3 — Agent 1 (Item Extractor)
- Build extractor.py with separate vision and text prompts
- Implement Claude tool use for structured JSON output
- Test against 20+ real receipt images and text descriptions
- Target: 90%+ item extraction accuracy

### Phase 4 — Agent 2 (Validator)
- Build validator.py with math check and retry logic
- Test with intentionally broken extraction outputs
- Confirm self-correction works within 2 retries

### Phase 5 — Fine-tuned classifier
- Generate synthetic training data using Claude
- Fine-tune model via OpenAI fine-tuning API
- Build classifier.py wrapper
- Build A/B comparison tab in Streamlit

### Phase 6 — Review screen
- Build editable items table component
- Connect to validated + classified item data
- Participant name entry
- Confirm flow before proceeding to assignment

### Phase 7 — Conversational voice agent
- Build voice_assignment.py with full STT → intent → TTS loop
- Implement state machine for item-by-item conversation
- Live screen updates as items are assigned
- Clarification handling for unknown names
- Manual tap-assign override

### Phase 8 — Math engine upgrades
- Proportional vs equal tax/tip toggle
- Quantity handling logic
- Unassigned item guard
- Final rounding validation

### Phase 9 — Output layer
- Final summary card
- PDF export
- WhatsApp copy button
- Venmo / UPI payment links

### Phase 10 — Polish and portfolio
- Detailed README.md explaining every AI component
- Workflow diagram embedded in the Streamlit UI
- Show reasoning toggle (exposes raw prompts and agent outputs)
- 2–3 minute demo video covering all three input modes and voice assignment
- Clean GitHub commit history organised by phase

---

## Key Design Decisions (Reference)

| Decision | Choice | Reason |
|---|---|---|
| Number of agents | 3 (Router, Extractor, Validator) | Lean and purposeful — no redundant agents |
| Voice assignment style | Conversational back-and-forth | Stronger portfolio signal than one-shot |
| URL input | Handled inside text box, no separate button | Keeps UI clean — 3 inputs only |
| Tax/tip split | Proportional by default, toggle for equal | Fairest default, user has control |
| UI framework | Streamlit | Focus stays on backend and AI, not UI |
| Fine-tuning visibility | A/B comparison tab | Concrete, measurable portfolio evidence |
| Agent transparency | Small status indicator only | Clean UX, not overwhelming |
| RAG | Not included | Dedicated RAG project already exists |
| Live camera | Not included in v1 | Deferred to later version |

---

## What This Project Demonstrates (For Portfolio)

- **Multimodal input handling** — text, audio, and image/PDF all entering one unified pipeline
- **Agentic AI architecture** — three agents with distinct, non-overlapping responsibilities
- **LLM prompt engineering** — chain-of-thought, few-shot examples, tool use for structured output, self-correction prompts
- **Fine-tuning** — training data generation, model fine-tuning, A/B benchmarking
- **Conversational voice AI** — full STT + LLM + TTS loop with multi-turn state management
- **Computer vision** — receipt parsing via Claude Vision across varied real-world images
- **Production patterns** — validation, error handling, human-in-the-loop review, math correctness guarantees

---

*Document version 1.0 — reflects all planning decisions as of project start.*
*Update this file if architectural decisions change during build.*
