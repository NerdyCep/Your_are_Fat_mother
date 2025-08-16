import json, time, requests, os
from kafka import KafkaConsumer

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
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
    pid = data.get("payment_id")
    print(f"[connector] processing payment {pid}")
    status = "error"
    try:
        resp = requests.post(ACQUIRER_URL, json=data, timeout=15)
        resp.raise_for_status()
        status = resp.json().get("status", "failed")
    except Exception as e:
        print(f"[connector] error contacting acquirer: {e}")

    try:
        cb = {"payment_id": pid, "status": status}
        r2 = requests.post("http://api:8000/v1/payments/callback", json=cb, timeout=10)
        print(f"[connector] callback -> {r2.status_code}, status={status}")
    except Exception as e:
        print(f"[connector] callback failed: {e}")
