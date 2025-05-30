from flask import Flask, request
import requests
import os

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DIALOGFLOW_TOKEN = os.getenv("DIALOGFLOW_TOKEN")
DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID")

# ➕ Поддържа GET за проверка дали е live
@app.route("/", methods=["GET"])
def index():
    return "Bot is live!", 200

# 🔧 Основният webhook endpoint
@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.get_json()

    if not data or "message" not in data:
        return "ok"

    message = data["message"]
    chat_id = message["chat"]["id"]
    user_text = message.get("text", "")

    # ➤ Заявка към Dialogflow
    dialogflow_url = f"https://dialogflow.googleapis.com/v2/projects/{DIALOGFLOW_PROJECT_ID}/agent/sessions/{chat_id}:detectIntent"
    headers = {
        "Authorization": f"Bearer {DIALOGFLOW_TOKEN}",
        "Content-Type": "application/json"
    }

    body = {
        "queryInput": {
            "text": {
                "text": user_text,
                "languageCode": "bg"
            }
        }
    }

    try:
        response = requests.post(dialogflow_url, headers=headers, json=body)
        response.raise_for_status()
        reply = response.json()["queryResult"]["fulfillmentText"]
    except Exception as e:
        reply = "🤖 Грешка при свързване с Dialogflow."

    # ➤ Изпращане на отговор към Telegram
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(telegram_url, data={"chat_id": chat_id, "text": reply})

    return "ok", 200

if __name__ == "__main__":
    app.run(debug=False)
