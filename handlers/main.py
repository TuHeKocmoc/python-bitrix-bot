from telegram import Update, User
from telegram.ext import ContextTypes

from openai_service import parse_message_with_openai
from bitrix_service import create_task_in_bitrix, get_user_id_from_webhook
from db import (add_user, set_url, get_url, get_user, set_user_bitrix_id,
                get_bitrix_id_for_user)
import logging
from utils import extract_mention_username, get_bitrix_url_from_admins


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("start_handler called")
    telegram_user: User = update.effective_user
    telegram_id = telegram_user.id
    username = (telegram_user.username or telegram_user.first_name or
                telegram_id)
    try:
        row = get_url(telegram_id)
        if row:
            bitrix_url = row[0]
            if bitrix_url:
                await update.message.reply_text(
                    f"Привет, {username}! Вы уже зарегистрированы. "
                    f"/info — чтобы увидеть инфо."
                )
            else:
                await update.message.reply_text(
                    f"Привет, {username}! /url -- задать Bitrix Webhook, "
                    f"/bitrixid -- задать свой ID в системе"
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
            "Произошла ошибка при доступе к БД. Попробуйте позже.")


async def text_message_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.effective_chat.type
    if chat_type not in ["group", "supergroup"]:
        return
    text = update.message.text
    chat_id = update.effective_chat.id

    parsed = parse_message_with_openai(text)

    if parsed.get("is_task"):
        title = parsed.get("title", "Без названия")
        deadline = parsed.get("deadline", "")
        description = parsed.get("description", "")
        checklist = parsed.get("checklist", [])

        reply_user = None
        mention_user = extract_mention_username(
            update.message)
        if update.message.reply_to_message:
            reply_user_obj = update.message.reply_to_message.from_user
            if reply_user_obj.username:
                reply_user = reply_user_obj.username

        executors = []
        if mention_user and reply_user:
            executors = [mention_user, reply_user]
        elif mention_user:
            executors = [mention_user]
        elif reply_user:
            executors = [reply_user]

        bitrix_executors = []
        for exec_username in executors:
            b_id = get_bitrix_id_for_user(exec_username)
            if not b_id:
                logging.info(
                    f"Не найден bitrix_id для user {exec_username}, "
                    f"fallback на админа")
            if b_id:
                bitrix_executors.append(b_id)

        url = await get_bitrix_url_from_admins(chat_id, context)
        if not url:
            await update.message.reply_text("Не задан URL")
            return

        responsible_id = bitrix_executors[0] \
            if bitrix_executors else get_user_id_from_webhook(url)
        accomplices = bitrix_executors[1:] if len(bitrix_executors) > 1 else []
        if not url:
            await update.message.reply_text("Не задан URL")
            return

        result = create_task_in_bitrix(url, title, description, deadline,
                                       responsible_id, checklist, accomplices)
        if result:
            await update.message.reply_text(
                f"👍"
            )


async def info_command_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or
                telegram_id)
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
        await update.message.reply_text("Произошла ошибка "
                                        "при получении информации.")


async def url_command_handler(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.split(None, 1)
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or
                telegram_id)

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


async def bitrixid_command_handler(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.split(None, 1)
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or telegram_user.first_name or
                telegram_id)

    if len(message_text) < 2:
        await update.message.reply_text("Использование: "
                                        "/bitrixid <числовой ID>")
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
        await update.message.reply_text("Ошибка при сохранении. "
                                        "Попробуйте позже.")
