from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from openai_service import parse_message_with_openai
from bitrix_service import (create_task_in_bitrix, get_user_id_from_webhook,
                            get_overdue_tasks_report, get_my_projects,
                            get_completed_tasks_report,
                            get_user_name_from_bitrix,
                            get_tasks_filtered_report)
from db import (add_user, set_url, get_url, get_user, set_user_bitrix_id,
                get_bitrix_id_for_user, set_user_chat_id, set_main_chat_id)
import logging

from tinkoff_service import transcribe_wav_tinkoff
from utils import (extract_mention_username, get_url_by_type,
                   get_uinfo_from_admins)
from datetime import datetime, timedelta
import asyncio

from pydub import AudioSegment
import os
import uuid


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.debug("start_handler called")
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
    voice = update.message.voice
    if voice:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        ogg_path = f"temp_{uuid.uuid4().hex}.ogg"
        await file.download_to_drive(ogg_path)
        wav_path = f"temp_{uuid.uuid4().hex}.wav"
        AudioSegment.from_ogg(ogg_path).export(wav_path, format="wav")
        try:
            recognized_text = transcribe_wav_tinkoff(wav_path)
            if recognized_text.strip():
                text = recognized_text.strip()
                if 'задача' not in text:
                    return
            else:
                await update.message.reply_text(
                    "Не удалось распознать голосовое сообщение.")
        except Exception as e:
            logging.exception("Ошибка распознавания через Tinkoff: %s", e)
            await update.message.reply_text(
                "Ошибка при распознавании голосового сообщения.")
            return
        finally:
            if os.path.exists(ogg_path):
                os.remove(ogg_path)
            if os.path.exists(wav_path):
                os.remove(wav_path)
    else:
        text = update.message.text
        if '#задача' not in text:
            return

    chat_id = update.effective_chat.id

    url, notification_group_id = await get_uinfo_from_admins(chat_id, context)
    if not url:
        await update.message.reply_text("Не задан URL")
        return

    projects = get_my_projects(url)
    project_names = [project.get("NAME") for project in projects if
                     project.get("NAME")]
    parsed = parse_message_with_openai(text, available_projects=project_names)

    title = parsed.get("title", "Без названия")
    deadline = parsed.get("deadline", "")
    description = parsed.get("description", "")
    checklist = parsed.get("checklist", [])

    project_name = parsed.get("project", "").strip()
    group_id = None
    if project_name and projects:
        for proj in projects:
            if proj.get("NAME", "").lower() == project_name.lower():
                group_id = proj.get("ID")
                break

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
            bitrix_executors.append(get_user_name_from_bitrix(url, b_id))

    if bitrix_executors:
        responsible_id = bitrix_executors[0]
    else:
        responsible_id = get_user_name_from_bitrix(
            url,
            get_user_id_from_webhook(url)
        )

    accomplices = bitrix_executors[1:] if len(bitrix_executors) > 1 else []
    if not url:
        await update.message.reply_text("Не задан URL")
        return

    result = create_task_in_bitrix(url, title, description, deadline,
                                   responsible_id, checklist, accomplices,
                                   group_id)
    if result:
        await update.message.reply_text(
            f"Задача поставлена!"
        )
        task_id = result['result']['task']['id']
    else:
        task_id = 0

    if notification_group_id:
        title_escaped = escape_markdown(title, version=2)
        description_escaped = escape_markdown(description, version=2)
        deadline_escaped = escape_markdown(deadline, version=2)
        project_name_escaped = escape_markdown(project_name, version=2)
        responsible_id_escaped = escape_markdown(str(responsible_id),
                                                 version=2)
        accomplices_escaped = [escape_markdown(str(a), version=2) for a in
                               accomplices]
        checklist_escaped = [escape_markdown(item, version=2) for item in
                             checklist]

        keyboard = [
            [
                InlineKeyboardButton(
                    text="Изменить задачу (WIP ⚒️)",
                    callback_data=f"edit_task:{task_id}"
                )
            ]
        ]
        # reply_markup = InlineKeyboardMarkup(keyboard)

        lines = [f"*Задача создана:* {title_escaped}"]
        if description_escaped:
            lines.append(f"*Описание:* {description_escaped}")
        if deadline_escaped:
            lines.append(f"*Дедлайн:* {deadline_escaped}")
        if project_name_escaped:
            lines.append(f"*Проект:* {project_name_escaped}")
        if responsible_id_escaped:
            lines.append(f"*Ответственный:* {responsible_id_escaped}")
        if accomplices_escaped:
            lines.append(
                f"*Соисполнители:* {', '.join(accomplices_escaped)}")
        if checklist_escaped:
            lines.append(f"*Чеклист:* {', '.join(checklist_escaped)}")
        task_details = "\n".join(lines)

        try:
            await context.bot.send_message(
                notification_group_id,
                task_details,
                parse_mode=ParseMode.MARKDOWN_V2,
                # reply_markup=reply_markup
            )

        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в группу: {e}")
            await update.message.reply_text(
                f"Ошибка при отправке информации в группу.")


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


async def notifications_command_handler(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username or
                telegram_user.first_name or telegram_id)

    user_row = get_user(telegram_id)
    if not user_row:
        add_user(telegram_id, username)

    try:
        set_user_chat_id(telegram_id,
                         chat_id)

        await update.message.reply_text(
            f"Ваш ID беседы (chat_id) сохранён: {chat_id}. "
            f"Теперь я буду писать уведомления в этой беседе."
        )
    except Exception as e:
        logging.error(
            f"Ошибка при сохранении chat_id для пользователя {telegram_id}: "
            f"{e}")
        await update.message.reply_text(
            "Ошибка при сохранении ID беседы. Попробуйте позже."
        )


async def delay_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного "
                                        "Bitrix URL для этой беседы.")
        return
    report_text = get_overdue_tasks_report(bitrix_url)
    await update.message.reply_text(report_text, parse_mode="Markdown")


async def main_command_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    telegram_user: User = update.effective_user
    telegram_id = telegram_user.id
    chat_id = update.effective_chat.id

    user_row = get_user(telegram_id)
    if not user_row:
        username = (telegram_user.username or telegram_user.first_name or
                    str(telegram_id))
        add_user(telegram_id, username)

    try:
        set_main_chat_id(telegram_id, chat_id)
        await update.message.reply_text(
            f"Основная беседа установлена. (main_chat_id = {chat_id})"
        )
    except Exception as e:
        logging.error(f"Ошибка при установке main_chat_id для пользователя "
                      f"{telegram_id}: {e}")
        await update.message.reply_text(
            "Ошибка при сохранении основной беседы. Попробуйте позже."
        )


async def report_command_handler(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного "
                                        "Bitrix URL для этой беседы.")
        return
    now = datetime.now()
    one_week_ago = now - timedelta(days=7)

    start_date = one_week_ago.strftime("%Y-%m-%dT%H:%M:%S+03:00")
    end_date = now.strftime("%Y-%m-%dT%H:%M:%S+03:00")

    report_text = await asyncio.to_thread(get_completed_tasks_report,
                                          bitrix_url, start_date, end_date)

    await update.message.reply_text(report_text)


async def tasks_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного "
                                        "Bitrix URL для этой беседы.")
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


# async def edit_task_callback(update: Update,
# context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#
#     data = query.data  # например, "edit_task:123"
#     command, task_id_str = data.split(":", 1)
#     task_id = int(task_id_str)
#
#
#     # Простейший вариант: сразу отправить форму/сообщение с вопросом
#     await query.message.reply_text(
#         text=f"Вы выбрали редактировать задачу {task_id}.
#         Какое поле хотите изменить?",
#     )
#     # Дальше - либо новая инлайн-клавиатура, либо переход в режим диалога
#     # (ожидание ответа пользователя, сохранение в ConversationHandler и т.д.)
