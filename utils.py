from telegram.ext import ContextTypes
from db import get_user, get_url
from datetime import datetime


def extract_mention_username(message):
    entities = message.entities or []
    for ent in entities:
        if ent.type == "mention":
            mention_text = message.text[ent.offset:ent.offset + ent.length]
            return mention_text[1:]
    return None


async def get_url_by_type(chat_id: int, chat_type: str,
                          context: ContextTypes.DEFAULT_TYPE):
    if chat_type == "private":
        user_row = get_url(chat_id)
        if user_row:
            return user_row
    elif chat_type == "group" or chat_type == "supergroup":
        return await get_uinfo_from_admins(chat_id, context)[0]
    return None


async def get_uinfo_from_admins(chat_id: int,
                                context: ContextTypes.DEFAULT_TYPE):
    admin_ids = await get_chat_admin_ids(chat_id, context)
    for adm_id in admin_ids:
        user_row = get_user(adm_id)
        if user_row:
            bitrix_url = user_row[2]
            is_enabled = user_row[1]
            group_id = user_row[4]

            if bitrix_url and is_enabled:
                return bitrix_url, group_id
    return None, None


async def get_chat_admin_ids(chat_id: int,
                             context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    admins = await context.bot.get_chat_administrators(chat_id)
    # admins -> список ChatMember (ChatMemberAdministrator / ChatMemberOwner)
    admin_ids = []
    for member in admins:
        # member = ChatMember(owner, admin, member, restricted, left, kicked)
        admin_ids.append(member.user.id)
    return admin_ids


def format_datetime(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str)
    return dt.strftime("%d.%m.%Y %H:%M")
