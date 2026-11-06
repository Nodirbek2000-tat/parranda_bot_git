from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

import config

BTN_TASKS = "📋 Vazifalarim"
BTN_PLATFORM = "🚀 Platformani ochish"
BTN_PROFILE = "👤 Profil"
BTN_HELP = "ℹ️ Yordam"
BTN_LOGOUT = "🚪 Chiqish"

OPEN_CASE_TEXT = "📂 Ochish"
OPEN_PLATFORM_TEXT = "🚀 Platformani ochish"

LOGOUT_YES = "logout:yes"
LOGOUT_NO = "logout:no"

remove_keyboard = ReplyKeyboardRemove()


def main_menu() -> ReplyKeyboardMarkup:
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton(BTN_TASKS), KeyboardButton(BTN_PLATFORM))
    markup.row(KeyboardButton(BTN_PROFILE), KeyboardButton(BTN_HELP), KeyboardButton(BTN_LOGOUT))
    return markup


def webapp_url(path: str = "/") -> Optional[str]:
    """Full Web App address for ``path``, or None when WEBAPP_URL is not https."""
    if not config.webapp_enabled():
        return None
    path = path or "/"
    return config.WEBAPP_URL + (path if path.startswith("/") else f"/{path}")


def webapp_button(text: str, path: str = "/") -> Optional[InlineKeyboardMarkup]:
    """One inline Web App button, or None when the Web App is not configured (non-https)."""
    url = webapp_url(path)
    if url is None:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]])


def logout_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton("✅ Ha, chiqish", callback_data=LOGOUT_YES),
        InlineKeyboardButton("❌ Yo‘q", callback_data=LOGOUT_NO),
    ]])
