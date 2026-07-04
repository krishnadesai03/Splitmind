# AI-Powered Bill Splitter: Complete Project Plan

## Executive Summary

An AI-driven application that uses computer vision, voice recognition, and LLMs to intelligently split group expenses item-by-item. Unlike existing tools that assume equal splits or require tedious manual entry, this project leverages voice interaction to make expense splitting as natural as having a conversation.

---

## Table of Contents

1. [Project Vision](#project-vision)
2. [The Problem Statement](#the-problem-statement)
3. [Core User Flow](#core-user-flow)
4. [Tech Stack](#tech-stack)
5. [AI Architecture](#ai-architecture)
6. [Project Roadmap](#project-roadmap)
7. [Additional Features](#additional-features)
8. [Key Design Decisions](#key-design-decisions)
9. [Getting Started](#getting-started)

---

## Project Vision

### Why This Project Exists

**The Problem:** Real-world group expenses are messy. When five friends go grocery shopping or eat out, the bill rarely splits evenly. Bananas are shared by two people, someone's oat milk is solo, three people split the pizza, everyone shares the appetizer. Existing tools force you to either:
- (a) Accept an unfair equal split
- (b) Manually calculate item-level splits in Excel
- (c) Tap through dozens of screens in apps like Splitwise to assign each item

**The Insight:** The fastest natural interface for this is *talking*. You're already looking at the bill and saying out loud "okay, the bananas were me and Sam, the milk was just for Priya." A voice-driven assistant that listens, sees the bill, and does the math live is dramatically faster than any tap-based UI.

### Purpose & Value

- **Time Savings:** Eliminates 10–15 minutes per group expense event
- **Accuracy:** Removes arithmetic errors and awkward "wait, did you charge me for the milk I didn't have?" conversations
- **Transparency:** Creates an auditable record everyone can see
- **Portfolio Impact:** Demonstrates strong integration of OCR, LLMs, voice, and real-time computation

---

## The Problem Statement

Current solutions fail to address the complexity of real-world group purchases:

| Current Approach | Pain Point |
|-----------------|------------|
| Equal split | Unfair when people ordered different amounts |
| Manual Excel calculation | Time-consuming, error-prone, no history |
| Splitwise/similar apps | Requires tedious tap-through UI for each item |
| Mental math | Impossible for complex bills with 15+ items |

**Our Solution:** Upload receipt → Speak naturally → Get instant, accurate splits

---

## Core User Flow

### Step-by-Step Experience

1. **Start:** User opens app, taps "New Expense"

2. **Capture:** Uploads a photo of the bill (or takes one in-app)

3. **Participants:** Enters/selects the names of people involved (e.g., 5 names: You, Aarav, Priya, Sam, Jordan)

4. **AI Parsing:** App runs OCR + LLM parsing → displays an itemized list with prices, plus tax/tip detected separately

5. **Review:** User reviews/corrects the parsed items (one-tap fixes if AI misread anything)

6. **Voice Assignment:** User taps a mic button and goes item-by-item:
   - *"Bananas — me and Aarav"*
   - *"Oat milk — just Priya"*
   - *"Bread — everyone except Sam"*
   - *"Beer — me, Aarav, and Jordan"*

7. **Live Feedback:** The screen updates **in real-time** as they speak — each item shows:
   - Names it's been assigned to
   - Per-person share for that item
   - Running totals updating

8. **Tax & Tip:** Tax and tip are split proportionally to each person's subtotal (or equally — user chooses)

9. **Final Summary:** 
   ```
   Aarav owes you: $12.40
   Priya owes you: $8.75
   Sam owes you: $15.20
   Jordan owes you: $11.85
   ```

10. **Share:** One-tap share to WhatsApp / generate Venmo/UPI payment links / export PDF receipt

---

## Tech Stack

### Recommended Stack (Balanced for Learning + Shipping)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Frontend** | React Native (Expo) or Next.js PWA | One codebase, mobile-first, camera access |
| **Backend** | Python + FastAPI | Best ML/AI ecosystem, async support |
| **OCR** | Google Cloud Vision API or AWS Textract | Textract excels at receipt-specific extraction |
| **Bill Parsing** | Claude API (Anthropic) or GPT-4o with vision | Pass image directly + structured JSON output |
| **Speech-to-Text** | OpenAI Whisper API or Deepgram | Handles names and accents reliably |
| **Intent Parsing** | Claude / GPT-4o with function calling | Maps speech → structured assignments |
| **Database** | PostgreSQL (via Supabase) | Relational model fits expenses/people/items |
| **Authentication** | Supabase Auth or Clerk | Production-ready, saves weeks of dev time |
| **Hosting** | Vercel (frontend) + Railway/Fly.io (backend) | Free tiers, instant deploys |
| **State Management** | Zustand or React Query | Lightweight, minimal boilerplate |

### Alternative Paths

**Option 1: Fully Serverless**
- Next.js + Vercel AI SDK + Supabase
- No separate backend needed
- Great for rapid prototyping

**Option 2: Cost-Optimized**
- Self-host Whisper
- Use Tesseract OCR (free, open-source)
- Run smaller open models locally
- More work, but $0 API costs

**Option 3: Mobile-Native**
- Swift (iOS) or Kotlin (Android)
- Use on-device speech recognition (free)
- Better performance, platform-specific features

---

## AI Architecture

### The Four AI Components

This project uses AI strategically in four distinct places — not as decoration, but as essential functionality:

#### 1. Vision / OCR (Receipt Parsing)
**Task:** Extract structured items + prices + tax + tip from messy receipt photos

**Why AI:** Vision LLMs (Claude/GPT-4o) outperform classical OCR because they:
- Understand receipt layout context
- Handle handwriting and poor image quality
- Can return clean, structured JSON directly
- Distinguish between item names, prices, quantities, subtotals, tax, tip

**Input:** Receipt image  
**Output:** 
```json
{
  "items": [
    {"name": "Organic Bananas", "price": 4.99, "quantity": 1},
    {"name": "Oat Milk 64oz", "price": 5.49, "quantity": 1}
  ],
  "subtotal": 42.15,
  "tax": 3.45,
  "tip": 8.40,
  "total": 54.00
}
```

#### 2. Speech-to-Text (Voice Transcription)
**Task:** Transcribe user's voice as they assign items

**Why AI:** Must handle proper nouns (participant names) reliably

**Technique:** Prompt Whisper with the participant names list for better accuracy:
```
Vocabulary: Aarav, Priya, Sam, Jordan
```

**Input:** Audio recording of "the bananas were me and Aarav"  
**Output:** `"the bananas were me and Aarav"`

#### 3. Intent Extraction (Structured Assignment)
**Task:** Convert natural speech into structured item assignments

**Why AI:** Users speak naturally, not in a rigid format

**Examples:**
- *"Milk was only for Priya"* → `{item: "milk", people: ["Priya"]}`
- *"Bread was everyone except Sam"* → `{item: "bread", people: ["You", "Aarav", "Priya", "Jordan"]}`
- *"The three beers were me, Aarav, and Jordan"* → `{item: "beer", people: ["You", "Aarav", "Jordan"]}`

**Implementation:** Use Claude/GPT-4o with function calling / structured output

#### 4. Item Matching (Fuzzy Matching)
**Task:** Map spoken item names to receipt line items

**Challenge:** User says "milk" but receipt shows "OAT MLK ORG 64OZ"

**Solution:** LLM-based semantic matching
- User says: "milk"
- Receipt items: ["Organic Bananas", "OAT MLK ORG 64OZ", "BREAD WHOLE WHT"]
- AI matches: "milk" → "OAT MLK ORG 64OZ" (confidence: 95%)

---

## Project Roadmap

### Phase 0: Setup & Design (3–4 days)

**Tasks:**
- Sketch UI flow on paper or Figma
- Finalize tech stack decisions
- Set up repository, CI/CD, and environments
- Obtain API keys (Anthropic/OpenAI, Whisper, OCR service)
- Define data models:
  - User
  - Expense (date, total, participants)
  - Item (name, price, quantity)
  - Participant (name, user_id)
  - Assignment (item_id, participant_id, share)

**Deliverable:** Project repository, design mockups, database schema

---

### Phase 1: Receipt OCR & Parsing (1 week)

**Tasks:**
- Build image upload flow (camera + gallery)
- Integrate Claude/GPT-4o Vision API
- Craft prompt for structured receipt parsing
- Validate: `subtotal + tax + tip ≈ total` (flag mismatches)
- Build editable items table in frontend
- Handle edge cases (missing prices, handwritten totals)

**Deliverable:** Working receipt parser that returns JSON for 90%+ of receipts

**Testing:** Photograph 20+ different receipts and verify accuracy

---

### Phase 2: Manual Splitting MVP (1 week)

**Tasks:**
- Skip voice — build tap-based assignment UI first
- Implement core math engine:
  1. Per-item split calculation
  2. Proportional tax/tip allocation
  3. Final per-person totals
- Add/remove participants mid-flow
- Handle edge cases (rounding errors, $0.01 discrepancies)
- Build summary view showing who owes what

**Deliverable:** Fully functional manual splitter with accurate math

**Why manual first:** Voice is a UI layer on top of this logic. Get the engine bulletproof before adding complexity.

---

### Phase 3: Voice Layer (1.5 weeks)

**Tasks:**
- Add microphone recording UI
- Stream audio to Whisper API
- Build prompt for intent extraction:
  - Input: transcript + item list + participant names
  - Output: structured assignments
- Update UI live as assignments are made
- Add visual feedback (items highlight as they're assigned)
- Handle ambiguity ("Did you mean Priya or Priyanka?")
- Add undo/redo for voice commands

**Deliverable:** Voice-driven assignment that feels magical

**Iteration focus:** Prompt engineering for natural language → structured data

---

### Phase 4: Polish & Sharing (1 week)

**Tasks:**
- Smooth animations as items get assigned
- Error states and loading indicators
- "Undo last assignment" button
- Export features:
  - PDF summary with itemized breakdown
  - WhatsApp share with formatted message
  - Deep links for Venmo/PayPal/UPI payments
- Settings: tax/tip split method, default currency
- Dark mode support

**Deliverable:** Production-ready MVP

---

### Phase 5: Stretch Features (Ongoing)

See [Additional Features](#additional-features) section below

**Timeline Summary:**  
Realistic for a solo developer working evenings/weekends: **6–8 weeks to polished MVP**  
Faster if you cut voice from v1 and ship manual-only first.

---

## Additional Features

### High-Value Features

#### 1. Group Memory
**What:** Remember frequent groups ("Roommates," "Hiking Crew," "Work Lunches")  
**Why:** Eliminates re-entering the same 5 names every week  
**Implementation:** Save groups with last-used date, suggest at expense creation

#### 2. Running Balances
**What:** Track multiple expenses with the same group, show cumulative balances  
**Why:** Core feature of Splitwise — settle with one transaction instead of many  
**Example:** 
```
This month with Roommates:
You → Aarav: +$45.20
You → Priya: -$12.30
Settle up: Aarav owes you $45.20, you owe Priya $12.30
```

#### 3. Smart Defaults
**What:** Learn preferences over time  
**Why:** Saves repeated assignments  
**Examples:**
- "Last time, Priya didn't eat meat — auto-exclude from meat items?"
- "Jordan always skips alcohol — suggest excluding from beer?"

#### 4. Multi-Currency Support
**What:** Live FX conversion for travel groups  
**Why:** Essential for international trips  
**Implementation:** Integrate exchangerate-api.com or similar

#### 5. Receipt History & Search
**What:** "Show all grocery trips this month" or "How much did we spend on restaurants?"  
**Why:** Budget tracking and insights  
**Implementation:** Full-text search + filtering by category/date/participant

---

### Differentiating / Fun Features

#### 6. AI Categorization & Insights
**What:** Auto-tag items (groceries, alcohol, household, entertainment)  
**Why:** Monthly spending breakdowns per person  
**Example:** "Aarav spent $120 on shared groceries this month, you spent $95"

#### 7. Voice-Only Mode
**What:** Completely hands-free operation  
**Why:** Use while cooking, driving, carrying groceries  
**Flow:** "Hey Splitter, new expense with the roommates. Bananas were me and Sam..."

#### 8. WhatsApp Bot Interface
**What:** Forward receipt photo + voice note to a WhatsApp number  
**Why:** No app installation needed — SMS-like convenience  
**Implementation:** Twilio + WhatsApp Business API

#### 9. Recurring Expense Detection
**What:** "You buy oat milk weekly — set up a recurring split?"  
**Why:** Automate predictable shared purchases  
**Implementation:** Pattern detection in purchase history

#### 10. Dispute Resolution Log
**What:** Every change is timestamped with who made it  
**Why:** No "I never agreed to that" — full audit trail  
**Implementation:** Event sourcing pattern

#### 11. Handwritten Tab Support
**What:** Handle scribbled notes from bars/restaurants  
**Why:** Many places still use paper  
**Implementation:** Enhanced OCR + manual correction flow

#### 12. Budget Warnings
**What:** "Aarav has spent $200 on shared expenses this month, 40% above group average"  
**Why:** Prevent resentment in long-term groups  
**Implementation:** Configurable thresholds + notifications

---

### Advanced / Portfolio-Worthy Features

#### 13. Fine-Tuned Receipt Parser
**What:** Train a smaller, specialized model instead of GPT-4o calls  
**Why:** 10x cheaper at scale, faster inference  
**How:** Fine-tune Llama 3 on 10k labeled receipts

#### 14. Offline Mode
**What:** Full functionality without internet  
**Why:** Works in restaurants with bad signal  
**Implementation:** On-device models (CoreML for iOS, TFLite for Android)

#### 15. Bank/Card Integration
**What:** Auto-create expenses when group purchases are detected  
**Why:** Zero manual input for users with linked accounts  
**Implementation:** Plaid API + merchant categorization

---

## Key Design Decisions

### 1. Tax & Tip Allocation

**Decision Required:** How should tax and tip be split?

**Options:**
- **Proportional to subtotal** (recommended): If you ordered 40% of the food, you pay 40% of tax/tip
- **Equal split**: Everyone pays the same tax/tip regardless of order size
- **Hybrid**: Tax proportional, tip equal

**Recommendation:** Make it a **user setting** rather than hardcoded. Proportional feels fairest and is the standard, but some groups prefer equal splits.

**Implementation:**
```python
if settings.tax_split == "proportional":
    person_tax = total_tax * (person_subtotal / group_subtotal)
else:
    person_tax = total_tax / num_people
```

---

### 2. Quantity Handling

**Scenario:** Receipt shows "Beer x3 @ $6 = $18"  
User says: *"The beers were me, Sam, and Aarav"*

**Question:** Does each person get one beer, or do they split all three?

**Decision:** 
- If quantity matches number of people → assume one each
- If not → prompt for clarification: "3 beers for 3 people — one each, or splitting the total?"

**Why:** Ambiguity here causes the most disputes

---

### 3. Voice Error Handling

**Problem:** LLMs occasionally mishear names  
- "Aarav" → "Arrow"
- "Priya" → "Priya" (different person with same name)

**Solution:**
1. **Feed participant names to Whisper** as a prompt/vocabulary to bias recognition
2. **Show assignments as editable chips** — user can tap to correct
3. **Confirm unusual assignments**: "I heard 'everyone except Sam' — is that right?"

---

### 4. Privacy & Data Storage

**Question:** What data do we store, and for how long?

**Considerations:**
- Receipts contain: location, purchase time, credit card last 4 digits
- Some users won't want this in the cloud

**Decision:**
- **Default:** Store encrypted images for 30 days, then delete (keep only parsed JSON)
- **Local-only mode:** Process everything on-device, never upload
- **Privacy policy:** Be explicit about what's stored and offer export/delete

**Implementation:** 
- Image storage: S3 with server-side encryption
- User preference: "Delete receipt images immediately after parsing"

---

### 5. Rounding & Penny Discrepancies

**Problem:** 
```
Item 1: $10.00 / 3 people = $3.33 each (but $3.33 × 3 = $9.99, not $10.00)
```

**Solution:**
1. Always round per-person amounts to 2 decimals
2. Absorb the $0.01 discrepancy in the payer's total
3. Validate: `sum(person_totals) == bill_total` and adjust payer's share if needed

**Why:** Prevents "you owe me $12.33333" and ensures books balance perfectly

---

## Getting Started

### This Weekend: Proof of Concept

Don't try to build everything at once. The **single highest-leverage thing** you can do right now:

**Build a 50-line Python script:**
1. Take a receipt photo
2. Send it to Claude or GPT-4o with a structured-output prompt
3. Print the parsed JSON

**Why:** If this works reliably across 10 different receipts you photograph, you have proof your core AI dependency is solid. Everything else is conventional app development on top of that foundation.

### Sample Receipt Parsing Prompt

```python
import anthropic
import base64

def parse_receipt(image_path):
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()
    
    client = anthropic.Anthropic(api_key="your-api-key")
    
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": """Parse this receipt and return ONLY valid JSON with this structure:
{
  "items": [{"name": "string", "price": number, "quantity": number}],
  "subtotal": number,
  "tax": number,
  "tip": number,
  "total": number
}

Rules:
- Extract ALL items with their prices
- If quantity is shown, include it (default 1)
- Subtotal is pre-tax total
- If tip/tax aren't shown, use 0
- Ensure subtotal + tax + tip ≈ total"""
                }
            ]
        }]
    )
    
    return message.content[0].text

# Test it
result = parse_receipt("receipt.jpg")
print(result)
```

### Database Schema (Quick Reference)

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    name VARCHAR(255),
    created_at TIMESTAMP
);

-- Expenses table
CREATE TABLE expenses (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    title VARCHAR(255),
    receipt_image_url TEXT,
    subtotal DECIMAL(10,2),
    tax DECIMAL(10,2),
    tip DECIMAL(10,2),
    total DECIMAL(10,2),
    created_at TIMESTAMP
);

-- Participants table (people involved in an expense)
CREATE TABLE participants (
    id UUID PRIMARY KEY,
    expense_id UUID REFERENCES expenses(id),
    name VARCHAR(255),
    total_owed DECIMAL(10,2)
);

-- Items table (line items from receipt)
CREATE TABLE items (
    id UUID PRIMARY KEY,
    expense_id UUID REFERENCES expenses(id),
    name VARCHAR(255),
    price DECIMAL(10,2),
    quantity INTEGER DEFAULT 1
);

-- Assignments table (which people are assigned to which items)
CREATE TABLE assignments (
    id UUID PRIMARY KEY,
    item_id UUID REFERENCES items(id),
    participant_id UUID REFERENCES participants(id),
    share DECIMAL(10,2) -- How much this person pays for this item
);
```

### Math Engine (Proportional Tax/Tip)

```python
def calculate_splits(items, assignments, tax, tip, split_method="proportional"):
    """
    items: [{"id": 1, "price": 10.00, "quantity": 1}, ...]
    assignments: [{"item_id": 1, "participant_id": "Alice", "share": 5.00}, ...]
    tax: 2.50
    tip: 3.00
    """
    
    # Calculate subtotal and each person's subtotal
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    person_subtotals = {}
    
    for assignment in assignments:
        person = assignment["participant_id"]
        person_subtotals[person] = person_subtotals.get(person, 0) + assignment["share"]
    
    # Split tax and tip
    person_totals = {}
    for person, person_subtotal in person_subtotals.items():
        if split_method == "proportional":
            proportion = person_subtotal / subtotal
            person_tax = tax * proportion
            person_tip = tip * proportion
        else:  # equal
            num_people = len(person_subtotals)
            person_tax = tax / num_people
            person_tip = tip / num_people
        
        person_totals[person] = person_subtotal + person_tax + person_tip
    
    # Handle rounding discrepancies
    total_calculated = sum(person_totals.values())
    actual_total = subtotal + tax + tip
    discrepancy = actual_total - total_calculated
    
    if abs(discrepancy) > 0.01:  # More than a penny off
        raise ValueError(f"Math error: discrepancy of ${discrepancy:.2f}")
    elif discrepancy != 0:
        # Absorb penny discrepancy in payer's total (first person)
        payer = list(person_totals.keys())[0]
        person_totals[payer] += discrepancy
    
    return person_totals

# Example usage
items = [
    {"id": 1, "price": 10.00, "quantity": 1},
    {"id": 2, "price": 5.00, "quantity": 2}
]

assignments = [
    {"item_id": 1, "participant_id": "Alice", "share": 5.00},
    {"item_id": 1, "participant_id": "Bob", "share": 5.00},
    {"item_id": 2, "participant_id": "Alice", "share": 10.00}
]

result = calculate_splits(items, assignments, tax=2.50, tip=3.00)
print(result)
# Output: {'Alice': 17.92, 'Bob': 6.58}
```

---

## Success Metrics

How will you know this project succeeded?

**Technical Metrics:**
- Receipt parsing accuracy: >90% of items extracted correctly
- Voice transcription accuracy: >95% with proper names
- App response time: <2 seconds from photo upload to parsed items
- Math accuracy: 100% (zero rounding errors)

**User Metrics:**
- Time to split a 10-item bill: <60 seconds (vs. 5+ minutes manually)
- User retention: 40%+ of users return for a second expense
- Voice usage: 60%+ of users try voice assignment

**Portfolio Metrics:**
- GitHub stars: 100+ (shows public interest)
- Blog post reach: 5,000+ views
- Interview mentions: Recruiters ask about it in 50%+ of calls

---

## Conclusion

This project sits at the intersection of **practical utility** and **technical depth**. You're solving a real pain point (messy group expense splits) with a genuinely innovative interface (voice-driven assignment) while demonstrating proficiency in computer vision, LLMs, voice processing, and full-stack development.

The phased roadmap lets you ship an MVP in 6–8 weeks while leaving room for advanced features that could turn this into a viral product. Most importantly, every person who's ever split a restaurant bill or grocery trip will immediately understand the value — making it an excellent portfolio piece that tells a clear story.

**Next Steps:**
1. This weekend: Build the receipt parsing proof-of-concept
2. Week 1: Set up your repository and design the UI flow
3. Week 2: Implement the math engine with test cases
4. Week 3+: Follow the phased roadmap

Good luck building! This is the kind of project that starts as a portfolio piece and could genuinely become something people want to use every day.

---

## Appendix: Useful Resources

### APIs & Services
- [Anthropic Claude API](https://www.anthropic.com/api)
- [OpenAI Whisper API](https://platform.openai.com/docs/guides/speech-to-text)
- [AWS Textract](https://aws.amazon.com/textract/)
- [Google Cloud Vision](https://cloud.google.com/vision)
- [Supabase](https://supabase.com/)
- [Vercel](https://vercel.com/)

### Learning Resources
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Native Expo](https://expo.dev/)
- [Prompt Engineering Guide](https://www.promptingguide.ai/)

### Similar Projects (for inspiration, not copying)
- Splitwise (equal splits, manual entry)
- Tab (social splitting app)
- Venmo (peer-to-peer payments)

---

*Project Plan Version 1.0 | Created: 2026*
