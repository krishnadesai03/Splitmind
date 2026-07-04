import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from ..database import Base


def _uuid():
    return str(uuid.uuid4())


class Expense(Base):
    __tablename__ = "expenses"

    id         = Column(String, primary_key=True, default=_uuid)
    title      = Column(String, nullable=True)
    subtotal   = Column(Float, default=0.0)
    tax        = Column(Float, default=0.0)
    tip        = Column(Float, default=0.0)
    total      = Column(Float, default=0.0)
    tax_split  = Column(String, default="proportional")  # "proportional" | "equal"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    participants = relationship("Participant", back_populates="expense", cascade="all, delete-orphan")
    items        = relationship("Item",        back_populates="expense", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"

    id         = Column(String, primary_key=True, default=_uuid)
    expense_id = Column(String, ForeignKey("expenses.id"), nullable=False)
    name       = Column(String, nullable=False)

    expense     = relationship("Expense",     back_populates="participants")
    assignments = relationship("Assignment",  back_populates="participant", cascade="all, delete-orphan")


class Item(Base):
    __tablename__ = "items"

    id         = Column(String, primary_key=True, default=_uuid)
    expense_id = Column(String, ForeignKey("expenses.id"), nullable=False)
    name       = Column(String, nullable=False)
    price      = Column(Float, nullable=False)
    quantity   = Column(Integer, default=1)

    expense     = relationship("Expense",    back_populates="items")
    assignments = relationship("Assignment", back_populates="item", cascade="all, delete-orphan")


class Assignment(Base):
    __tablename__ = "assignments"

    id             = Column(String, primary_key=True, default=_uuid)
    item_id        = Column(String, ForeignKey("items.id"),        nullable=False)
    participant_id = Column(String, ForeignKey("participants.id"), nullable=False)
    share          = Column(Float, nullable=False)

    item        = relationship("Item",        back_populates="assignments")
    participant = relationship("Participant", back_populates="assignments")
