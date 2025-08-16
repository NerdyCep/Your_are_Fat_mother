from flask import Flask, request, jsonify
import random, time

app = Flask(__name__)

@app.route("/process", methods=["POST"])
def process():
    data = request.json or {}
    # имитация обработки
    time.sleep(0.1)
    status = random.choice(["approved","declined"])
    return jsonify({"status": status})

@app.get("/health")
def health():
    return jsonify({"status":"ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
