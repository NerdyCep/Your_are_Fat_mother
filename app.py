from fastapi import FastAPI
from pydantic import BaseModel
import random
import asyncio

app = FastAPI(title="Acquirer Simulator")

class Payment(BaseModel):
    idempotency_key: str
    amount: float
    currency: str
    user_id: str
    card_number: str
    card_expiry: str
    cvv: str

@app.post("/process_payment")
async def process_payment(payment: Payment):
    await asyncio.sleep(random.uniform(0.2, 1))  # имитация задержки
    # Имитация успеха/неудачи (90% успех)
    if random.random() < 0.9:
        return {"status": "approved"}
    else:
        return {"status": "declined"}
