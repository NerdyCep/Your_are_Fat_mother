# admin/app.py
import os
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqladmin import Admin
from starlette.middleware.cors import CORSMiddleware

# ВАЖНО: абсолютные импорты (без точки)
from auth import AdminAuthMiddleware
from models import Base  # (если решишь вызывать Base.metadata.create_all, но тут не нужно)
from views import PaymentAdmin, MerchantAdmin, WebhookOutboxAdmin

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@postgres:5432/payments",
)

app = FastAPI(title="Aggregator Admin")

# CORS (на локалке можно *; в проде — ужесточай)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# BasicAuth на /admin/*
app.add_middleware(AdminAuthMiddleware)

# SQLAlchemy engine + admin
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

admin = Admin(app, engine, base_url="/admin")
admin.add_view(PaymentAdmin)
admin.add_view(MerchantAdmin)
admin.add_view(WebhookOutboxAdmin)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
