from telegram import (
    Update, User, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram import Message as TelegramMessage
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    CommandHandler, MessageHandler, filters
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

from openai_service import parse_message_with_openai
from bitrix_service import (
    create_task_in_bitrix, get_user_id_from_webhook, get_overdue_tasks_report,
    get_my_projects, get_completed_tasks_report, get_user_name_from_bitrix,
    get_tasks_filtered_report, update_task_in_bitrix,
    get_task_fields_from_bitrix, get_project_id_by_name,
    get_project_name_by_id, add_checklist_item, delete_checklist_item,
    get_checklist_items
)
from db import (
    add_user, set_url, get_url, get_user, set_user_bitrix_id,
    get_bitrix_id_for_user, set_user_chat_id, set_main_chat_id
)
import logging
import asyncio
from datetime import datetime, timedelta
import os
import uuid

from pydub import AudioSegment
from tinkoff_service import transcribe_wav_tinkoff
from utils import (
    extract_mention_username, get_url_by_type, get_uinfo_from_admins
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
CHECKLIST_MENU = 3
CHECKLIST_ADD = 4
CHECKLIST_DEL = 5


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
            InlineKeyboardButton("Название",
                                 callback_data=f"edit_field:{task_id}:title"),
            InlineKeyboardButton("Дедлайн",
                                 callback_data=f"edit_field:{task_id}:deadline"
                                 ),
        ],
        [
            InlineKeyboardButton(
                "Описание",
                callback_data=f"edit_field:{task_id}:description"
            ),
            InlineKeyboardButton("Проект",
                                 callback_data=f"edit_field:{task_id}:project"
                                 ),
        ],
        [
            InlineKeyboardButton("Отмена", callback_data="cancel_edit"),
            InlineKeyboardButton("Чеклист",
                                 callback_data=f"edit_checklist:{task_id}")
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
        "deadline": "Введите новый дедлайн (формат YYYY-MM-DD HH:MM:SS):",
        "project": "Введите название проекта:",
    }
    prompt = field_labels.get(field_name, "Введите новое значение:")

    keyboard = [
        [
            InlineKeyboardButton("Отмена", callback_data="cancel_edit")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent_msg = await query.edit_message_text(
        text=prompt,
        reply_markup=reply_markup
    )
    context.user_data["edit_chat_id"] = sent_msg.chat_id
    context.user_data["edit_message_id"] = sent_msg.message_id

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
    elif field_name == "project":
        bitrix_url_for_search = await get_url_by_type(
            update.effective_chat.id,
            update.effective_chat.type,
            context
        )
        if bitrix_url_for_search:
            group_id = get_project_id_by_name(bitrix_url_for_search, text)
            if group_id == -1:
                await update.message.reply_text(
                    "Проект с таким названием не найден. Попробуйте ещё раз."
                )
                return ConversationHandler.END
            update_kwargs["group_id"] = group_id
        else:
            await update.message.reply_text("Нет настроенного Bitrix URL.")
            return ConversationHandler.END
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
    old_chat_id = context.user_data.get("edit_chat_id")
    old_message_id = context.user_data.get("edit_message_id")

    if result:
        await context.bot.edit_message_text(
            chat_id=old_chat_id,
            message_id=old_message_id,
            text="Задача успешно обновлена!"
        )
    else:
        await context.bot.edit_message_text(
            chat_id=old_chat_id,
            message_id=old_message_id,
            text="Ошибка при обновлении задачи."
        )

    task_entry = context.user_data.get("created_tasks", {}).get(task_id)
    logging.debug(f"task_entry={task_entry}, "
                  f"created_tasks={context.user_data.get('created_tasks')}")
    if task_entry:
        original_chat_id = task_entry["chat_id"]
        original_msg_id = task_entry["message_id"]

        updated_fields = get_task_fields_from_bitrix(bitrix_url, task_id)
        logging.debug(f"updated_fields={updated_fields}")

        if updated_fields:
            new_title = updated_fields.get("title", "Без названия")
            new_description = updated_fields.get("description", "")
            new_deadline = updated_fields.get("deadline", "")
            new_responsible_id_str = updated_fields.get("responsibleId", "")
            new_accomplices = updated_fields.get("accomplices", [])
            new_group_id = updated_fields.get("groupId", 0)
            # checklist

            try:
                new_responsible_id = int(new_responsible_id_str)
            except ValueError:
                logging.warning(
                    f"RESPONSIBLE_ID is '{new_responsible_id_str}', can't "
                    f"parse.")
                new_responsible_id = 0
            new_responsible_name = get_user_name_from_bitrix(
                bitrix_url, new_responsible_id) or f"ID {new_responsible_id}"

            if new_deadline is None:
                new_deadline = ""
            else:
                dt = datetime.fromisoformat(new_deadline)
                new_deadline = dt.strftime("%d/%m/%Y %H:%M")

            project_name = ""
            if new_group_id:
                project_name = get_project_name_by_id(bitrix_url, new_group_id)
                if project_name == "-1":
                    project_name = ""

            accomplices_names = []
            for ac_id in new_accomplices:
                ac_name = get_user_name_from_bitrix(bitrix_url, ac_id)
                if ac_name:
                    accomplices_names.append(ac_name)
                else:
                    accomplices_names.append(f"ID {ac_id}")

            updated_checklist = get_checklist_items(bitrix_url, task_id)
            checklist_lines = []
            filtered_list = [
                x for x in updated_checklist
                if x.get("TITLE",
                         "").lower().replace("_",
                                             "").strip() != "bxchecklist1"
            ]
            if filtered_list:
                for i, item in enumerate(filtered_list, start=1):
                    t = item.get("TITLE", "Без названия")
                    complete = item.get("IS_COMPLETE", "N")
                    prefix = "✅" if complete == "Y" else "⬜"
                    checklist_lines.append(f"{i}. {prefix} {t}")
            else:
                checklist_lines = []

            new_lines = [
                f"*Задача обновлена:* {escape_markdown(new_title, version=2)}"
            ]

            description_escaped = escape_markdown(new_description, version=2)
            deadline_escaped = escape_markdown(new_deadline or "", version=2)
            project_name_escaped = escape_markdown(project_name, version=2)

            if description_escaped:
                new_lines.append(f"*Описание:* {description_escaped}")
            if deadline_escaped:
                new_lines.append(f"*Дедлайн:* {deadline_escaped}")
            if project_name_escaped:
                new_lines.append(f"*Проект:* {project_name_escaped}")
            responsible_name_escaped = escape_markdown(new_responsible_name,
                                                       version=2)
            new_lines.append(f"*Ответственный:* {responsible_name_escaped}")
            if accomplices_names:
                joined_accomplices = ", ".join(escape_markdown(a, version=2)
                                               for a in accomplices_names)
                new_lines.append(f"*Соисполнители:* {joined_accomplices}")

            if checklist_lines:
                escaped_lines = [escape_markdown(x, version=2) for x in
                                 checklist_lines]
                checklist_str = "\n".join(escaped_lines)
                new_lines.append(f"*Чек\\-лист:*\n{checklist_str}")

            updated_text = "\n".join(new_lines)

            keyboard = [
                [InlineKeyboardButton("Изменить задачу",
                                      callback_data=f"edit_task:{task_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            logging.debug(f"Final updated_text: {repr(updated_text)}")

            await context.bot.edit_message_text(
                chat_id=original_chat_id,
                message_id=original_msg_id,
                text=updated_text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup
            )
        else:
            logging.warning(
                f"Не удалось получить updated_fields для задачи {task_id}")
    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /cancel для выхода из редактирования (fallback).
    """
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Редактирование отменено.")

    else:
        await update.message.reply_text("Редактирование отменено.")

    return ConversationHandler.END


async def edit_checklist_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # "edit_checklist:123"
    _, task_id_str = data.split(":", 1)
    task_id = int(task_id_str)

    context.user_data["edit_task_id"] = task_id

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
    if not bitrix_url:
        if query.message and isinstance(query.message, TelegramMessage):
            await query.message.reply_text("Нет настроенного Bitrix URL.")
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Нет настроенного Bitrix URL."
            )
        return ConversationHandler.END

    check_list = get_checklist_items(bitrix_url, task_id)
    # [{"ID": "12345", "TITLE": "Пункт", "IS_COMPLETE": "N"}, ...]

    text_lines = ["**Текущий чек-лист:**"]
    if check_list:
        filtered_check_list = [
            x for x in check_list
            if x.get("TITLE",
                     "").strip().lower().replace("_", "") != "bxchecklist1"
        ]

        for i, item in enumerate(filtered_check_list, start=1):
            title = item.get("TITLE", "Без названия").strip()
            logging.debug(f"CheckList item title: {repr(title)}")
            if title.lower() == "bxchecklist1":
                continue
            cleaned_title = title.lower().replace("_", "").strip()
            if cleaned_title == "bxchecklist1":
                continue
            is_complete = item.get("IS_COMPLETE", "N")
            status_emoji = "✅" if is_complete == "Y" else "⬜"
            text_lines.append(f"{i}. {status_emoji} {title}")
    else:
        text_lines.append("_(пусто)_")

    keyboard = [
        [
            InlineKeyboardButton("Добавить пункт",
                                 callback_data="checklist_add"),
            InlineKeyboardButton("Удалить пункт",
                                 callback_data="checklist_del")
        ],
        [
            InlineKeyboardButton("Отмена", callback_data="cancel_edit")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="\n".join(text_lines),
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return CHECKLIST_MENU


async def checklist_add_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Переходим в режим добавления пункта: ждём ввод текста."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        text="Введите текст нового пункта (сообщением)."
    )
    return CHECKLIST_ADD


async def checklist_add_text(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Новый пункт, добавляем через Bitrix API."""
    new_item_title = update.message.text.strip()
    task_id = context.user_data.get("edit_task_id")
    if not task_id:
        await update.message.reply_text("Неизвестная задача. Попробуйте "
                                        "заново.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
    if not bitrix_url:
        await update.message.reply_text("Нет настроенного Bitrix URL.")
        return ConversationHandler.END

    add_ok = add_checklist_item(bitrix_url, task_id, new_item_title)

    if add_ok:
        await update.message.reply_text("Пункт добавлен в чек-лист.")
    else:
        await update.message.reply_text("Ошибка при добавлении пункта.")

    task_entry = context.user_data.get("created_tasks", {}).get(task_id)
    if task_entry:
        original_chat_id = task_entry["chat_id"]
        original_msg_id = task_entry["message_id"]

        updated_fields = get_task_fields_from_bitrix(bitrix_url, task_id)

        if updated_fields:
            new_title = updated_fields.get("title", "Без названия")
            new_description = updated_fields.get("description", "")
            new_deadline_iso = updated_fields.get("deadline", "")
            new_responsible_id_str = updated_fields.get("responsibleId", "")
            new_group_id = updated_fields.get("groupId", 0)
            new_accomplices = updated_fields.get("accomplices", [])

            from datetime import datetime
            if new_deadline_iso:
                try:
                    dt = datetime.fromisoformat(new_deadline_iso)
                    new_deadline = dt.strftime("%d/%m/%Y %H:%M")
                except ValueError:
                    new_deadline = new_deadline_iso
            else:
                new_deadline = ""

            try:
                resp_id = int(new_responsible_id_str)
            except ValueError:
                resp_id = 0

            responsible_name = (get_user_name_from_bitrix(bitrix_url, resp_id)
                                or f"ID {resp_id}")

            project_name = ""
            if new_group_id:
                pn = get_project_name_by_id(bitrix_url, new_group_id)
                if pn != "-1":
                    project_name = pn

            accomplices_names = []
            for ac_id in new_accomplices:
                ac_name = get_user_name_from_bitrix(bitrix_url, ac_id)
                accomplices_names.append(ac_name or f"ID {ac_id}")

            # ============  Чек-лист  ============
            updated_checklist = get_checklist_items(bitrix_url, task_id)
            filtered_list = [
                x for x in updated_checklist
                if x.get("TITLE",
                         "").lower().replace("_", "").strip() != "bxchecklist1"
            ]
            checklist_lines = []
            if filtered_list:
                for i, item in enumerate(filtered_list, start=1):
                    t = item.get("TITLE", "Без названия")
                    complete = item.get("IS_COMPLETE", "N")
                    prefix = "✅" if complete == "Y" else "⬜"
                    checklist_lines.append(f"{i}. {prefix} {t}")
            # ============ end Чек-лист ============

            lines = [
                f"*Задача обновлена:* {escape_markdown(new_title, version=2)}"
            ]
            if new_description:
                lines.append(
                    f"*Описание:* "
                    f"{escape_markdown(new_description, version=2)}")
            if new_deadline:
                lines.append(
                    f"*Дедлайн:* {escape_markdown(new_deadline, version=2)}")
            if project_name:
                lines.append(
                    f"*Проект:* {escape_markdown(project_name, version=2)}")
            lines.append(
                f"*Ответственный:* "
                f"{escape_markdown(responsible_name, version=2)}"
            )

            if accomplices_names:
                joined_accomp = ", ".join(escape_markdown(a, version=2)
                                          for a in accomplices_names)
                lines.append(f"*Соисполнители:* {joined_accomp}")

            if checklist_lines:
                escaped_lines = [escape_markdown(x, version=2) for x in
                                 checklist_lines]
                checklist_str = "\n".join(escaped_lines)
                lines.append(f"*Чек\\-лист:*\n{checklist_str}")

            updated_text = "\n".join(lines)

            kb = [[InlineKeyboardButton("Изменить задачу",
                                        callback_data=f"edit_task:{task_id}")]]
            rm = InlineKeyboardMarkup(kb)

            await context.bot.edit_message_text(
                chat_id=original_chat_id,
                message_id=original_msg_id,
                text=updated_text,
                parse_mode="MarkdownV2",
                reply_markup=rm
            )

    return ConversationHandler.END


async def checklist_del_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Показываем список пунктов для удаления."""
    query = update.callback_query
    await query.answer()

    task_id = context.user_data.get("edit_task_id")
    if not task_id:
        if query.message and isinstance(query.message, TelegramMessage):
            await query.message.reply_text("Неизвестная задача.")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                                           text="Неизвестная задача.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
    if not bitrix_url:
        if query.message and isinstance(query.message, TelegramMessage):
            await query.message.reply_text("Нет настроенного Bitrix URL.")
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Нет настроенного Bitrix URL."
            )
        return ConversationHandler.END

    check_list = get_checklist_items(bitrix_url, task_id)

    filtered_check_list = [
        x for x in check_list
        if
        x.get("TITLE", "").lower().replace("_", "").strip() != "bxchecklist1"
    ]

    if not check_list:
        await query.edit_message_text("Чек-лист пуст.")
        return CHECKLIST_MENU

    buttons = []
    text_lines = ["Выберите пункт для удаления:"]
    for i, item in enumerate(filtered_check_list, start=1):
        title = item.get("TITLE", "Без названия")
        item_id = item.get("ID", "")
        text_lines.append(f"{i}. {title}")
        buttons.append([
            InlineKeyboardButton(
                f"Удалить {i}",
                callback_data=f"checklist_del_item:{item_id}"
            )
        ])
    buttons.append([InlineKeyboardButton("Отмена",
                                         callback_data="cancel_edit")])

    await query.edit_message_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return CHECKLIST_DEL


async def checklist_del_item_callback(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    """Удаляем конкретный пункт по item_id из чек-листа."""
    query = update.callback_query
    await query.answer()

    data = query.data  # "checklist_del_item:12345"
    _, item_id_str = data.split(":", 1)
    item_id = item_id_str

    task_id = context.user_data.get("edit_task_id")
    if not task_id:
        if not task_id:
            if query.message and isinstance(query.message, TelegramMessage):
                await query.message.reply_text("Неизвестная задача.")
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Неизвестная задача.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    bitrix_url = await get_url_by_type(chat_id, chat_type, context)
    if not bitrix_url:
        if query.message and isinstance(query.message, TelegramMessage):
            await query.message.reply_text("Нет настроенного Bitrix URL.")
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Нет настроенного Bitrix URL."
            )
        return ConversationHandler.END

    success = delete_checklist_item(bitrix_url, task_id, item_id)

    if success:
        await query.edit_message_text("Пункт удалён из чек-листа.")
    else:
        await query.edit_message_text("Ошибка при удалении пункта.")

    if success:
        task_entry = context.user_data.get("created_tasks", {}).get(task_id)
        if task_entry:
            original_chat_id = task_entry["chat_id"]
            original_msg_id = task_entry["message_id"]

            updated_fields = get_task_fields_from_bitrix(bitrix_url, task_id)
            if updated_fields:
                new_title = updated_fields.get("title", "Без названия")
                new_description = updated_fields.get("description", "")
                new_deadline_iso = updated_fields.get("deadline", "")
                new_responsible_id_str = updated_fields.get("responsibleId",
                                                            "")
                new_group_id = updated_fields.get("groupId", 0)
                new_accomplices = updated_fields.get("accomplices", [])

                if new_deadline_iso:
                    try:
                        dt = datetime.fromisoformat(new_deadline_iso)
                        new_deadline = dt.strftime("%d/%m/%Y %H:%M")
                    except ValueError:
                        new_deadline = new_deadline_iso
                else:
                    new_deadline = ""

                try:
                    resp_id = int(new_responsible_id_str)
                except ValueError:
                    resp_id = 0
                responsible_name = (
                            get_user_name_from_bitrix(bitrix_url, resp_id)
                            or f"ID {resp_id}")

                project_name = ""
                if new_group_id:
                    pn = get_project_name_by_id(bitrix_url, new_group_id)
                    if pn != "-1":
                        project_name = pn

                accomplices_names = []
                for ac_id in new_accomplices:
                    ac_name = get_user_name_from_bitrix(bitrix_url, ac_id)
                    accomplices_names.append(ac_name or f"ID {ac_id}")

                updated_checklist = get_checklist_items(bitrix_url, task_id)
                filtered_list = [
                    x for x in updated_checklist
                    if x.get("TITLE",
                             "").lower().replace("_",
                                                 "").strip() != "bxchecklist1"
                ]
                checklist_lines = []
                if filtered_list:
                    for i, item in enumerate(filtered_list, start=1):
                        t = item.get("TITLE", "Без названия")
                        complete = item.get("IS_COMPLETE", "N")
                        prefix = "✅" if complete == "Y" else "⬜"
                        checklist_lines.append(f"{i}. {prefix} {t}")

                lines = [
                    f"*Задача обновлена:* {escape_markdown(new_title, 
                                                           version=2)}"
                ]
                if new_description:
                    lines.append(
                        f"*Описание:* {escape_markdown(new_description, 
                                                       version=2)}")
                if new_deadline:
                    lines.append(
                        f"*Дедлайн:* {escape_markdown(new_deadline, 
                                                      version=2)}")
                if project_name:
                    lines.append(
                        f"*Проект:* {escape_markdown(project_name, 
                                                     version=2)}")
                lines.append(
                    f"*Ответственный:* {escape_markdown(responsible_name, 
                                                        version=2)}")

                if accomplices_names:
                    joined_accomp = ", ".join(
                        escape_markdown(a, version=2) for a in
                        accomplices_names
                    )
                    lines.append(f"*Соисполнители:* {joined_accomp}")

                if checklist_lines:
                    escaped_lines = [escape_markdown(x, version=2) for x in
                                     checklist_lines]
                    checklist_str = "\n".join(escaped_lines)
                    lines.append(f"*Чек\\-лист:*\n{checklist_str}")

                updated_text = "\n".join(lines)

                kb = [[InlineKeyboardButton("Изменить задачу",
                                            callback_data=f"edit_task:"
                                                          f"{task_id}")]]
                rm = InlineKeyboardMarkup(kb)

                await context.bot.edit_message_text(
                    chat_id=original_chat_id,
                    message_id=original_msg_id,
                    text=updated_text,
                    parse_mode="MarkdownV2",
                    reply_markup=rm
                )
    return CHECKLIST_MENU


edit_task_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(edit_task_callback, pattern=r"^edit_task:\d+")
    ],
    states={
        CHOOSING_FIELD: [
            CallbackQueryHandler(edit_field_callback, pattern=r"^edit_field"
                                                              r":\d+:.+"),
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit"),
            CallbackQueryHandler(edit_checklist_callback,
                                 pattern=r"^edit_checklist:\d+")
        ],
        WAITING_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_value),
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit")
        ],
        CHECKLIST_MENU: [
            CallbackQueryHandler(checklist_add_callback,
                                 pattern="checklist_add"),
            CallbackQueryHandler(checklist_del_callback,
                                 pattern="checklist_del"),
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit")
        ],
        CHECKLIST_ADD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND,
                           checklist_add_text),
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit")
        ],
        CHECKLIST_DEL: [
            CallbackQueryHandler(checklist_del_item_callback,
                                 pattern=r"^checklist_del_item:.+"),
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit")
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_edit)
    ]
)
