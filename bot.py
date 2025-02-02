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
                           notifications_command_handler,
                           delay_command_handler_daily_all,
                           main_command_handler, report_command_handler)
import logging
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler

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
    application.add_handler(CommandHandler("main", main_command_handler))
    application.add_handler(CommandHandler("report", report_command_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                           text_message_handler))

    init_db()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        delay_command_handler_daily_all,
        "cron",
        hour=10,
        minute=0,
        args=[application, None]
    )
    scheduler.start()

    application.run_polling()


if __name__ == "__main__":
    main()
