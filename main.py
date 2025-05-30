from flask import Flask, request
import requests
import os

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DIALOGFLOW_TOKEN = os.getenv("DIALOGFLOW_TOKEN")
DIALOGFLOW_PROJECT_ID = os.getenv("DIALOGFLOW_PROJECT_ID")

@app.route('/')
def index():
    return "Bot is live!"

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def telegram_webhook():
    data = request.get_json()

    if "message" not in data:
        return "ok"

    message = data['message']
    chat_id = message['chat']['id']
    user_text = message.get('text', '')

    # Dialogflow request
    dialogflow_url = f"https://dialogflow.googleapis.com/v2/projects/{DIALOGFLOW_PROJECT_ID}/agent/sessions/{chat_id}:detectIntent"
    headers = {
        'Authorization': f'Bearer {DIALOGFLOW_TOKEN}',
        'Content-Type': 'application/json'
    }

    body = {
        "query_input": {
            "text": {
                "text": user_text,
                "language_code": "bg"
            }
        }
    }

    response = requests.post(dialogflow_url, headers=headers, json=body)
    reply = "🤖 Не разбрах."

    try:
        reply = response.json()['queryResult']['fulfillmentText']
    except:
        pass

    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': reply})

    return "ok"
