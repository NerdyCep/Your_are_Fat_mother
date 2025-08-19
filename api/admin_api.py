import os
from typing import Optional, List, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Result
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "dev-admin")

def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    if token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid token")

DB_DSN = os.getenv("DB_DSN", "postgresql+psycopg2://postgres:postgres@postgres:5432/payments")
engine: Engine = create_engine(DB_DSN, pool_pre_ping=True)

router = APIRouter(prefix="/admin-api", tags=["admin-api"])

class MerchantOut(BaseModel):
    id: UUID
    webhook_url: str
    api_secret: str
    api_key: Optional[str] = None

class MerchantCreate(BaseModel):
    webhook_url: str = Field(..., min_length=4)
    api_secret: str = Field(..., min_length=1)
    api_key: Optional[str] = None  # можно задать руками

class MerchantUpdate(BaseModel):
    webhook_url: Optional[str] = Field(None, min_length=4)
    api_secret: Optional[str] = Field(None, min_length=1)
    api_key: Optional[str] = Field(None, min_length=1)

PaymentStatus = Literal["new","processing","approved","declined","failed"]

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

def row_to_dict(row) -> dict:
    return dict(row._mapping)

# ---------- MERCHANTS ----------
@router.get("/merchants", response_model=List[MerchantOut])
def list_merchants(_: None = Depends(require_admin)):
    with engine.begin() as conn:
        res: Result = conn.execute(text("""
            SELECT id, webhook_url, api_secret, api_key
              FROM merchants
             ORDER BY webhook_url
        """))
        return [row_to_dict(r) for r in res]

@router.post("/merchants", response_model=MerchantOut, status_code=201)
def create_merchant(body: MerchantCreate, _: None = Depends(require_admin)):
    new_id = str(uuid4())
    api_key = body.api_key or f"sk_live_{uuid4().hex}"
    try:
        with engine.begin() as conn:
            res: Result = conn.execute(text("""
                INSERT INTO merchants (id, webhook_url, api_secret, api_key)
                VALUES (CAST(:id AS uuid), :webhook_url, :api_secret, :api_key)
             RETURNING id, webhook_url, api_secret, api_key
            """), dict(id=new_id, webhook_url=body.webhook_url, api_secret=body.api_secret, api_key=api_key))
            return row_to_dict(res.first())
    except IntegrityError as e:
        raise HTTPException(409, detail=f"Integrity error: {str(e.orig)}")
    except SQLAlchemyError as e:
        raise HTTPException(500, detail=f"DB error: {str(e)}")
    except Exception as e:
        raise HTTPException(500, detail=f"Unexpected: {str(e)}")

@router.patch("/merchants/{merchant_id}", response_model=MerchantOut)
def update_merchant(merchant_id: UUID, body: MerchantUpdate, _: None = Depends(require_admin)):
    sets = []
    params = {"id": str(merchant_id)}
    if body.webhook_url is not None:
        sets.append("webhook_url = :webhook_url"); params["webhook_url"] = body.webhook_url
    if body.api_secret is not None:
        sets.append("api_secret = :api_secret"); params["api_secret"] = body.api_secret
    if body.api_key is not None:
        sets.append("api_key = :api_key"); params["api_key"] = body.api_key
    if not sets:
        raise HTTPException(400, "Nothing to update")

    try:
        with engine.begin() as conn:
            res: Result = conn.execute(text(f"""
                UPDATE merchants SET {", ".join(sets)}
                 WHERE id = CAST(:id AS uuid)
             RETURNING id, webhook_url, api_secret, api_key
            """), params)
            row = res.first()
            if not row:
                raise HTTPException(404, "Merchant not found")
            return row_to_dict(row)
    except IntegrityError as e:
        raise HTTPException(409, detail=f"Integrity error: {str(e.orig)}")
    except SQLAlchemyError as e:
        raise HTTPException(500, detail=f"DB error: {str(e)}")

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

# ---------- PAYMENTS ----------
@router.get("/payments", response_model=List[PaymentOut])
def list_payments(
    _: None = Depends(require_admin),
    q: Optional[str] = Query(None),
    status: Optional[PaymentStatus] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    where = ["1=1"]; params = {}
    if q: where.append("(p.idempotency_key ILIKE :q OR p.currency ILIKE :q)"); params["q"] = f"%{q}%"
    if status: where.append("p.status = :status"); params["status"] = status
    with engine.begin() as conn:
        res: Result = conn.execute(text(f"""
            SELECT p.payment_id, p.merchant_id, p.amount, p.currency, p.status,
                   p.idempotency_key, p.created_at,
                   m.webhook_url AS merchant_webhook_url
              FROM payments p
              LEFT JOIN merchants m ON m.id = p.merchant_id
             WHERE {" AND ".join(where)}
             ORDER BY p.created_at DESC
             LIMIT :limit OFFSET :offset
        """), {**params, "limit": limit, "offset": offset})
        return [row_to_dict(r) for r in res]

@router.patch("/payments/{payment_id}", response_model=PaymentOut)
def update_payment_status(payment_id: UUID, body: PaymentUpdate, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        res: Result = conn.execute(text("""
            UPDATE payments
               SET status = :status
             WHERE payment_id = CAST(:pid AS uuid)
         RETURNING payment_id, merchant_id, amount, currency, status,
                   idempotency_key, created_at,
                   (SELECT webhook_url FROM merchants m WHERE m.id = payments.merchant_id) AS merchant_webhook_url
        """), {"pid": str(payment_id), "status": body.status})
        row = res.first()
        if not row: raise HTTPException(404, "Payment not found")
        return row_to_dict(row)

@router.post("/payments/{payment_id}/resend-webhook", status_code=202)
def resend_webhook(payment_id: UUID, _: None = Depends(require_admin)):
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM payments WHERE payment_id = CAST(:pid AS uuid)
        """), {"pid": str(payment_id)}).first()
        if not exists: raise HTTPException(404, "Payment not found")
        conn.execute(text("""
            INSERT INTO webhook_outbox (payment_id, delivered)
                 VALUES (CAST(:pid AS uuid), FALSE)
            ON CONFLICT (payment_id) DO UPDATE SET delivered = FALSE
        """), {"pid": str(payment_id)})
    return {"status": "queued"}

class StatsOut(BaseModel):
    counts_by_status: dict
    merchants_total: int
    payments_total: int

@router.get("/stats", response_model=StatsOut)
def get_stats(_: None = Depends(require_admin)):
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT status, COUNT(*) AS cnt FROM payments GROUP BY status")).all()
        counts = {r.status: r.cnt for r in rows}
        merchants_total = conn.execute(text("SELECT COUNT(*) FROM merchants")).scalar_one()
        payments_total = conn.execute(text("SELECT COUNT(*) FROM payments")).scalar_one()
    return StatsOut(counts_by_status=counts, merchants_total=merchants_total, payments_total=payments_total)
