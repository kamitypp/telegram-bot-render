import os
import logging
import requests
from flask import Flask, request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PROJECT_ID = "freebot-461207"
CREDENTIALS_FILE = "/etc/secrets/freebot-461207-c76a09ed3cfa.json"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN missing")
if not os.path.exists(CREDENTIALS_FILE):
    raise FileNotFoundError(f"❌ Credentials file not found: {CREDENTIALS_FILE}")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

credentials = service_account.Credentials.from_service_account_file(
    CREDENTIALS_FILE, scopes=SCOPES
)

def get_dialogflow_token():
    if not credentials.valid or credentials.expired:
        credentials.refresh(Request())
    return credentials.token

def detect_intent_text(text, session_id):
    token = get_dialogflow_token()
    url = f"https://dialogflow.googleapis.com/v2/projects/{PROJECT_ID}/agent/sessions/{session_id}:detectIntent"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    body = {
        "queryInput": {
            "text": {"text": text, "languageCode": "bg"}
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=5)
        logging.info("🎯 DF status: %s", response.status_code)
        logging.info("📦 DF raw: %s", response.text)

        if response.status_code != 200:
            return "🤖 Грешка свързване с Dialogflow."

        data = response.json()
        logging.info("📦 DF JSON: %s", data)
        fulfillment = data.get("queryResult", {}).get("fulfillmentText")
        logging.info("📦 fulfillmentText: %s", fulfillment)

        return fulfillment or "🤖 Няма отговор."

    except requests.RequestException as e:
        logging.error("⚠️ Exception при Dialogflow: %s", e)
        return "🤖 Възникна грешка при dialogflow."

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    logging.info("📥 From Telegram: %s", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")

    if not chat_id or not text:
        logging.warning("⚠️ Няма chat_id или текст")
        return {"ok": True}

    reply = detect_intent_text(text, session_id=str(chat_id))
    logging.info("↩️ Reply to send: %s", reply)

    requests.post(TELEGRAM_API_URL, json={
        "chat_id": chat_id,
        "text": reply
    }, timeout=5)
    return {"ok": True}

@app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is live!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
