import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Message as TelegramMessage
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    CommandHandler, MessageHandler, filters
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.error import BadRequest

from ..services.bitrix_service import (
    update_task_in_bitrix,
    get_task_fields_from_bitrix,
    get_project_id_by_name,
    get_project_name_by_id,
    add_checklist_item,
    delete_checklist_item,
    get_checklist_items,
    get_user_name_from_bitrix,
)
from ..utils import get_url_by_type

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
                old_chat_id = context.user_data.get("edit_chat_id")
                old_message_id = context.user_data.get("edit_message_id")

                if old_chat_id and old_message_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=old_chat_id,
                            message_id=old_message_id,
                            text="Проект с таким названием не найден. "
                                 "Попробуйте ещё раз."
                        )
                    except BadRequest:
                        logging.debug(
                            "Попытка редактировать сообщение не удалась.")
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
        return ConversationHandler.END

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
                    f"*Задача обновлена:* {escape_markdown(new_title, version=2)}"
                ]
                if new_description:
                    lines.append(
                        f"*Описание:* {escape_markdown(new_description, version=2)}")
                if new_deadline:
                    lines.append(
                        f"*Дедлайн:* {escape_markdown(new_deadline, version=2)}")
                if project_name:
                    lines.append(
                        f"*Проект:* {escape_markdown(project_name, version=2)}")
                lines.append(
                    f"*Ответственный:* {escape_markdown(responsible_name, version=2)}")

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
            CallbackQueryHandler(cancel_edit, pattern="cancel_edit"),
            CallbackQueryHandler(edit_task_callback, pattern=r"^edit_task:\d+")
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



