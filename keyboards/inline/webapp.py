from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

PLATFORM_BUTTON_TEXT = "🚀 PLATFORMANI OCHISH"
WEBAPP_BUTTON_TEXT = "🔎 Web App orqali ko‘rish"


def webapp_button_markup(text: str, url: str) -> InlineKeyboardMarkup:
    """Bitta Web App tugmasidan iborat inline klaviatura (``url`` https bo'lishi shart)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]]
    )


def platform_markup(webapp_url: str) -> InlineKeyboardMarkup:
    return webapp_button_markup(PLATFORM_BUTTON_TEXT, webapp_url)
