import os
import json
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy # Уверете се, че този е там
from models import db, User, ChatMessage # <-- ТОЗИ РЕД Е НОВ
import requests
import logging # Уверете се, че logging е импортиран, ако не е.
from google.cloud import dialogflowcx_v3beta1 as dialogflowcx # Уверете се, че този е там
from datetime import datetime # <-- ТОЗИ РЕД Е НОВ (нужен за timestamp)


app = Flask(__name__)

# >>> НАЧАЛО НА НОВИЯ КОД ЗА БАЗА ДАННИ <<<
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Препоръчително за избягване на предупреждения
db.init_app(app) # Инициализирайте db обекта с Flask приложението
# >>> КРАЙ НА НОВИЯ КОД ЗА БАЗА ДАННИ <<<

# >>> НОВ КОД ЗА ИНИЦИАЛИЗАЦИЯ НА ЛОГЪРА <<<
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# >>> КРАЙ НА НОВ КОД ЗА ИНИЦИАЛИЗАЦИЯ НА ЛОГЪРА <<<

# ... останалите ви настройки (като TELEGRAM_TOKEN, Dialogflow CX ID-та)

# ... останалият ви код (настройки на логър, API ключове и т.н.)

# ... (след инициализацията на логъра, но преди TELEGRAM_TOKEN и webhook)

# Функция за извикване на Dialogflow CX API (предоствена от Google Cloud SDK)
def detect_intent_texts(project_id, location_id, agent_id, session_id, text, language_code):
    """Returns the result of detect intent with texts as inputs.
    Using the same `session_id` between requests allows continuation of the conversation.
    """
    session_path = f"projects/{project_id}/locations/{location_id}/agents/{agent_id}/sessions/{session_id}"
    client_options = None
    if location_id != "global":
        client_options = {"api_endpoint": f"{location_id}-dialogflow.googleapis.com"}
    
    session_client = dialogflowcx.SessionsClient(client_options=client_options)
    
    text_input = dialogflowcx.TextInput(text=text)
    query_input = dialogflowcx.QueryInput(text=text_input, language_code=language_code)
    
    try:
        response = session_client.detect_intent(
            request={"session": session_path, "query_input": query_input}
        )
        logger.info(f"Dialogflow CX query result: {response.query_result.fulfillment_response.messages}")
        return response
    except Exception as e:
        logger.error(f"Error detecting intent for session {session_id}: {e}", exc_info=True)
        return None

# TELEGRAM обработка (оставете както си е)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# ... (и сега ще заместим webhook функцията)

# TELEGRAM обработка
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logger.info(f"Received Telegram webhook data: {json.dumps(data, indent=2)}")

    message_data = data.get("message", {})
    chat_id = message_data.get("chat", {}).get("id")
    user_input = message_data.get("text") # Вземаме само текстовия вход от message

    # Ако е callback_query (от бутон), обработваме го
    if "callback_query" in data:
        chat_id = data["callback_query"]["message"]["chat"]["id"]
        user_input = data["callback_query"]["data"] # Данните от бутона са вход
        try:
            # Отговор на callback_query, за да изчезне "loading" състоянието на бутона в Telegram
            requests.post(f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN')}/answerCallbackQuery",
                          json={"callback_query_id": data["callback_query"]["id"]})
            logger.info(f"Answered callback query for chat ID: {chat_id}")
        except Exception as e:
            logger.error(f"Error answering callback query: {e}", exc_info=True)
        logger.info(f"Type: Callback Query, Chat ID: {chat_id}, Data: '{user_input}'")
    elif "message" in data:
        # Вече обработено по-горе за "text"
        logger.info(f"Type: Message, Chat ID: {chat_id}, Text: '{user_input}'")
    else:
        logger.warning("Received unknown update type. Ignoring.")
        return jsonify({"status": "ok"})


    if not chat_id or user_input is None: # user_input може да е празен стринг
        logger.warning("Could not extract chat_id or user_input. Ignoring.")
        return jsonify({"status": "ok"})

    # Извикайте Dialogflow CX
    dfcx_response = detect_intent_texts(
        project_id=os.environ.get('GOOGLE_CLOUD_PROJECT_ID'),
        location_id=os.environ.get('DIALOGFLOW_AGENT_LOCATION'),
        agent_id=os.environ.get('DIALOGFLOW_AGENT_ID'),
        session_id=str(chat_id), # Използвайте chat_id като session_id
        text=user_input,
        language_code=os.environ.get('DIALOGFLOW_AGENT_LANGUAGE_CODE', 'bg') # Може да бъде променлива на средата
    )
    
    # Проверка дали dfcx_response е None или липсва query_result
    if not dfcx_response or not dfcx_response.query_result:
        logger.error("Dialogflow CX did not return a valid query_result.")
        # Изпращане на грешка към Telegram
        try:
            requests.post(TELEGRAM_API_URL, json={
                "chat_id": chat_id,
                "text": "Извинявам се, възникна проблем при обработката на вашето съобщение. Моля, опитайте отново по-късно."
            })
            return jsonify({"status": "error", "message": "Dialogflow CX processing failed."}), 500
        except Exception as e:
            logger.error(f"Error sending fallback message to Telegram: {e}", exc_info=True)
            return jsonify({"status": "error", "message": "Internal server error."}), 500


    # Извличане на отговор от Dialogflow CX и обработка на Custom Payload
    final_fulfillment_text = ""
    telegram_reply_markup = None
    
    # Iterate through response_messages, looking for text and custom payloads
    if dfcx_response.query_result.response_messages:
        for message in dfcx_response.query_result.response_messages:
            # Get text response
            if message.text and message.text.text:
                # Concatenate all text responses
                final_fulfillment_text += " ".join(message.text.text) + " "
            
            # Get custom payload for Telegram
            if message.payload:
                # Convert protobuf Struct to Python dictionary
                payload_dict = dialogflowcx.types.struct_pb2.Struct.to_dict(message.payload)
                if "telegram" in payload_dict:
                    telegram_data = payload_dict["telegram"]
                    if "text" in telegram_data and telegram_data["text"].strip():
                        # If a 'text' field is present in the Telegram payload, prioritize it
                        final_fulfillment_text = telegram_data["text"].strip()
                    if "reply_markup" in telegram_data:
                        telegram_reply_markup = telegram_data["reply_markup"]
                        logger.info(f"Found Telegram reply_markup: {json.dumps(telegram_reply_markup, indent=2)}")
                    # If we found Telegram payload, we usually stop processing other messages
                    break # Assuming only one Telegram payload per response is expected

    final_fulfillment_text = final_fulfillment_text.strip()
    if not final_fulfillment_text:
        final_fulfillment_text = "Няма отговор от Dialogflow CX." # Fallback if no text was found

    logger.info(f"Final fulfillment text: '{final_fulfillment_text}'")
    logger.info(f"Telegram reply markup: {json.dumps(telegram_reply_markup, indent=2) if telegram_reply_markup else 'None'}")


    # >>> НАЧАЛО НА КОДА ЗА ЗАПИС В БАЗА ДАННИ (от предишния ми отговор) <<<
    try:
        with app.app_context():
            user = User.query.filter_by(telegram_chat_id=str(chat_id)).first()
            if not user:
                from_data = message_data.get("from", {}) # Извличане на данни от message_data, не data
                user = User(
                    telegram_chat_id=str(chat_id),
                    first_name=from_data.get("first_name"),
                    last_name=from_data.get("last_name"),
                    username=from_data.get("username"),
                    language_code=from_data.get("language_code")
                )
                db.session.add(user)
                db.session.commit()
                logger.info(f"New user created: {user.telegram_chat_id}")

            # Запис на входящо съобщение
            inbound_msg = ChatMessage(
                user_id=user.id,
                message_type='inbound',
                message_text=user_input,
                is_from_user=True,
                timestamp=datetime.fromtimestamp(message_data.get("date")) if message_data.get("date") else datetime.now(), # Използвайте времето от Telegram или текущо
                raw_telegram_json=json.dumps(data)
            )
            db.session.add(inbound_msg)
            db.session.commit()
            logger.info(f"Inbound message for user {chat_id} logged.")

            # Запис на изходящо съобщение
            if final_fulfillment_text:
                outbound_msg = ChatMessage(
                    user_id=user.id,
                    message_type='outbound',
                    message_text=final_fulfillment_text,
                    is_from_user=False,
                    timestamp=datetime.now(), # Текущо време за изходящо съобщение
                    dialogflow_response_id=dfcx_response.query_result.response_id if dfcx_response.query_result else None,
                    raw_dialogflow_json=json.dumps(dialogflowcx.QueryResult.to_json(dfcx_response.query_result)) if dfcx_response and dfcx_response.query_result else None
                )
                db.session.add(outbound_msg)
                db.session.commit()
                logger.info(f"Outbound message for user {chat_id} logged.")

    except Exception as e:
        logger.error(f"Failed to save message to database: {e}", exc_info=True)
        db.session.rollback() # Връщане на промените при грешка
    # >>> КРАЙ НА КОДА ЗА ЗАПИС В БАЗА ДАННИ <<<


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
        logger.info(f"Message sent to Telegram. Status: {telegram_response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to Telegram: {e}", exc_info=True)
        # Връщаме грешка, ако не можем да изпратим до Telegram
        return jsonify({"status": "error", "message": "Failed to send message to Telegram"}), 500

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=os.environ.get("PORT", 5000), host="0.0.0.0")