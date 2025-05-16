from telegram import (
    Update, User, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram import Message as TelegramMessage
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from openai_service import parse_message_with_openai
from bitrix_service import (
    create_task_in_bitrix,
    get_user_id_from_webhook,
    get_overdue_tasks_report,
    get_my_projects,
    get_completed_tasks_report,
    get_user_name_from_bitrix,
    get_tasks_filtered_report,
    update_task_in_bitrix
)
from db import (
    add_user,
    set_url,
    get_url,
    get_user,
    set_user_bitrix_id,
    get_bitrix_id_for_user,
    set_user_chat_id,
    set_main_chat_id
)
import logging
import asyncio
from datetime import datetime, timedelta
import os
import uuid

from pydub import AudioSegment
from tinkoff_service import transcribe_wav_tinkoff
from utils import (
    extract_mention_username,
    get_url_by_type,
    get_uinfo_from_admins
)


#############################
#  Команды и обработчики #
#############################

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
            "Произошла ошибка при доступе к БД. Попробуйте позже."
        )


async def text_message_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
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
        task_id = result['result']['task']['id']
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
            await context.bot.send_message(
                notification_group_id,
                task_details,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения в группу: {e}")
            await update.message.reply_text(
                "Ошибка при отправке информации в группу."
            )


async def info_command_handler(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username
                or telegram_user.first_name or telegram_id)
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


async def url_command_handler(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.split(None, 1)
    telegram_id = update.effective_user.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username
                or telegram_user.first_name or telegram_id)

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
    username = (telegram_user.username
                or telegram_user.first_name or telegram_id)

    if len(message_text) < 2:
        await update.message.reply_text("Использование: /bitrixid <числовой "
                                        "ID>")
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


async def notifications_command_handler(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id
    telegram_user: User = update.effective_user
    username = (telegram_user.username
                or telegram_user.first_name or telegram_id)

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


async def delay_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL для "
                                        "этой беседы.")
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
        username = (telegram_user.username
                    or telegram_user.first_name or str(telegram_id))
        add_user(telegram_id, username)

    try:
        set_main_chat_id(telegram_id, chat_id)
        await update.message.reply_text(f"Основная беседа установлена. ("
                                        f"main_chat_id = {chat_id})")
    except Exception as e:
        logging.error(f"Ошибка при установке main_chat_id для {telegram_id}:"
                      f" {e}")
        await update.message.reply_text("Ошибка при сохранении основной "
                                        "беседы. Попробуйте позже.")


async def report_command_handler(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
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


async def tasks_command_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
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


#############################
#    Редактирование задач #
#############################

CHOOSING_FIELD, WAITING_VALUE = range(2)


async def edit_task_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 1. Change task
    """
    query = update.callback_query
    await query.answer()

    data = query.data  # "edit_task:123"
    _, task_id_str = data.split(":", 1)
    task_id = int(task_id_str)

    context.user_data["edit_task_id"] = task_id

    keyboard = [
        [
            InlineKeyboardButton("Название", callback_data=f"edit_field:"
                                                           f"{task_id}:"
                                                           f"title"),
            InlineKeyboardButton("Дедлайн", callback_data=f"edit_field:"
                                                          f"{task_id}:"
                                                          f"deadline")
        ],
        [
            InlineKeyboardButton("Описание", callback_data=f"edit_field:"
                                                           f"{task_id}:"
                                                           f"description")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query.message and isinstance(query.message, TelegramMessage):
        await query.message.reply_text(
            text=f"Вы выбрали редактировать задачу *{task_id}*.\nКакое поле "
                 f"хотите изменить?",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Вы выбрали редактировать задачу *{task_id}*.\nКакое поле "
                 f"хотите изменить?",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    # await query.edit_message_text(
    #     text=f"Вы выбрали редактировать задачу *{task_id}*.\nКакое поле "
    #          f"хотите изменить?",
    #     parse_mode="Markdown",
    #     reply_markup=reply_markup
    # )
    return CHOOSING_FIELD


async def edit_field_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 2. (title/description/deadline) chosen
    """
    query = update.callback_query
    await query.answer()

    data = query.data  # "edit_field:123:deadline"
    _, task_id_str, field_name = data.split(":", 2)
    task_id = int(task_id_str)

    context.user_data["edit_task_id"] = task_id
    context.user_data["edit_field_name"] = field_name

    field_labels = {
        "title": "Введите новое название задачи:",
        "description": "Введите новое описание задачи:",
        "deadline": "Введите новый дедлайн (формат YYYY-MM-DD HH:MM:SS):"
    }
    prompt = field_labels.get(field_name, "Введите новое значение:")

    # if query.message:
    #     await query.message.reply_text(prompt)
    # else:
    #     await context.bot.send_message(
    #         chat_id=update.effective_chat.id,
    #         text=prompt
    #     )

    await query.edit_message_text(prompt)
    return WAITING_VALUE


async def edit_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 3. Update task
    """
    text = update.message.text.strip()
    task_id = context.user_data.get("edit_task_id")
    field_name = context.user_data.get("edit_field_name")

    if not task_id or not field_name:
        await update.message.reply_text("Неизвестная задача или поле. "
                                        "Попробуйте заново.")
        return ConversationHandler.END

    update_kwargs = {"task_id": task_id}

    if field_name == "title":
        update_kwargs["title"] = text
    elif field_name == "description":
        update_kwargs["description"] = text
    elif field_name == "deadline":
        update_kwargs["deadline"] = text
    else:
        logging.warning(f"Unknown field '{field_name}'")
        await update.message.reply_text("Неизвестное поле. Попробуйте заново.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)

    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL для "
                                        "редактирования.")
        return ConversationHandler.END

    result = update_task_in_bitrix(bitrix_url, **update_kwargs)
    if result:
        await update.message.reply_text("Задача успешно обновлена!")
    else:
        await update.message.reply_text("Ошибка при обновлении задачи.")

    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /cancel для выхода из редактирования (fallback).
    """
    await update.message.reply_text("Редактирование отменено.")
    return ConversationHandler.END


edit_task_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(edit_task_callback, pattern=r"^edit_task:\d+")
    ],
    states={
        CHOOSING_FIELD: [
            CallbackQueryHandler(edit_field_callback, pattern=r"^edit_field"
                                                              r":\d+:.+")
        ],
        WAITING_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_value)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_edit)
    ]
)
