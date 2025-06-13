import os
import json
import requests
from flask import Flask, request, jsonify
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from flask_sqlalchemy import SQLAlchemy
import logging
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx # Import the Dialogflow CX client library
from google.protobuf.json_format import MessageToDict # To convert Protobuf Any to Python dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Database Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Препоръчително е да е False
db = SQLAlchemy(app)

# --- Database Models ---
class TelegramUser(db.Model):
    # Коригирано __tablename__ (правилно име и без излишна кавичка)
    __tablename__ = 'telegram_users' # Използвайте 'telegram_users' за яснота и избягване на конфликти
    id = db.Column(db.Integer, primary_key=True)
    telegram_chat_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    city = db.Column(db.String(255))
    label = db.Column(db.String(255)) # For storing current Dialogflow CX session/label
    last_updated = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    def __repr__(self):
        return f'<TelegramUser {self.telegram_chat_id}>'
    
class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Коригиран foreign key, за да сочи към новата таблица 'telegram_users'
    user_id = db.Column(db.Integer, db.ForeignKey('telegram_users.id'), nullable=False)
    message_text = db.Column(db.Text, nullable=False)
    is_from_user = db.Column(db.Boolean, nullable=False) # True if from user, False if from bot
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    # !!! МНОГО ВАЖНО: ТЕЗИ КОЛОНИ ВЕЧЕ СА ПРАВИЛНО ОТМЕСТЕНИ (с 4 интервала навътре) !!!
    message_type = db.Column(db.String(50)) # 'inbound' or 'outbound'
    raw_telegram_json = db.Column(db.Text) # To store full Telegram request for inbound
    dialogflow_response_id = db.Column(db.String(255)) # ID от Dialogflow CX отговора
    raw_dialogflow_json = db.Column(db.Text) # To store full Dialogflow CX response for outbound

    # Коригиран relationship, за да сочи към новия клас TelegramUser
    user = db.relationship('TelegramUser', backref=db.backref('messages', lazy=True))

    def __repr__(self):
        return f'<ChatMessage {self.id} from_user={self.is_from_user}>'
    
# Този блок е на правилното място и ще се изпълни при зареждане на модула от Gunicorn
with app.app_context():
    db.create_all()
    logger.info("Database tables checked/created.")

# --- Service Account Credentials ---
SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
SERVICE_ACCOUNT_FILE = "/etc/secrets/freestreets-1736017814504-fb8a19bd0fed.json"

if not os.path.exists(SERVICE_ACCOUNT_FILE):
    logger.error(f"Error: Service account file not found at {SERVICE_ACCOUNT_FILE}")
    exit(1)

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

# --- Dialogflow CX Agent Configuration ---
PROJECT_ID = "freestreets-1736017814504"
REGION = "europe-west3"
AGENT_ID = "95163a7e-670b-4e91-bbd6-71df5db9feaf"
LANGUAGE_CODE = "bg" # Bulgarian

# --- Dialogflow CX Intent Detection Function (using client library) ---
def detect_dialogflow_intent(text_or_event, session_id):
    """
    Calls Dialogflow CX detectIntent API using the client library.
    Takes user text input or an event name.
    Returns the full response dictionary from Dialogflow CX API.
    """
    client_options = None
    if REGION != "global":
        client_options = {"api_endpoint": f"{REGION}-dialogflow.googleapis.com:443"}

    # Use the service account credentials directly with the client
    session_client = dialogflow_cx.SessionsClient(credentials=creds, client_options=client_options)
    session_path = session_client.session_path(PROJECT_ID, REGION, AGENT_ID, session_id)

    logger.info(f"Dialogflow CX Session Path: {session_path}")

    # Prepare the query input
    text_input = dialogflow_cx.TextInput(text=text_or_event)
    query_input = dialogflow_cx.QueryInput(text=text_input, language_code=LANGUAGE_CODE)

    request_obj = dialogflow_cx.DetectIntentRequest(
        session=session_path,
        query_input=query_input
    )

    try:
        response = session_client.detect_intent(request=request_obj)
        # Convert response to dictionary for easier logging and JSON serialization
        response_dict = MessageToDict(response._pb) # ._pb gives the underlying protobuf message
        logger.info(f"Dialogflow CX Response (Library): {json.dumps(response_dict, indent=2)}")
        return response_dict
    except Exception as e:
        logger.error(f"Error calling Dialogflow CX API with client library: {e}", exc_info=True)
        return None

# --- Telegram Bot API Helper Function ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

def send_telegram_message(chat_id, text, reply_markup=None):
    """
    Изпраща съобщение обратно до Telegram потребител.
    Включва възможност за изпращане на бутони чрез reply_markup.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML" # Можете да използвате HTML за форматиране, ако е необходимо
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(TELEGRAM_API_URL, json=payload)
        response.raise_for_status() # Ще предизвика HTTPError за лоши отговори (4xx или 5xx)
        logger.info(f"Message sent to Telegram chat ID {chat_id}. Status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending message to Telegram chat ID {chat_id}: {e}", exc_info=True)

# --- Webhook Endpoint ---
@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json(silent=True, force=True)
    logger.info(f"Received Telegram webhook data: {json.dumps(req, indent=2)}")

    if not req:
        logger.info("Received empty data from webhook.")
        return jsonify({"status": "ok"})

    chat_id = None
    user_input = None
    telegram_raw_json = json.dumps(req) # Store the raw Telegram request JSON

    # Determine chat_id and user_input (message text or callback_data)
    if "message" in req:
        chat_id = req["message"]["chat"]["id"]
        user_input = req["message"].get("text", "")
        logger.info(f"Type: Message, Chat ID: {chat_id}, Text: '{user_input}'")
    elif "callback_query" in req:
        chat_id = req["callback_query"]["message"]["chat"]["id"]
        user_input = req["callback_query"]["data"]
        try:
            # Answer callback_query to remove "loading" state from the button in Telegram
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": req["callback_query"]["id"]})
        except Exception as e:
            logger.error(f"Error answering callback query: {e}")
        logger.info(f"Type: Callback Query, Chat ID: {chat_id}, Data: '{user_input}'")
    else:
        logger.info("Received unknown update type. Ignoring.")
        return jsonify({"status": "ok"})

    if not chat_id or user_input is None:
        logger.warning("Could not extract chat_id or user_input. Ignoring.")
        return jsonify({"status": "ok"})

    # --- DB: Log the inbound message and handle user ---
    with app.app_context():
        # Find or create user - ИЗПОЛЗВАЙТЕ TelegramUser (тази промяна е критична!)
        user = db.session.execute(db.select(TelegramUser).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none() 
        if not user:
            user = TelegramUser(telegram_chat_id=str(chat_id)) # ИЗПОЛЗВАЙТЕ TelegramUser (тази промяна е критична!)
            db.session.add(user)
            db.session.commit() # Commit to get user.id for ChatMessage
            logger.info(f"New user created in DB with chat_id: {chat_id}")

        # Log inbound message
        new_chat_message = ChatMessage(
            user_id=user.id,
            message_type='inbound',
            message_text=user_input, # Коригирано от message_text,, на user_input и премахната двойна запетая
            is_from_user=True,
            raw_telegram_json=telegram_raw_json # Коригирано от json.dumps на telegram_raw_json
        )
        db.session.add(new_chat_message)
        db.session.commit()
        logger.info(f"Inbound message logged for user {chat_id}")

    # Call Dialogflow CX
    dfcx_response_dict = detect_dialogflow_intent(user_input, str(chat_id))

    if not dfcx_response_dict:
        send_telegram_message(chat_id, "Извинете, възникна грешка. Моля, опитайте отново по-късно.")
        return jsonify({"status": "error", "message": "Failed to get response from Dialogflow CX"})

    query_result = dfcx_response_dict.get('queryResult', {})
    
    # --- Extract text and custom_payload for Telegram ---
    # This block now correctly initializes variables and processes messages without duplication.
    all_fulfillment_texts = [] 
    telegram_reply_markup = None 
    text_from_custom_payload = None 

    if 'fulfillmentResponse' in query_result and 'messages' in query_result['fulfillmentResponse']:
        for message in query_result['fulfillmentResponse']['messages']:
            # 1. Check for text fulfillment
            if 'text' in message and 'text' in message['text'] and message['text']['text'] and message['text']['text'][0].strip():
                all_fulfillment_texts.append(message['text']['text'][0].strip())
            
            # 2. Check for custom payload with Telegram reply_markup
            if 'payload' in message:
                payload_data = message['payload']
                if 'telegram' in payload_data:
                    telegram_data = payload_data['telegram']
                    if 'reply_markup' in telegram_data:
                        telegram_reply_markup = telegram_data['reply_markup']
                        logger.info(f"Found Telegram reply_markup: {json.dumps(telegram_reply_markup, indent=2)}")
                    
                    if 'text' in telegram_data and telegram_data['text'].strip():
                        text_from_custom_payload = telegram_data['text'].strip()
                        all_fulfillment_texts = [] # Clear other texts
                        all_fulfillment_texts.append(text_from_custom_payload)
                        break # Stop processing messages if Telegram payload with text is found
    
    # Construct final text message based on priority
    if text_from_custom_payload:
        final_fulfillment_text = text_from_custom_payload
    elif all_fulfillment_texts:
        final_fulfillment_text = "\n\n".join(all_fulfillment_texts)
    else:
        # Fallback to queryResult.text (from user's input), if no fulfillment texts or custom payload text found
        if 'text' in query_result and query_result['text'].strip():
            final_fulfillment_text = query_result['text'].strip()
        else:
            final_fulfillment_text = "Няма отговор."
            
    # --- DB: Save / Update User Data from Dialogflow CX Parameters ---
    with app.app_context():
        # Re-fetch user to ensure we're working with the freshest data, especially important in concurrent environments
        user = db.session.execute(db.select(TelegramUser).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none() # Използвайте TelegramUser
        if user:
            params = query_result.get('parameters', {}) # Get parameters as dict directly from MessageToDict output
            logger.info(f"Parsed parameters from DF CX: {params}")

            if 'name' in params and params['name']:
                # The 'name' parameter from @sys.person might be an object {'name': '...', 'original': '...'}
                # Handle this by taking the 'name' field if it's an object, or the value itself if it's a string
                if isinstance(params['name'], dict) and 'name' in params['name']:
                    user.name = params['name']['name']
                else:
                    user.name = str(params['name']) # Ensure it's a string, in case it's not a dict

            if 'email' in params and params['email']:
                user.email = params['email']
            if 'phone' in params and params['phone']:
                user.phone = params['phone']
            if 'city' in params and params['city']:
                # The 'city' parameter might be an object if mapped directly from a @sys.location entity
                # or a string if mapped from 'callback_data'. Handle both.
                if isinstance(params['city'], dict) and 'original' in params['city']:
                    user.city = params['city']['original']
                else:
                    user.city = params['city']
            
            # Example for 'label' parameter from Dialogflow CX.
            # If you have a parameter in DF CX called 'job_type' that you want to save as 'label':
            # if 'job_type' in params and params['job_type']:
            #     user.label = params['job_type']
            # Or if you manually set 'label' in Dialogflow CX fulfillment:
            # if 'label_param_name' in params and params['label_param_name']:
            #    user.label = params['label_param_name']

            db.session.commit()
            logger.info(f"User data updated in DB for {chat_id}: {user.name}, {user.email}, {user.phone}, {user.city}, {user.label}")
        else:
            logger.error(f"User with chat_id {chat_id} not found after initial creation. This should not happen.")

    # Send response back to Telegram, including buttons if available
    send_telegram_message(chat_id, final_fulfillment_text, telegram_reply_markup)

    # --- DB: Log the outbound message ---
    with app.app_context():
        user = db.session.execute(db.select(TelegramUser).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none() # Използвайте TelegramUser
        if user:
            new_chat_message = ChatMessage(
                user_id=user.id,
                message_text=final_fulfillment_text, # Коригирано от agent_response_text на final_fulfillment_text
                is_from_user=False,
                message_type="outbound", # Коригирано от "outnound" на "outbound"
                raw_dialogflow_json=json.dumps(dfcx_response_dict) # Store full DF CX response JSON
            )
            db.session.add(new_chat_message)
            db.session.commit()
            logger.info(f"Outbound message logged for user {chat_id}")

    return jsonify({"status": "success"})


if __name__ == '__main__':
    # Initialize logging (moved here for clarity, though already at top)
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 10000))
