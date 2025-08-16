from flask import Flask, request, jsonify
import sys

app = Flask(__name__)

@app.route("/merchant-webhook", methods=["POST"])
def hook():
    sig = request.headers.get("X-Signature")
    print("[merchant_webhook] got event:", request.json, "X-Signature:", sig, file=sys.stdout, flush=True)
    return jsonify({"ok": True})

@app.get("/health")
def health():
    return jsonify({"status":"ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
