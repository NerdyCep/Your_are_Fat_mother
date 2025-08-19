# api/admin_api.py
import os, time
from typing import Optional, List, Literal, Dict, Any, Mapping
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Result

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin")
DB_DSN = os.getenv("DB_DSN", "postgresql+psycopg2://postgres:postgres@postgres:5432/payments")
engine: Engine = create_engine(DB_DSN, pool_pre_ping=True)

router = APIRouter(prefix="/admin-api", tags=["admin"])

def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid token")

# Универсальный конвертер и для Row, и для mappings()-результатов
def row_to_dict(row: Any) -> dict:
    if isinstance(row, Mapping):
        return dict(row)
    # SQLAlchemy Row: row._mapping
    m = getattr(row, "_mapping", None)
    return dict(m) if m is not None else dict(row)

PaymentStatus = Literal["new", "processing", "approved", "declined", "failed"]
RefundStatus  = Literal["requested", "succeeded", "failed"]

class MerchantOut(BaseModel):
    id: UUID
    webhook_url: str
    api_secret: str
    api_key: Optional[str] = None

class MerchantCreate(BaseModel):
    webhook_url: str = Field(..., min_length=4)
    api_secret: str = Field(..., min_length=1)
    api_key: Optional[str] = None

class MerchantUpdate(BaseModel):
    webhook_url: Optional[str] = Field(None, min_length=4)
    api_secret: Optional[str] = Field(None, min_length=1)
    api_key: Optional[str] = Field(None, min_length=1)

class PaymentOut(BaseModel):
    payment_id: UUID
    merchant_id: Optional[UUID] = None
    amount: int
    currency: str
    status: PaymentStatus
    idempotency_key: Optional[str] = None
    created_at: int
    merchant_webhook_url: Optional[str] = None

class PaymentUpdate(BaseModel):
    status: PaymentStatus

class PaymentsList(BaseModel):
    items: List[PaymentOut]
    total: int
    limit: int
    offset: int

class StatsOut(BaseModel):
    counts_by_status: Dict[str, int]
    merchants_total: int
    payments_total: int

class RefundOut(BaseModel):
    refund_id: UUID
    payment_id: UUID
    amount: int
    currency: str
    status: RefundStatus
    reason: Optional[str] = None
    created_at: int

class RefundsList(BaseModel):
    items: List[RefundOut]
    total: int
    limit: int
    offset: int

class RefundCreate(BaseModel):
    amount: int = Field(..., gt=0)
    reason: Optional[str] = Field(None, max_length=200)
    result: Optional[RefundStatus] = Field(None)

class RefundSimulate(BaseModel):
    amount: int = Field(..., gt=0)
    reason: Optional[str] = Field(None, max_length=200)
    success: bool = True

# -------- Merchants --------
@router.get("/merchants", response_model=List[MerchantOut])
def list_merchants(_: None = Depends(require_admin)):
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, webhook_url, api_secret, api_key
              FROM merchants
             ORDER BY webhook_url
        """)).mappings().all()
        return [row_to_dict(r) for r in rows]

@router.post("/merchants", response_model=MerchantOut, status_code=201)
def create_merchant(body: MerchantCreate, _: None = Depends(require_admin)):
    new_id = str(uuid4())
    api_key = body.api_key or f"sk_live_{uuid4().hex}"
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO merchants (id, webhook_url, api_secret, api_key)
            VALUES (CAST(:id AS uuid), :webhook_url, :api_secret, :api_key)
         RETURNING id, webhook_url, api_secret, api_key
        """), dict(id=new_id, webhook_url=body.webhook_url, api_secret=body.api_secret, api_key=api_key)).mappings().first()
        return row_to_dict(row)

@router.patch("/merchants/{merchant_id}", response_model=MerchantOut)
def update_merchant(merchant_id: UUID, body: MerchantUpdate, _: None = Depends(require_admin)):
    sets = []
    params: Dict[str, Any] = {"id": str(merchant_id)}
    if body.webhook_url is not None:
        sets.append("webhook_url = :webhook_url"); params["webhook_url"] = body.webhook_url
    if body.api_secret is not None:
        sets.append("api_secret = :api_secret"); params["api_secret"] = body.api_secret
    if body.api_key is not None:
        sets.append("api_key = :api_key"); params["api_key"] = body.api_key
    if not sets:
        raise HTTPException(400, "Nothing to update")

    with engine.begin() as conn:
        row = conn.execute(text(f"""
            UPDATE merchants SET {", ".join(sets)}
             WHERE id = CAST(:id AS uuid)
         RETURNING id, webhook_url, api_secret, api_key
        """), params).mappings().first()
        if not row:
            raise HTTPException(404, "Merchant not found")
        return row_to_dict(row)

@router.delete("/merchants/{merchant_id}", status_code=204)
def delete_merchant(merchant_id: UUID, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        has_payments = conn.execute(text("""
            SELECT 1 FROM payments WHERE merchant_id = CAST(:id AS uuid) LIMIT 1
        """), {"id": str(merchant_id)}).first()
        if has_payments:
            raise HTTPException(409, "Cannot delete merchant with existing payments")
        res = conn.execute(text("DELETE FROM merchants WHERE id = CAST(:id AS uuid)"), {"id": str(merchant_id)})
        if res.rowcount == 0:
            raise HTTPException(404, "Merchant not found")
    return

# -------- Payments --------
@router.get("/payments", response_model=PaymentsList)
def list_payments(
    _: None = Depends(require_admin),
    merchant_id: Optional[UUID] = Query(None),
    status: Optional[PaymentStatus] = Query(None),
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    amount_min: Optional[int] = Query(None, ge=1),
    amount_max: Optional[int] = Query(None, ge=1),
    created_from: Optional[int] = Query(None),
    created_to: Optional[int] = Query(None, description="inclusive"),
    q: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: Literal['created_at','amount'] = Query('created_at'),
    order: Literal['desc','asc'] = Query('desc'),
):
    where = ["1=1"]; params: Dict[str, Any] = {}
    if merchant_id: where.append("p.merchant_id = CAST(:merchant_id AS uuid)"); params["merchant_id"] = str(merchant_id)
    if status: where.append("p.status = :status"); params["status"] = status
    if currency: where.append("p.currency = :currency"); params["currency"] = currency.upper()
    if amount_min is not None: where.append("p.amount >= :amount_min"); params["amount_min"] = amount_min
    if amount_max is not None: where.append("p.amount <= :amount_max"); params["amount_max"] = amount_max
    if created_from is not None: where.append("p.created_at >= :created_from"); params["created_from"] = created_from
    if created_to is not None: where.append("p.created_at < :created_to_excl"); params["created_to_excl"] = created_to + 1
    if q:
        where.append("(CAST(p.payment_id AS TEXT) ILIKE :q OR p.idempotency_key ILIKE :q OR p.currency ILIKE :q)")
        params["q"] = f"%{q}%"

    where_sql = " AND ".join(where)
    sort_col = "p.created_at" if sort == "created_at" else "p.amount"
    direction = "DESC" if order == "desc" else "ASC"

    with engine.begin() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM payments p WHERE {where_sql}"), params).scalar_one()
        rows = conn.execute(text(f"""
            SELECT p.payment_id, p.merchant_id, p.amount, p.currency, p.status,
                   p.idempotency_key, p.created_at,
                   m.webhook_url AS merchant_webhook_url
              FROM payments p
              LEFT JOIN merchants m ON m.id = p.merchant_id
             WHERE {where_sql}
             ORDER BY {sort_col} {direction}, p.payment_id
             LIMIT :limit OFFSET :offset
        """), {**params, "limit": limit, "offset": offset}).mappings().all()

    items = [PaymentOut(**row_to_dict(r)) for r in rows]
    return PaymentsList(items=items, total=total, limit=limit, offset=offset)

@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: UUID, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT p.payment_id, p.merchant_id, p.amount, p.currency, p.status,
                   p.idempotency_key, p.created_at,
                   m.webhook_url AS merchant_webhook_url
              FROM payments p
              LEFT JOIN merchants m ON m.id = p.merchant_id
             WHERE p.payment_id = CAST(:pid AS uuid)
        """), {"pid": str(payment_id)}).mappings().first()
        if not row:
            raise HTTPException(404, "Payment not found")
        return PaymentOut(**row_to_dict(row))

@router.patch("/payments/{payment_id}", response_model=PaymentOut)
def update_payment_status(payment_id: UUID, body: PaymentUpdate, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE payments
               SET status = :status
             WHERE payment_id = CAST(:pid AS uuid)
         RETURNING payment_id, merchant_id, amount, currency, status,
                   idempotency_key, created_at,
                   (SELECT webhook_url FROM merchants m WHERE m.id = payments.merchant_id) AS merchant_webhook_url
        """), {"pid": str(payment_id), "status": body.status}).mappings().first()
        if not row:
            raise HTTPException(404, "Payment not found")
        return row_to_dict(row)

@router.post("/payments/{payment_id}/resend-webhook", status_code=202)
def resend_webhook(payment_id: UUID, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM payments WHERE payment_id = CAST(:pid AS uuid)"),
                              {"pid": str(payment_id)}).first()
        if not exists:
            raise HTTPException(404, "Payment not found")
        conn.execute(text("""
            INSERT INTO webhook_outbox (payment_id, delivered)
                 VALUES (CAST(:pid AS uuid), FALSE)
            ON CONFLICT (payment_id) DO UPDATE SET delivered = FALSE
        """), {"pid": str(payment_id)})
    return {"status": "queued"}

# -------- Refunds --------
def _get_payment_and_refunded_sum(conn, pid: str):
    p = conn.execute(text("""
        SELECT payment_id, amount, currency, status
          FROM payments
         WHERE payment_id = CAST(:pid AS uuid)
    """), {"pid": pid}).mappings().first()
    if not p:
        raise HTTPException(404, "Payment not found")
    refunded_sum = conn.execute(text("""
        SELECT COALESCE(SUM(amount),0) AS s
          FROM refunds
         WHERE payment_id = CAST(:pid AS uuid) AND status = 'succeeded'
    """), {"pid": pid}).scalar_one()
    return p, int(refunded_sum or 0)

@router.get("/refunds", response_model=RefundsList)
def list_refunds(
    _: None = Depends(require_admin),
    payment_id: Optional[UUID] = Query(None),
    status: Optional[RefundStatus] = Query(None),
    created_from: Optional[int] = Query(None),
    created_to: Optional[int] = Query(None, description="inclusive"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    order: Literal["asc","desc"] = Query("desc")
):
    where = ["1=1"]; params: Dict[str, Any] = {}
    if payment_id: where.append("r.payment_id = CAST(:pid AS uuid)"); params["pid"] = str(payment_id)
    if status: where.append("r.status = :status"); params["status"] = status
    if created_from is not None: where.append("r.created_at >= :from"); params["from"] = created_from
    if created_to is not None: where.append("r.created_at < :to_excl"); params["to_excl"] = created_to + 1
    where_sql = " AND ".join(where)
    direction = "ASC" if order == "asc" else "DESC"

    with engine.begin() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM refunds r WHERE {where_sql}"), params).scalar_one()
        rows = conn.execute(text(f"""
            SELECT refund_id, payment_id, amount, currency, status, reason, created_at
              FROM refunds r
             WHERE {where_sql}
             ORDER BY created_at {direction}, refund_id
             LIMIT :limit OFFSET :offset
        """), {**params, "limit": limit, "offset": offset}).mappings().all()
    return RefundsList(items=[RefundOut(**row_to_dict(r)) for r in rows], total=total, limit=limit, offset=offset)

@router.get("/payments/{payment_id}/refunds", response_model=RefundsList)
def list_payment_refunds(payment_id: UUID, _: None = Depends(require_admin), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), order: Literal["asc","desc"] = Query("desc")):
    return list_refunds(_, payment_id, None, None, None, limit, offset, order)

@router.post("/payments/{payment_id}/refunds", response_model=RefundOut, status_code=201)
def create_refund(payment_id: UUID, body: RefundCreate, _: None = Depends(require_admin)):
    now = int(time.time())
    with engine.begin() as conn:
        p, refunded = _get_payment_and_refunded_sum(conn, str(payment_id))
        if p["status"] != "approved":
            raise HTTPException(409, "Refunds allowed only for approved (completed) payments")
        remaining = int(p["amount"]) - refunded
        if body.amount > remaining:
            raise HTTPException(409, f"Refund amount exceeds remaining ({remaining})")
        status: RefundStatus = body.result or "succeeded"
        rid = str(uuid4())
        row = conn.execute(text("""
            INSERT INTO refunds (refund_id, payment_id, amount, currency, status, reason, created_at)
            VALUES (CAST(:rid AS uuid), CAST(:pid AS uuid), :amount, :currency, :status, :reason, :created)
         RETURNING refund_id, payment_id, amount, currency, status, reason, created_at
        """), {
            "rid": rid,
            "pid": str(payment_id),
            "amount": body.amount,
            "currency": p["currency"],
            "status": status,
            "reason": body.reason,
            "created": now
        }).mappings().first()
        return RefundOut(**row_to_dict(row))

@router.post("/payments/{payment_id}/simulate-refund", response_model=RefundOut, status_code=201)
def simulate_refund(payment_id: UUID, body: RefundSimulate, _: None = Depends(require_admin)):
    result: RefundStatus = "succeeded" if body.success else "failed"
    return create_refund(payment_id, RefundCreate(amount=body.amount, reason=body.reason, result=result), _)

@router.get("/stats", response_model=StatsOut)
def get_stats(_: None = Depends(require_admin)):
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT status, COUNT(*) AS cnt FROM payments GROUP BY status")).mappings().all()
        counts = {str(r["status"]): int(r["cnt"]) for r in rows}
        merchants_total = int(conn.execute(text("SELECT COUNT(*) FROM merchants")).scalar_one())
        payments_total = int(conn.execute(text("SELECT COUNT(*) FROM payments")).scalar_one())
    return StatsOut(counts_by_status=counts, merchants_total=merchants_total, payments_total=payments_total)
