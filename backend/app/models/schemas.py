from pydantic import BaseModel, ConfigDict
from typing import Optional


# ── Receipt parsing (Phase 1) ──────────────────────────────────────────────

class ReceiptItem(BaseModel):
    name: str
    price: float
    quantity: int = 1


class ParsedReceipt(BaseModel):
    items: list[ReceiptItem]
    subtotal: float
    tax: float = 0.0
    tip: float = 0.0
    total: float
    validation_passed: bool = True
    validation_note: Optional[str] = None


class ParseReceiptResponse(BaseModel):
    success: bool
    receipt: Optional[ParsedReceipt] = None
    error: Optional[str] = None


# ── Expense management (Phase 2) ───────────────────────────────────────────

class CreateExpenseRequest(BaseModel):
    title: Optional[str] = None
    items: list[ReceiptItem]
    subtotal: float
    tax: float = 0.0
    tip: float = 0.0
    total: float
    tax_split: str = "proportional"


class AddParticipantRequest(BaseModel):
    name: str


class AssignItemRequest(BaseModel):
    participant_ids: list[str]


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    price: float
    quantity: int
    assigned_to: list[str] = []  # participant ids currently assigned


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: Optional[str]
    subtotal: float
    tax: float
    tip: float
    total: float
    tax_split: str
    participants: list[ParticipantOut]
    items: list[ItemOut]


class PersonSplit(BaseModel):
    participant_id: str
    name: str
    subtotal: float
    tax: float
    tip: float
    total: float


class SummaryResponse(BaseModel):
    expense_id: str
    splits: list[PersonSplit]
    unassigned_items: list[str]  # item names not yet fully assigned
