from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# db обектът ще бъде инициализиран в main.py
# Тук го дефинираме празен, защото Alembic има нужда от него.
db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'telegram_users' # Важно: трябва да съвпада с името на таблицата
    id = db.Column(db.Integer, primary_key=True)
    telegram_chat_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    username = db.Column(db.String(255))
    language_code = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    # Връзка към ChatMessage - backref създава 'user' атрибут в ChatMessage
    messages = db.relationship('ChatMessage', backref='user', lazy=True)

    def __repr__(self):
        return f"<User {self.telegram_chat_id}>"

class ChatMessage(db.Model):
    __tablename__ = 'chat_message' # Важно: трябва да съвпада с името на таблицата
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('telegram_users.id'), nullable=False) # Коригиран foreign key
    message_type = db.Column(db.String(50), nullable=False) # 'inbound' or 'outbound'
    message_text = db.Column(db.Text, nullable=False)
    is_from_user = db.Column(db.Boolean, nullable=False) # True if from user, False if from bot
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
    raw_telegram_json = db.Column(db.Text) # To store full Telegram request for inbound
    dialogflow_response_id = db.Column(db.String(255)) # ID от Dialogflow CX отговора
    raw_dialogflow_json = db.Column(db.Text) # To store full Dialogflow CX response for outbound

    def __repr__(self):
        return f"<ChatMessage {self.id} from user {self.user_id}>"