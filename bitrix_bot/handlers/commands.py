from datetime import datetime, timedelta
import asyncio
import logging

from telegram import Update, User
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from ..metrics import observe_command

from ..db import (
    add_user, set_url, get_url, get_user, set_user_bitrix_id,
    set_user_chat_id, set_main_chat_id, get_sprint_for_chat, create_sprint,
    set_sprint_deadline, start_sprint, get_sprint_tasks, finish_sprint
)
from ..services.bitrix_service import (
    get_overdue_tasks_report,
    get_completed_tasks_report,
    get_tasks_filtered_report,
    get_task_fields_from_bitrix,
)
from ..utils import get_url_by_type


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("start")
    logging.debug("start_handler called")
    telegram_user: User = update.effective_user
    telegram_id = telegram_user.id
    username = (telegram_user.username or telegram_user.first_name or telegram_id)
    try:
        bitrix_url = get_url(telegram_id)
        if bitrix_url is not None:
            await update.message.reply_text(
                f"Привет, {username}! Вы уже зарегистрированы. "
                f"/info — чтобы увидеть инфо."
            )
        else:
            await update.message.reply_text(
                f"Привет, {username}! /url -- задать Bitrix Webhook, "
                f"/bitrixid -- задать свой ID в системе"
            )
            add_user(telegram_id, username)
    except Exception as e:
        logging.error(f"Ошибка в /start: {e}")
        await update.message.reply_text(
            "Произошла ошибка при доступе к БД. Попробуйте позже."
        )


async def info_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("info")
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or telegram_id)
    try:
        user_row = get_user(telegram_id)
        if not user_row:
            add_user(telegram_id, username)
            user_row = get_user(telegram_id)

        is_enabled = user_row[1]
        bitrix_url = user_row[2] or "—"
        bitrix_id = user_row[3] or "—"

        info_text = (f"**Информация о пользователе**\n"
                     f"• Включен ли: {bool(is_enabled)}\n"
                     f"• Bitrix URL: {bitrix_url}\n"
                     f"• Bitrix ID: {bitrix_id}\n")

        await update.message.reply_text(info_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка в /info: {e}")
        await update.message.reply_text("Произошла ошибка при получении "
                                        "информации.")


async def url_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("url")
    message_text = update.message.text.split(None, 1)
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or telegram_id)

    if len(message_text) < 2:
        await update.message.reply_text("Использование: /url <Bitrix URL>")
        return

    bitrix_url = message_text[1].strip()
    user_row = get_user(telegram_id)
    if not user_row:
        add_user(telegram_id, username)

    try:
        set_url(telegram_id, bitrix_url)
        await update.message.reply_text(f"Bitrix URL сохранён: {bitrix_url}")
    except Exception as e:
        logging.error(f"Ошибка сохранения Bitrix URL: {e}")
        await update.message.reply_text("Ошибка при сохранении URL. "
                                        "Попробуйте позже.")


async def bitrixid_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("bitrixid")
    message_text = update.message.text.split(None, 1)
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or telegram_id)

    if len(message_text) < 2:
        await update.message.reply_text("Использование: /bitrixid <числовой ID>")
        return

    bitrix_id_str = message_text[1].strip()
    try:
        new_id = int(bitrix_id_str)
    except ValueError:
        await update.message.reply_text("Bitrix ID должен быть числом.")
        return

    user_row = get_user(telegram_id)
    if not user_row:
        add_user(telegram_id, username)

    try:
        set_user_bitrix_id(telegram_id, new_id)
        await update.message.reply_text(f"Bitrix ID сохранён: {new_id}")
    except Exception as e:
        logging.error(f"Ошибка сохранения Bitrix ID: {e}")
        await update.message.reply_text("Ошибка при сохранении. Попробуйте "
                                        "позже.")


async def notifications_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("notifications")
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or telegram_id)

    user_row = get_user(telegram_id)
    if not user_row:
        add_user(telegram_id, username)

    try:
        set_user_chat_id(telegram_id, chat_id)
        await update.message.reply_text(
            f"Ваш ID беседы (chat_id) сохранён: {chat_id}. "
            f"Теперь я буду писать уведомления в этой беседе."
        )
    except Exception as e:
        logging.error(f"Ошибка при сохранении chat_id для {telegram_id}: {e}")
        await update.message.reply_text("Ошибка при сохранении ID беседы. "
                                        "Попробуйте позже.")


async def delay_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("delay")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL для "
                                        "этой беседы.")
        return

    report_text = get_overdue_tasks_report(bitrix_url)
    await update.message.reply_text(report_text, parse_mode="Markdown")


async def main_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("main")
    telegram_user: User = update.effective_user
    telegram_id = telegram_user.id
    chat_id = update.effective_chat.id

    user_row = get_user(telegram_id)
    if not user_row:
        username = (telegram_user.username or telegram_user.first_name or str(telegram_id))
        add_user(telegram_id, username)

    try:
        set_main_chat_id(telegram_id, chat_id)
        await update.message.reply_text(f"Основная беседа установлена. ("
                                        f"main_chat_id = {chat_id})")
    except Exception as e:
        logging.error(f"Ошибка при установке main_chat_id для {telegram_id}: {e}")
        await update.message.reply_text("Ошибка при сохранении основной "
                                        "беседы. Попробуйте позже.")


async def report_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("report")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL для "
                                        "этой беседы.")
        return

    now = datetime.now()
    one_week_ago = now - timedelta(days=7)
    start_date = one_week_ago.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    end_date = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")

    report_text = await asyncio.to_thread(get_completed_tasks_report,
                                          bitrix_url, start_date, end_date)
    await update.message.reply_text(report_text)


async def tasks_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("tasks")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL для "
                                        "этой беседы.")
        return

    text = update.message.text.strip()
    parts = text.split(maxsplit=1)

    query = None
    if len(parts) > 1:
        possible_filter = parts[1].strip()
        try:
            query = int(possible_filter)
        except ValueError:
            query = possible_filter

    report_text = get_tasks_filtered_report(bitrix_url, query)
    await update.message.reply_text(report_text,
                                    parse_mode=ParseMode.MARKDOWN_V2)


async def sprint_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    observe_command("sprint")
    chat_id = update.effective_chat.id
    current_sprint = get_sprint_for_chat(chat_id)

    if current_sprint and current_sprint["is_active"] == 1:
        await update.message.reply_text(
            "Уже запущен спринт в этом чате! "
            "Можете завершить или дождаться дедлайна."
        )
        return

    sprint_id = create_sprint(chat_id)

    await update.message.reply_text(
        f"В этом чате подготовлен спринт (ID={sprint_id})\n"
        "Укажите дедлайн командой /set_sprint_deadline 2025-05-20 18:00 "
        "или сразу /startsprint 2025-05-20 18:00"
    )


async def set_sprint_deadline_handler(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    observe_command("set_sprint_deadline")
    chat_id = update.effective_chat.id
    current_sprint = get_sprint_for_chat(chat_id)
    if not current_sprint:
        await update.message.reply_text(
            "Сначала создайте спринт командой /sprint")
        return

    text = update.message.text.split(maxsplit=1)
    if len(text) < 2:
        await update.message.reply_text(
            "Укажите дату в формате YYYY-MM-DD HH:MM")
        return

    try:
        deadline = datetime.strptime(text[1], "%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text(
            "Неверный формат даты. Пример: 2025-05-20 18:00")
        return

    set_sprint_deadline(current_sprint["id"], deadline)
    await update.message.reply_text(
        f"Дедлайн спринта установлен: {deadline}")


async def startsprint_command_handler(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    observe_command("startsprint")
    chat_id = update.effective_chat.id
    current_sprint = get_sprint_for_chat(chat_id)
    if not current_sprint:
        await update.message.reply_text(
            "Сначала создайте спринт командой /sprint")
        return

    text = update.message.text.split(maxsplit=1)
    deadline = None
    if len(text) > 1:
        try:
            deadline = datetime.strptime(text[1], "%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text(
                "Неверный формат даты. Пример: 2025-05-20 18:00")
            return
    elif not current_sprint["deadline"]:
        await update.message.reply_text(
            "Сначала задайте дедлайн командой /set_sprint_deadline")
        return

    start_sprint(current_sprint["id"], deadline)
    dl = deadline or current_sprint["deadline"]
    await update.message.reply_text(
        f"Спринт запущен! Дедлайн: {dl}")


async def check_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    observe_command("check")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    sprint = get_sprint_for_chat(chat_id)
    if not sprint:
        await update.message.reply_text(
            "Спринт в этом чате не создан.")
        return

    if (sprint["is_active"]
            and sprint["deadline"]
            and sprint["deadline"] <= datetime.now()):
        bitrix_url = await get_url_by_type(chat_id, chat_type, context)
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
        await update.message.reply_text(summary + ("\n" + report if report else ""))
        finish_sprint(sprint["id"])
        return

    task_ids = get_sprint_tasks(sprint["id"])
    if not task_ids:
        await update.message.reply_text("В спринте нет задач.")
        return

    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
    if not bitrix_url:
        await update.message.reply_text("Не найден Bitrix URL для этого чата.")
        return

    lines = []
    completed = 0
    for t_id in task_ids:
        fields = get_task_fields_from_bitrix(bitrix_url, t_id)
        title = fields.get("TITLE") or fields.get("title") or "Без названия"
        status = fields.get("REAL_STATUS")
        closed = fields.get("CLOSED_DATE")
        is_done = bool(closed) or (status and int(status) >= 5)
        if is_done:
            completed += 1
        lines.append(f"{t_id}: {title} - {'✅' if is_done else '❌'}")

    percent = int(completed / len(task_ids) * 100)
    if sprint["deadline"]:
        remaining = sprint["deadline"] - datetime.now()
        remaining_str = str(remaining).split(".")[0]
    else:
        remaining_str = "-"

    if sprint["is_active"]:
        status_line = f"До дедлайна: {remaining_str}"
    else:
        status_line = "Спринт ещё не запущен."

    header = (f"Всего задач: {len(task_ids)}, выполнено: {completed} "
              f"({percent}%). {status_line}")
    report = "\n".join(lines)
    await update.message.reply_text(header + "\n" + report)


async def endsprint_command_handler(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    observe_command("endsprint")
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    sprint = get_sprint_for_chat(chat_id)
    if not sprint or sprint["is_active"] == 0:
        await update.message.reply_text(
            "Нет активного спринта в этом чате.")
        return

    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
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
    await update.message.reply_text(summary + ("\n" + report if report else ""))
    finish_sprint(sprint["id"])
