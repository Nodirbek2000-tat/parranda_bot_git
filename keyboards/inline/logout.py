from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.callback_data import CallbackData

logout_cb = CallbackData("logout", "action")

CONFIRM = "yes"
CANCEL = "no"


def logout_confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ha, chiqish", callback_data=logout_cb.new(action=CONFIRM)),
                InlineKeyboardButton(text="❌ Yo‘q", callback_data=logout_cb.new(action=CANCEL)),
            ]
        ]
    )
