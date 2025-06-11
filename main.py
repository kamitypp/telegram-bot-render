import os
import json
import requests
from flask import Flask, request, jsonify
from google.auth.transport.requests import Request
from google.oauth2 import service_account

app = Flask(__name__)

# Зареждаме service account credentials
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
SERVICE_ACCOUNT_FILE = "/etc/secrets/freestreets-1736017814504-fb8a19bd0fed.json"

# Уверете се, че файлът съществува
if not os.path.exists(SERVICE_ACCOUNT_FILE):
    print(f"Error: Service account file not found at {SERVICE_ACCOUNT_FILE}")
    exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

# Правилна конфигурация на CX агента
PROJECT_ID = "freestreets-1736017814504"
REGION = "europe-west3"
AGENT_ID = "95163a7e-670b-4e91-bbd6-71df5db9feaf"
LANGUAGE_CODE = "bg" # Уверете се, че това съответства на езика в Dialogflow CX

def detect_dialogflow_intent(text_or_event, session_id):
    """
    Извиква Dialogflow CX detectIntent API.
    Приема текст за потребителски вход или event name (за специални случаи).
    Връща целия 'queryResult' отговор от Dialogflow CX.
    """
    session_path = f"projects/{PROJECT_ID}/locations/{REGION}/agents/{AGENT_ID}/sessions/{session_id}"

    creds.refresh(Request())
    url = f"https://{REGION}-dialogflow.googleapis.com/v3/{session_path}:detectIntent"
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json"
    }

    body = {
        "queryInput": {
            "text": {
                "text": text_or_event
            },
            "languageCode": LANGUAGE_CODE
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        response_data = response.json()
        print(f"Dialogflow CX Response: {json.dumps(response_data, indent=2)}")
        return response_data.get("queryResult", {})
    except requests.exceptions.RequestException as e:
        print(f"Error calling Dialogflow CX API: {e}")
        return None


# TELEGRAM обработка
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(f"Received Telegram webhook data: {json.dumps(data, indent=2)}")

    if not data:
        print("Received empty data from webhook.")
        return jsonify({"status": "ok"})

    chat_id = None
    user_input = None

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        user_input = data["message"].get("text", "")
        print(f"Type: Message, Chat ID: {chat_id}, Text: '{user_input}'")
    elif "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        user_input = data["callback_query"]["data"]
        try:
            # Отговор на callback_query, за да изчезне "loading" състоянието на бутона в Telegram
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                          json={"callback_query_id": data["callback_query"]["id"]})
        except Exception as e:
            print(f"Error answering callback query: {e}")
        print(f"Type: Callback Query, Chat ID: {chat_id}, Data: '{user_input}'")
    else:
        print("Received unknown update type. Ignoring.")
        return jsonify({"status": "ok"})

    if not chat_id or user_input is None:
        print("Could not extract chat_id or user_input. Ignoring.")
        return jsonify({"status": "ok"})

    dfcx_query_result = detect_dialogflow_intent(user_input, str(chat_id))

    if not dfcx_query_result:
        try:
            requests.post(TELEGRAM_API_URL, json={
                "chat_id": chat_id,
                "text": "Извинявам се, възникна проблем. Моля, опитайте отново по-късно."
            })
        except Exception as e:
            print(f"Error sending fallback message to Telegram: {e}")
        return jsonify({"status": "error", "message": "Failed to get response from Dialogflow CX"})

    # --- НОВАТА И ПОДОБРЕНА ЛОГИКА ЗА ОБРАБОТКА НА CUSTOM PAYLOAD И БУТОНИ ---
    
    all_fulfillment_texts = [] # Списък за събиране на всички текстови отговори
    telegram_reply_markup = None
    text_from_custom_payload = None # За да приоритизираме текста, който е директно в payload-а на Telegram

    if dfcx_query_result.get("responseMessages"):
        for msg in dfcx_query_result["responseMessages"]:
            # Проверяваме за текстови отговори
            if "text" in msg and msg["text"].get("text") and msg["text"]["text"][0].strip():
                all_fulfillment_texts.append(msg["text"]["text"][0].strip())
            
            # Проверяваме за custom payload с Telegram специфична информация
            if "payload" in msg:
                payload_data = msg["payload"]
                if "telegram" in payload_data:
                    telegram_data = payload_data["telegram"]
                    if "reply_markup" in telegram_data:
                        telegram_reply_markup = telegram_data["reply_markup"]
                        print(f"Found Telegram reply_markup: {json.dumps(telegram_reply_markup, indent=2)}")
                    
                    # Ако custom payload съдържа и 'text' поле, това е текстът за бутоните
                    if "text" in telegram_data and telegram_data["text"].strip():
                        text_from_custom_payload = telegram_data["text"].strip()
                        # Ако намерим текст в custom payload, той ще бъде основният текст за съобщението
                        # и ще замести всички други текстове, събрани до момента, или ще бъде добавен като първи.
                        # За да гарантираме, че винаги се показва, дори и сам:
                        all_fulfillment_texts = [] # Изчистваме предишните текстове
                        all_fulfillment_texts.append(text_from_custom_payload)
                        # Тук може да решите дали да break-вате, ако custom payload винаги означава край на другите текстове.
                        # За повечето случаи, ако има custom payload с текст и бутони, той е достатъчен.
                        break # Спираме търсенето, ако намерим Telegram payload с текст и бутони

    # Изграждаме финалния текстов отговор
    final_fulfillment_text = ""
    if text_from_custom_payload: # Приоритет на текста от custom payload
        final_fulfillment_text = text_from_custom_payload
    elif all_fulfillment_texts:
        final_fulfillment_text = "\n\n".join(all_fulfillment_texts) # Обединяваме всички събрани текстове
    else:
        # Fallback към queryResult.text, ако няма други отговори (малко вероятно след горната логика)
        if dfcx_query_result.get("text") and dfcx_query_result["text"].strip():
            final_fulfillment_text = dfcx_query_result["text"].strip()
        else:
            final_fulfillment_text = "Няма отговор."
    
    # Изграждаме параметрите за изпращане до Telegram
    telegram_params = {
        "chat_id": chat_id,
        "text": final_fulfillment_text
    }

    # Ако сме намерили reply_markup от custom payload, го добавяме
    if telegram_reply_markup:
        telegram_params["reply_markup"] = telegram_reply_markup

    # Изпращаме отговора обратно към Telegram
    try:
        telegram_response = requests.post(TELEGRAM_API_URL, json=telegram_params)
        telegram_response.raise_for_status()
        print(f"Message sent to Telegram. Status: {telegram_response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending message to Telegram: {e}")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(port=os.environ.get("PORT", 5000), host="0.0.0.0")