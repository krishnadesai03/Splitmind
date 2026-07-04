from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import db as models
from ..models.schemas import (
    CreateExpenseRequest, AddParticipantRequest, AssignItemRequest,
    ExpenseOut, ItemOut, ParticipantOut, SummaryResponse,
)
from ..services.math_engine import calculate_splits

router = APIRouter(prefix="/expenses", tags=["expenses"])


def _item_out(item: models.Item) -> ItemOut:
    return ItemOut(
        id=item.id,
        name=item.name,
        price=item.price,
        quantity=item.quantity,
        assigned_to=[a.participant_id for a in item.assignments],
    )


def _expense_out(expense: models.Expense) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        title=expense.title,
        subtotal=expense.subtotal,
        tax=expense.tax,
        tip=expense.tip,
        total=expense.total,
        tax_split=expense.tax_split,
        participants=[ParticipantOut(id=p.id, name=p.name) for p in expense.participants],
        items=[_item_out(i) for i in expense.items],
    )


# ── Create expense from parsed receipt ────────────────────────────────────

@router.post("", response_model=ExpenseOut)
def create_expense(body: CreateExpenseRequest, db: Session = Depends(get_db)):
    expense = models.Expense(
        title=body.title,
        subtotal=body.subtotal,
        tax=body.tax,
        tip=body.tip,
        total=body.total,
        tax_split=body.tax_split,
    )
    db.add(expense)
    db.flush()

    for item_data in body.items:
        db.add(models.Item(
            expense_id=expense.id,
            name=item_data.name,
            price=item_data.price,
            quantity=item_data.quantity,
        ))

    db.commit()
    db.refresh(expense)
    return _expense_out(expense)


# ── Get expense ────────────────────────────────────────────────────────────

@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: str, db: Session = Depends(get_db)):
    expense = db.get(models.Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _expense_out(expense)


# ── Participants ───────────────────────────────────────────────────────────

@router.post("/{expense_id}/participants", response_model=ParticipantOut)
def add_participant(expense_id: str, body: AddParticipantRequest, db: Session = Depends(get_db)):
    expense = db.get(models.Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    participant = models.Participant(expense_id=expense_id, name=body.name.strip())
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return ParticipantOut(id=participant.id, name=participant.name)


@router.delete("/{expense_id}/participants/{participant_id}", status_code=204)
def remove_participant(expense_id: str, participant_id: str, db: Session = Depends(get_db)):
    participant = db.get(models.Participant, participant_id)
    if not participant or participant.expense_id != expense_id:
        raise HTTPException(status_code=404, detail="Participant not found")
    db.delete(participant)
    db.commit()


# ── Item assignment ────────────────────────────────────────────────────────

@router.put("/{expense_id}/items/{item_id}/assign", response_model=ItemOut)
def assign_item(
    expense_id: str,
    item_id: str,
    body: AssignItemRequest,
    db: Session = Depends(get_db),
):
    item = db.get(models.Item, item_id)
    if not item or item.expense_id != expense_id:
        raise HTTPException(status_code=404, detail="Item not found")

    # Validate all participant ids belong to this expense
    expense = db.get(models.Expense, expense_id)
    valid_ids = {p.id for p in expense.participants}
    for pid in body.participant_ids:
        if pid not in valid_ids:
            raise HTTPException(status_code=400, detail=f"Participant {pid} not in this expense")

    # Replace all assignments for this item
    for a in item.assignments:
        db.delete(a)
    db.flush()

    share_each = round(item.price / len(body.participant_ids), 4) if body.participant_ids else 0
    for pid in body.participant_ids:
        db.add(models.Assignment(item_id=item_id, participant_id=pid, share=share_each))

    db.commit()
    db.refresh(item)
    return _item_out(item)


# ── Summary ────────────────────────────────────────────────────────────────

@router.get("/{expense_id}/summary", response_model=SummaryResponse)
def get_summary(expense_id: str, db: Session = Depends(get_db)):
    expense = db.get(models.Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    splits, unassigned = calculate_splits(expense, expense.participants, expense.items)
    return SummaryResponse(
        expense_id=expense_id,
        splits=splits,
        unassigned_items=unassigned,
    )
