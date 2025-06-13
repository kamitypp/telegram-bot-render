import requests
import os

# Уверете се, че TELEGRAM_TOKEN е наличен като променлива на средата,
# както във вашето основно приложение.
# Или го поставете директно за теста, ако не е зададено.
# КОРЕКЦИЯ: Добавени са кавички около стойността на токена
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7380464303:AAFm4HxW3k_BnyX5evh5rxgsCQOHwjC28I0")

# Заменете с реалното ID на чата, където вие сте изпращали съобщения към бота.
# Можете да го вземете от лога на вашето Python приложение: INFO:main:Type: Message, Chat ID: XXXXXXXXXX
chat_id = 7756798441 

message_text = "Здравейте, това е ПРЯК тест от бота! Моля, потвърдете дали виждате това съобщение."

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
payload = {"chat_id": chat_id, "text": message_text}

try:
    response = requests.post(url, json=payload)
    response.raise_for_status() # Ще предизвика HTTPError за лоши отговори (4xx или 5xx)
    print(f"Telegram API response: Status: {response.status_code}, Body: {response.text}")
except requests.exceptions.RequestException as e:
    print(f"Error sending message to Telegram: {e}")