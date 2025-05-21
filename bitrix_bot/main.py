from . import log
from datetime import datetime, timedelta

import logging

from apscheduler.triggers.cron import CronTrigger
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters, ContextTypes
)

from .services.bitrix_service import (
    get_completed_tasks_report,
    get_overdue_tasks_report,
    get_task_fields_from_bitrix,
)
from .config import BOT_TOKEN
from .db import (
    init_db, get_users_for_weekly_report,
    get_users_for_daily_report, get_active_sprints,
    get_sprint_tasks, finish_sprint, get_user
)
from .handlers.admin import admin_command_handler, ainfo_command_handler
from .handlers.commands import (
    start_handler,
    info_command_handler,
    url_command_handler,
    bitrixid_command_handler,
    delay_command_handler,
    notifications_command_handler,
    main_command_handler,
    report_command_handler,
    tasks_command_handler,
    sprint_command_handler,
    set_sprint_deadline_handler,
    startsprint_command_handler,
    check_command_handler,
    endsprint_command_handler,
)
from .handlers.messages import text_message_handler
from .handlers.edit_task import edit_task_conv_handler
from .metrics import setup_metrics
import asyncio
from apscheduler import Scheduler


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


async def check_sprints_job(application):
    active = get_active_sprints()
    if not active:
        return

    for sprint in active:
        deadline = sprint.get("deadline")
        if deadline and deadline <= datetime.now():
            chat_id = sprint["chat_id"]

            # опред. bitrix url через админов
            admins = await application.bot.get_chat_administrators(chat_id)
            bitrix_url = None
            for adm in admins:
                row = get_user(adm.user.id)
                if row and row[1] and row[2]:
                    bitrix_url = row[2]
                    break

            task_ids = get_sprint_tasks(sprint["id"])
            lines = []
            completed = 0
            if bitrix_url:
                for t_id in task_ids:
                    fields = get_task_fields_from_bitrix(bitrix_url, t_id)
                    title = fields.get("TITLE") or fields.get("title") or "Без названия"
                    status = fields.get("REAL_STATUS")
                    closed = fields.get("CLOSED_DATE")
                    done = bool(closed) or (status and int(status) >= 5)
                    if done:
                        completed += 1
                    lines.append(f"{t_id}: {title} - {'✅' if done else '❌'}")

            percent = int(completed / len(task_ids) * 100) if task_ids else 0
            summary = (
                f"Спринт завершен! Выполнено {completed} из {len(task_ids)} "
                f"({percent}%)."
            )
            report = "\n".join(lines)
            await application.bot.send_message(chat_id=chat_id,
                                               text=summary + "\n" + report)
            finish_sprint(sprint["id"])


def main():
    log.start()
    setup_metrics()
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
    application.add_handler(CommandHandler("tasks", tasks_command_handler))
    application.add_handler(CommandHandler("sprint", sprint_command_handler))
    application.add_handler(CommandHandler("set_sprint_deadline",
                                             set_sprint_deadline_handler))
    application.add_handler(CommandHandler("startsprint",
                                             startsprint_command_handler))
    application.add_handler(CommandHandler("check",
                                             check_command_handler))
    application.add_handler(CommandHandler("endsprint",
                                             endsprint_command_handler))

    application.add_handler(edit_task_conv_handler)

    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE)
                                           & ~filters.COMMAND,
                                           text_message_handler))
    # application.add_handler(
    #     CallbackQueryHandler(edit_task_callback, pattern=r"^edit_task:"))

    init_db()

    with Scheduler() as scheduler:
        daily_trigger = CronTrigger(hour=10, minute=0)
        weekly_trigger = CronTrigger(day_of_week='sun', hour=10, minute=0)
        sprint_trigger = CronTrigger(minute="*")

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
        scheduler.add_schedule(
            check_sprints_job,
            sprint_trigger,
            args=[application],
            id='sprint_task'
        )
        scheduler.start_in_background()

    application.run_polling()


if __name__ == "__main__":
    main()
