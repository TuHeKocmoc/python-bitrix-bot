import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "bitrixbot")
DB_PORT = int(os.getenv("DB_PORT", 5432))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TINKOFF_API_KEY = os.getenv("TINKOFF_API_KEY")
TINKOFF_SECRET_KEY = os.getenv("TINKOFF_SECRET_KEY")

ADMIN_IDS = [625079727, 694837524]
