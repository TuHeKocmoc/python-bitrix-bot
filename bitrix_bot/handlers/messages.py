from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Message as TelegramMessage
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
import logging
import asyncio
import os
import uuid
from pydub import AudioSegment

from ..services.openai_service import parse_message_with_openai
from ..services.bitrix_service import (
    create_task_in_bitrix,
    get_user_id_from_webhook,
    get_my_projects,
    get_user_name_from_bitrix,
)
from ..services.tinkoff_service import transcribe_wav_tinkoff
from ..db import get_bitrix_id_for_user
from ..utils import extract_mention_username, get_uinfo_from_admins


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.effective_chat.type
    if chat_type not in ["group", "supergroup"]:
        return

    voice = update.message.voice
    if voice:
        file = await context.bot.get_file(voice.file_id)
        ogg_path = f"temp_{uuid.uuid4().hex}.ogg"
        await file.download_to_drive(ogg_path)
        wav_path = f"temp_{uuid.uuid4().hex}.wav"
        audio = AudioSegment.from_file(ogg_path, format="ogg")
        audio = audio.set_frame_rate(16000).set_sample_width(2).set_channels(1)
        audio.export(wav_path, format="wav")

        try:
            recognized_text = transcribe_wav_tinkoff(wav_path)
            logging.debug(f"Распознанный текст: {recognized_text}")
            if recognized_text.strip():
                text = recognized_text.strip().lower()
                if 'задача' not in text:
                    return
            else:
                await update.message.reply_text(
                    "Не удалось распознать голосовое сообщение."
                )
                return
        except Exception as e:
            logging.exception("Ошибка распознавания через Tinkoff: %s", e)
            await update.message.reply_text(
                "Ошибка при распознавании голосового сообщения."
            )
            return
        finally:
            if os.path.exists(ogg_path):
                os.remove(ogg_path)
            if os.path.exists(wav_path):
                os.remove(wav_path)
    else:
        text = update.message.text
        if '#задача' not in text.lower():
            return

    chat_id = update.effective_chat.id

    url, notification_group_id = await get_uinfo_from_admins(chat_id, context)
    if not url:
        await update.message.reply_text("Не задан URL")
        return

    projects = get_my_projects(url)
    project_names = [p.get("NAME") for p in projects if p.get("NAME")]
    parsed = await asyncio.to_thread(
        parse_message_with_openai,
        text,
        available_projects=project_names
    )

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

    mention_user = extract_mention_username(update.message)
    reply_user_obj = update.message.reply_to_message.from_user \
        if update.message.reply_to_message else None
    reply_user = reply_user_obj.username \
        if reply_user_obj and reply_user_obj.username else None

    executors = []
    if mention_user and reply_user:
        executors = [mention_user, reply_user]
    elif mention_user:
        executors = [mention_user]
    elif reply_user:
        executors = [reply_user]

    logging.debug(f"[TASK PARSING] mention_user={mention_user}, "
                  f"reply_user={reply_user}")
    logging.debug(f"[TASK PARSING] executors={executors}")

    bitrix_executors = []
    for exec_username in executors:
        b_id = get_bitrix_id_for_user(exec_username)
        logging.debug(f"[TASK PARSING] Checking user '{exec_username}' => "
                      f"bitrix_id={b_id}")
        if not b_id:
            logging.info(f"Не найден bitrix_id для user {exec_username}, "
                         f"fallback на админа")
        else:
            bitrix_executors.append(b_id)

    if bitrix_executors:
        responsible_id = bitrix_executors[0]
        accomplices = bitrix_executors[1:] if len(bitrix_executors) > 1 else []
        logging.debug(f"[TASK PARSING] Responsible ID (bitrix_executors[0]) = "
                      f"{responsible_id}")
    else:
        fallback_id = get_user_id_from_webhook(url)
        logging.debug(f"[TASK PARSING] Fallback admin ID => {fallback_id}")
        responsible_id = fallback_id
        accomplices = []

    result = create_task_in_bitrix(
        webhook=url,
        title=title,
        description=description,
        deadline=deadline,
        responsible=responsible_id,
        checklist=checklist,
        accomplices=accomplices,
        group_id=group_id
    )
    if result:
        await update.message.reply_text("Задача поставлена!")
        task_id = int(result['result']['task']['id'])
    else:
        task_id = 0

    if notification_group_id and task_id:
        title_escaped = escape_markdown(title, version=2)
        description_escaped = escape_markdown(description, version=2)
        deadline_escaped = escape_markdown(deadline, version=2)
        project_name_escaped = escape_markdown(project_name, version=2)

        accomplices_names = []
        for ac_id in accomplices:
            name_in_bitrix = (get_user_name_from_bitrix(url, ac_id)
                              or f"ID {ac_id}")
            accomplices_names.append(name_in_bitrix)

        responsible_name = (get_user_name_from_bitrix(url, responsible_id)
                            or f"ID {responsible_id}")
        responsible_id_escaped = escape_markdown(str(responsible_name),
                                                 version=2)
        accomplices_escaped = [escape_markdown(str(a), version=2)
                               for a in accomplices_names]

        checklist_escaped = [escape_markdown(item, version=2)
                             for item in checklist]
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
            lines.append(f"*Соисполнители:* {', '.join(accomplices_escaped)}")
        if checklist_escaped:
            lines.append(f"*Чеклист:* {', '.join(checklist_escaped)}")

        keyboard = [
            [
                InlineKeyboardButton(
                    text="Изменить задачу ",
                    callback_data=f"edit_task:{task_id}"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        task_details = "\n".join(lines)
        try:
            sent_msg = await context.bot.send_message(
                notification_group_id,
                task_details,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
            context.user_data.setdefault("created_tasks", {})
            context.user_data["created_tasks"][task_id] = {
                "chat_id": notification_group_id,
                "message_id": sent_msg.message_id
            }
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в группу: {e}")
            await update.message.reply_text(
                "Ошибка при отправке информации в группу."
            )

