from warnings import filterwarnings
import warnings
from telegram.warnings import PTBUserWarning, PTBDeprecationWarning
import logging

logging.basicConfig(
    filename='bot.log',
    filemode='w',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

filterwarnings(action="ignore", message=r".*CallbackQueryHandler",
               category=PTBUserWarning)
warnings.filterwarnings("error", category=PTBDeprecationWarning)


def start():
    logging.info("[DEBUG] Bot started")
