from datetime import datetime, timedelta

from apscheduler.triggers.cron import CronTrigger
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters, ContextTypes
)

from bitrix_service import get_completed_tasks_report, get_overdue_tasks_report
from config import BOT_TOKEN
from db import init_db, get_users_for_weekly_report, get_users_for_daily_report
from handlers.admin import admin_command_handler, ainfo_command_handler
from handlers.main import (start_handler, text_message_handler,
                           info_command_handler, url_command_handler,
                           bitrixid_command_handler, delay_command_handler,
                           notifications_command_handler,
                           main_command_handler, report_command_handler)
import logging
import asyncio
from apscheduler import Scheduler
logging.basicConfig(
    filename='bot.log',
    filemode='w',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)


async def delay_command_handler_daily_all(application,
                                          context: ContextTypes.DEFAULT_TYPE):
    users = get_users_for_daily_report()
    if not users:
        logging.info("Нет пользователей для ежедневного отчета.")
        return

    for user in users:
        telegram_id, username, bitrix_url, main_chat_id = user
        report_text = get_overdue_tasks_report(bitrix_url)
        if not report_text:
            report_text = "Нет просроченных задач."
        try:
            await application.bot.send_message(chat_id=main_chat_id,
                                               text=report_text,
                                               parse_mode="Markdown")
            logging.info(f"Отчет для пользователя {username} отправлен "
                         f"в чат {main_chat_id}.")
        except Exception as e:
            logging.error(f"Ошибка при отправке отчета для пользователя "
                          f"{username} в чат {main_chat_id}: {e}")


async def weekly_report_job(application):
    now = datetime.now()
    one_week_ago = now - timedelta(days=7)
    start_date = one_week_ago.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    end_date = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")

    users = get_users_for_weekly_report()
    if not users:
        logging.info("Нет пользователей для отправки еженедельного отчёта.")
        return

    for user in users:
        telegram_id, username, bitrix_url = user
        report = get_completed_tasks_report(bitrix_url, start_date, end_date)
        try:
            await application.bot.send_message(chat_id=telegram_id,
                                               text=report)
            logging.info(
                f"Отчёт отправлен пользователю {username} (Telegram ID: "
                f"{telegram_id}).")
        except Exception as e:
            logging.error(
                f"Ошибка при отправке отчёта пользователю {username} (ID: "
                f"{telegram_id}): {e}")


def weekly_report_job_wrapper(application):
    asyncio.run(weekly_report_job(application))


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

    with Scheduler() as scheduler:
        daily_trigger = CronTrigger(hour=10, minute=0)
        weekly_trigger = CronTrigger(day_of_week='sun', hour=10, minute=0)

        scheduler.add_schedule(
            delay_command_handler_daily_all,
            daily_trigger,
            args=[application, None],
            id='daily_task'
        )

        scheduler.add_schedule(
            weekly_report_job_wrapper,
            weekly_trigger,
            args=[application],
            id='weekly_task'
        )
        scheduler.start_in_background()

    application.run_polling()


if __name__ == "__main__":
    main()
