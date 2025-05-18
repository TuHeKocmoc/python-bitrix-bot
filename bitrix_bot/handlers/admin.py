from telegram import Update
from telegram.ext import ContextTypes
from ..config import ADMIN_IDS
from ..db import enable_user, disable_user, get_user_by_username
from ..metrics import observe_command
import logging


async def admin_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для этой команды.")
        return

    msg_parts = update.message.text.strip().split()
    command = msg_parts[0]
    observe_command(command.lstrip('/'))
    if len(msg_parts) < 2:
        await update.message.reply_text("Укажите chat_id. "
                                        "Пример: /enable -100123456789")
        return

    chat_id = msg_parts[1]
    if command == "/enable":
        enable_user(chat_id)
        await update.message.reply_text(f"Пользователь "
                                        f"{chat_id} активирован.")
    elif command == "/disable":
        disable_user(chat_id)
        await update.message.reply_text(f"Пользователь "
                                        f"{chat_id} деактивирован.")
    else:
        await update.message.reply_text("Неизвестная админ-команда.")


async def ainfo_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id  # telegram_id инициатора
    message_text = update.message.text.split()
    observe_command("ainfo")

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав на эту команду.")
        return

    if len(message_text) < 2:
        await update.message.reply_text("Использование: /ainfo <username>")
        return

    target_username = message_text[1].strip()

    try:
        row = get_user_by_username(target_username)

        if not row:
            await update.message.reply_text(f"Пользователь "
                                            f"'{target_username}' не найден.")
            return

        telegram_id_db = row[1]
        is_enabled = row[2]
        bitrix_url = row[3] or "—"
        bitrix_id = row[4] or "—"

        info_text = (f"**Информация о пользователе '{target_username}'**\n"
                     f"• Telegram ID: {telegram_id_db}\n"
                     f"• Включён ли: {bool(is_enabled)}\n"
                     f"• Bitrix URL: {bitrix_url}\n"
                     f"• Bitrix ID: {bitrix_id}\n")

        await update.message.reply_text(info_text, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Ошибка в /ainfo: {e}")
        await update.message.reply_text("Произошла ошибка "
                                        "при получении информации.")
