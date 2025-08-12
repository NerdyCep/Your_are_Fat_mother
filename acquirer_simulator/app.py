# acquirer_simulator/app.py
from flask import Flask, request, jsonify
import random, time

app = Flask(__name__)

@app.route("/process", methods=["POST"])
def process():
    payload = request.json or {}
    # simulate processing time
    time.sleep(random.uniform(0.1, 0.6))
    # simple deterministic-ish result by amount (for easier testing):
    amount = payload.get("amount", 0)
    # if amount divisible by 2 -> approved, else declined (so tests can vary)
    if isinstance(amount, int) and amount % 2 == 0:
        status = "approved"
    else:
        # small chance of random error
        status = random.choice(["declined", "approved", "declined"])
    return jsonify({"status": status})

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
