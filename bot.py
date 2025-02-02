from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters
)

from config import BOT_TOKEN
from db import init_db
from handlers.admin import admin_command_handler, ainfo_command_handler
from handlers.main import (start_handler, text_message_handler,
                           info_command_handler, url_command_handler,
                           bitrixid_command_handler, delay_command_handler,
                           notifications_command_handler)
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)


def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("info", info_command_handler))
    application.add_handler(CommandHandler("enable", admin_command_handler))
    application.add_handler(CommandHandler("disable", admin_command_handler))
    application.add_handler(CommandHandler("ainfo", ainfo_command_handler))
    application.add_handler(CommandHandler("url", url_command_handler))
    application.add_handler(
        CommandHandler("bitrixid", bitrixid_command_handler))
    application.add_handler(
        CommandHandler("notifications", notifications_command_handler))
    application.add_handler(CommandHandler("delay",
                                           delay_command_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           text_message_handler))

    init_db()
    application.run_polling()


if __name__ == "__main__":
    main()
