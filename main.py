import os
import logging
import requests
from flask import Flask, request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# Настройка на логове
logging.basicConfig(level=logging.INFO)

# Flask приложение
app = Flask(__name__)

# Променливи на средата
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PROJECT_ID = "freebot-461207"
CREDENTIALS_FILE = "/etc/secrets/freebot-461207-c76a09ed3cfa.json"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# Проверки
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN липсва в средата.")

if not os.path.exists(CREDENTIALS_FILE):
    raise FileNotFoundError(f"❌ Service account файлът не съществува: {CREDENTIALS_FILE}")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Google Credentials
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
            "text": {
                "text": text,
                "languageCode": "bg"
            }
        }
    }

        try:
        response = requests.post(url, headers=headers, json=body, timeout=5)
        print("🎯 Dialogflow status:", response.status_code)
        print("🎯 Dialogflow raw response:", response.text)

        if response.status_code != 200:
            return "🤖 Грешка при свързване с Dialogflow."

        print("📦 Dialogflow response JSON:", response.json())
        print("📦 FulfillmentText:", response.json().get("queryResult", {}).get("fulfillmentText"))

        return response.json().get("queryResult", {}).get("fulfillmentText", "🤖 Няма отговор.")


    except requests.RequestException as e:
        print("⚠️ Exception при заявка към Dialogflow:", e)
        return "🤖 Възникна грешка при свързване с Dialogflow."

# Webhook за Telegram
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📥 Получено от Telegram:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")

    if not chat_id or not text:
        print("⚠️ Липсващ chat_id или текст.")
        return {"ok": True}

    reply = detect_intent_text(text, session_id=str(chat_id))

    requests.post(TELEGRAM_API_URL, json={
        "chat_id": chat_id,
        "text": reply
    }, timeout=5)

    return {"ok": True}

# Пинг роут
@app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is live!"

# Стартиране (локално)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
