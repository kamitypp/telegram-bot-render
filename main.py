import os
import json
import requests
from flask import Flask, request, jsonify # Добавих jsonify за по-добра обработка на JSON отговори
from google.auth.transport.requests import Request
from google.oauth2 import service_account

app = Flask(__name__)

# Зареждаме service account credentials
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
SERVICE_ACCOUNT_FILE = "/etc/secrets/freestreets-1736017814504-fb8a19bd0fed.json"

# Уверете се, че файлът съществува
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    print(f"Error: Service account file not found at {SERVICE_ACCOUNT_FILE}")
    # Можете да изберете да спрете приложението или да използвате mock credentials за локален тест
    # За Render, този път е правилен, ако е настроен като Secret File
    exit(1) # За локален тест, може да спрете, ако файлът липсва

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

# Правилна конфигурация на CX агента
PROJECT_ID = "freestreets-1736017814504"
REGION = "europe-west3"
AGENT_ID = "95163a7e-670b-4e91-bbd6-71df5db9feaf"
LANGUAGE_CODE = "bg" # Уверете се, че това съответства на езика в Dialogflow CX

# --- Модифицирана функция за извикване на Dialogflow CX ---
# Тази функция вече ще връща целия 'queryResult' обект,
# за да можем да проверим за 'responseMessages' и 'payload'.
def detect_dialogflow_intent(text_or_event, session_id):
    """
    Извиква Dialogflow CX detectIntent API.
    Приема текст за потребителски вход или event name (за специални случаи).
    Връща целия 'queryResult' отговор от Dialogflow CX.
    """
    session_path = f"projects/{PROJECT_ID}/locations/{REGION}/agents/{AGENT_ID}/sessions/{session_id}"

    # Опресняваме токена за достъп, ако е необходимо
    creds.refresh(Request())
    url = f"https://{REGION}-dialogflow.googleapis.com/v3/{session_path}:detectIntent"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }

    body = {
        "queryInput": {
            # Проверяваме дали входът е текст или събитие (event)
            # В случая на бутони, callback_data се третира като текст
            "text": {
                "text": text_or_event # Независимо дали е текст или callback_data
            },
            "languageCode": LANGUAGE_CODE
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status() # Предизвиква HTTPError за лоши отговори (4xx или 5xx)
        response_data = response.json()
        print(f"Dialogflow CX Response: {json.dumps(response_data, indent=2)}") # За дебъгване
        return response_data.get("queryResult", {})
    except requests.exceptions.RequestException as e:
        print(f"Error calling Dialogflow CX API: {e}")
        return None # Връщаме None при грешка


# TELEGRAM обработка
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" # Преименувах променливата за яснота

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(f"Received Telegram webhook data: {json.dumps(data, indent=2)}") # За дебъгване

    if not data:
        print("Received empty data from webhook.")
        return jsonify({"status": "ok"})

    chat_id = None
    user_input = None # Това ще е текст от съобщение или callback_data от бутон

    # Различаваме дали е обикновено съобщение или натиснат бутон (callback_query)
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        user_input = data["message"].get("text", "")
        print(f"Type: Message, Chat ID: {chat_id}, Text: '{user_input}'")
    elif "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        user_input = data["callback_query"]["data"] # Callback data от бутона
        # Telegram очаква да потвърдите callback_query
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": data["callback_query"]["id"]})
        except Exception as e:
            print(f"Error answering callback query: {e}")
        print(f"Type: Callback Query, Chat ID: {chat_id}, Data: '{user_input}'")
    else:
        print("Received unknown update type. Ignoring.")
        return jsonify({"status": "ok"}) # Игнорираме други типове ъпдейти

    if not chat_id or user_input is None:
        print("Could not extract chat_id or user_input. Ignoring.")
        return jsonify({"status": "ok"})

    # Изпращаме потребителския вход към Dialogflow CX
    dfcx_query_result = detect_dialogflow_intent(user_input, str(chat_id))

    if not dfcx_query_result:
        # Изпращаме съобщение за грешка на потребителя, ако Dialogflow CX не отговори
        try:
            requests.post(TELEGRAM_API_URL, json={
                "chat_id": chat_id,
                "text": "Извинявам се, възникна проблем. Моля, опитайте отново по-късно."
            })
        except Exception as e:
            print(f"Error sending fallback message to Telegram: {e}")
        return jsonify({"status": "error", "message": "Failed to get response from Dialogflow CX"})

    # --- НОВАТА ЛОГИКА ЗА ОБРАБОТКА НА CUSTOM PAYLOAD И БУТОНИ ---
    fulfillment_text = "Няма отговор." # Дефолтен отговор
    telegram_reply_markup = None

    # Вземаме основния текстов отговор, ако има такъв
    if dfcx_query_result.get("responseMessages"):
        for msg in dfcx_query_result["responseMessages"]:
            if "text" in msg and msg["text"].get("text"):
                fulfillment_text = msg["text"]["text"][0] # Вземаме първия текстов отговор
                break # Вземаме само първия текстов отговор
        
        # Проверяваме за custom payload, който съдържа Telegram специфична информация
        for msg in dfcx_query_result["responseMessages"]:
            if "payload" in msg:
                payload_data = msg["payload"]
                if "telegram" in payload_data:
                    telegram_data = payload_data["telegram"]
                    if "reply_markup" in telegram_data:
                        telegram_reply_markup = telegram_data["reply_markup"]
                        print(f"Found Telegram reply_markup: {json.dumps(telegram_reply_markup, indent=2)}")
                        # Не break-ваме тук, за да позволим други отговори, ако има

    # Изграждаме параметрите за изпращане до Telegram
    telegram_params = {
        "chat_id": chat_id,
        "text": fulfillment_text
    }

    # Ако сме намерили reply_markup от custom payload, го добавяме
    if telegram_reply_markup:
        telegram_params["reply_markup"] = telegram_reply_markup
        # За inline бутони, Text field може да не е задължителен, но е добра практика да го има
        # Ако искате да изпратите само бутони без текст, можете да промените fulfillment_text на празен низ
        # или да добавите отделна логика за това.

    # Изпращаме отговора обратно към Telegram
    try:
        telegram_response = requests.post(TELEGRAM_API_URL, json=telegram_params)
        telegram_response.raise_for_status() # Предизвиква грешка за HTTP грешки (4xx или 5xx)
        print(f"Message sent to Telegram. Status: {telegram_response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message to Telegram: {e}")
        # Можете да логвате и други детайли за грешката

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    # За локален тест, ако SERVICE_ACCOUNT_FILE е в същата директория:
    # SERVICE_ACCOUNT_FILE = "freestreets-1736017814504-fb8a19bd0fed.json"
    # creds = service_account.Credentials.from_service_account_file(
    #     SERVICE_ACCOUNT_FILE, scopes=SCOPES
    # )
    app.run(port=5000) # Може да промените порта, ако е необходимо