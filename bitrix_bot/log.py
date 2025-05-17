from warnings import filterwarnings
import warnings
from telegram.warnings import PTBUserWarning, PTBDeprecationWarning
import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

filterwarnings(action="ignore", message=r".*CallbackQueryHandler",
               category=PTBUserWarning)
warnings.filterwarnings("error", category=PTBDeprecationWarning)


def start():
    logging.info("[DEBUG] Bot started")
