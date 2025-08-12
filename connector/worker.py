# connector/worker.py
import json, time, requests
from kafka import KafkaConsumer, KafkaProducer
import os

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "redpanda:9092")
API_CALLBACK_URL = os.getenv("API_CALLBACK", "http://api:8000/v1/payments/callback")
ACQUIRER_URL = os.getenv("ACQUIRER_URL", "http://acquirer:5000/process")

consumer = KafkaConsumer(
    "payments",
    bootstrap_servers=KAFKA_BOOTSTRAP,
    value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='connector-group'
)

print("Connector started, awaiting messages...")

for msg in consumer:
    data = msg.value
    payment_id = data.get("payment_id")
    print(f"[connector] processing payment {payment_id}")
    try:
        # send to acquirer
        resp = requests.post(ACQUIRER_URL, json=data, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        status = result.get("status", "failed")
    except Exception as e:
        print(f"[connector] error contacting acquirer: {e}")
        status = "error"

    # post back to API callback
    try:
        cb = {"payment_id": payment_id, "status": status}
        r2 = requests.post(API_CALLBACK_URL, json=cb, timeout=10)
        if r2.status_code == 200:
            print(f"[connector] updated API with status={status} for {payment_id}")
        else:
            print(f"[connector] API callback returned {r2.status_code}, body={r2.text}")
    except Exception as e:
        print(f"[connector] failed callback: {e}")
