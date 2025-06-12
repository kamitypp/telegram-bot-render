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
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db' # Това е SQLite база данни, ще бъде файл site.db
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Препоръчително е да е False
db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_chat_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    city = db.Column(db.String(50), nullable=True)
    label = db.Column(db.String(50), nullable=True) # e.g., "courier", "non-working", or anything else you need
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f"User('{self.telegram_chat_id}', '{self.name}', '{self.email}', '{self.label}')"

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_type = db.Column(db.String(10), nullable=False) # 'inbound' or 'outbound'
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.now())
    dialogflow_response_id = db.Column(db.String(100), nullable=True) # For linking to DF CX history
    raw_telegram_json = db.Column(db.Text, nullable=True)
    raw_dialogflow_json = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"ChatMessage('{self.user_id}', '{self.message_type}', '{self.timestamp}')"

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
        # Find or create user
        user = db.session.execute(db.select(User).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none()
        if not user:
            user = User(telegram_chat_id=str(chat_id))
            db.session.add(user)
            db.session.commit() # Commit to get user.id for ChatMessage
            logger.info(f"New user created in DB with chat_id: {chat_id}")

        # Log inbound message
        inbound_msg = ChatMessage(
            user_id=user.id,
            message_type='inbound',
            text=user_input,
            raw_telegram_json=telegram_raw_json
        )
        db.session.add(inbound_msg)
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
        user = db.session.execute(db.select(User).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none()
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
        user = db.session.execute(db.select(User).filter_by(telegram_chat_id=str(chat_id))).scalar_one_or_none()
        if user:
            outbound_msg = ChatMessage(
                user_id=user.id,
                message_type='outbound',
                text=final_fulfillment_text,
                dialogflow_response_id=dfcx_response_dict.get('responseId'),
                raw_dialogflow_json=json.dumps(dfcx_response_dict) # Store full DF CX response JSON
            )
            db.session.add(outbound_msg)
            db.session.commit()
            logger.info(f"Outbound message logged for user {chat_id}")

    return jsonify({"status": "success"})


if __name__ == '__main__':
    # Initialize logging (moved here for clarity, though already at top)
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    with app.app_context():
        db.create_all() # Creates tables in the database if they don't exist
        logger.info("Database tables checked/created.")
    # For Render, the port is usually 10000. For local testing, 5000 is common.
    # Host '0.0.0.0' makes it accessible externally (required for Render)
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 10000))