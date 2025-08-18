# admin/models.py
from __future__ import annotations
from typing import Optional
from uuid import uuid4
from sqlalchemy import String, BigInteger, Integer, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    payments: Mapped[list["Payment"]] = relationship(back_populates="merchant")

class Payment(Base):
    __tablename__ = "payments"
    payment_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    merchant_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("merchants.id"), index=True, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    merchant: Mapped[Optional[Merchant]] = relationship(back_populates="payments")
    # one-to-one: в webhook_outbox PK = payment_id, значит запись максимум одна
    outbox: Mapped[Optional["WebhookOutbox"]] = relationship(back_populates="payment", uselist=False)

class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"
    payment_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("payments.payment_id"), primary_key=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment: Mapped[Optional[Payment]] = relationship(back_populates="outbox")
