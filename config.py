import os
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

if not BOT_TOKEN:
    raise ValueError("ОШИБКА: Токен бота BOT_TOKEN не указан в файле .env!")
if OWNER_ID == 0:
    raise ValueError("ОШИБКА: OWNER_ID не указан в файле .env!")