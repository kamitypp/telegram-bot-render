import os
import json
import requests
from flask import Flask, request
from google.auth.transport.requests import Request
from google.oauth2 import service_account

app = Flask(__name__)

# Зареждаме service account credentials
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
SERVICE_ACCOUNT_FILE = "/etc/secrets/freestreets-1736017814504-fb8a19bd0fed.json"
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

# Правилна конфигурация на CX агента
PROJECT_ID = "freestreets-1736017814504"
REGION = "europe-west3"
AGENT_ID = "95163a7e-670b-4e91-bbd6-71df5db9feaf"
LANGUAGE_CODE = "bg"

def detect_intent_text(text, session_id):
    session = f"projects/{PROJECT_ID}/locations/{REGION}/agents/{AGENT_ID}/sessions/{session_id}"

    creds.refresh(Request())
    url = f"https://{REGION}-dialogflow.googleapis.com/v3/{session}:detectIntent"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }

    body = {
        "queryInput": {
            "text": {
                "text": text
            },
            "languageCode": LANGUAGE_CODE
        }
    }

    response = requests.post(url, headers=headers, json=body)
    response_data = response.json()

    return response_data.get("queryResult", {}).get("responseMessages", [{}])[0].get("text", {}).get("text", ["🤖 Няма отговор."])[0]

# TELEGRAM обработка
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")
        reply = detect_intent_text(text, str(chat_id))

        requests.post(TELEGRAM_API, json={
            "chat_id": chat_id,
            "text": reply
        })

    return "ok"

if __name__ == "__main__":
    app.run()
