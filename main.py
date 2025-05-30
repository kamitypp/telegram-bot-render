import os
import requests
from flask import Flask, request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

app = Flask(__name__)

# Конфигурации
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID")

# Аутентикация с Service Account JSON
CREDENTIALS_FILE = "/etc/secrets/freestreets-1736017814504-2e3680439af6.json"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

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
    response = requests.post(url, headers=headers, json=body)
    if response.status_code != 200:
        print("❌ Грешка при свързване с Dialogflow:", response.text)
        return "🤖 Грешка при свързване с Dialogflow."
    return response.json().get("queryResult", {}).get("fulfillmentText", "🤖 Няма отговор.")

# Webhook за Telegram
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text")
    if chat_id and text:
        reply = detect_intent_text(text, session_id=str(chat_id))
        requests.post(TELEGRAM_API_URL, json={
            "chat_id": chat_id,
            "text": reply
        })
    return {"ok": True}

@app.route("/", methods=["GET"])
def index():
    return "🤖 Bot is live!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
