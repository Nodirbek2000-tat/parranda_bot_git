from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from utils.roles import LOGISTICS, OWNER, VET

BTN_LOCATION = "📍 Lokatsiyani yuborish"
BTN_PROFILE = "👤 Profil"
BTN_HELP = "ℹ️ Yordam"
BTN_REPORTS = "📊 Hisobot"
BTN_NOTIFICATIONS = "🔔 Bildirishnomalar"
# «Topshiriqlar» tugmasi rolga qarab nomlanadi (API_CONTRACT_V3 §14.4); hammasi /tasks ni ochadi.
BTN_TASKS = "📋 Topshiriqlar"
BTN_TASKS_LOGISTICS = "📋 Topshiriqlarim"
BTN_TASKS_VET = "📋 Bugungi ishlar"
TASK_BUTTONS = (BTN_TASKS, BTN_TASKS_LOGISTICS, BTN_TASKS_VET)


def tasks_button_text(role: str) -> str:
    if role == LOGISTICS:
        return BTN_TASKS_LOGISTICS
    if role == VET:
        return BTN_TASKS_VET
    return BTN_TASKS


def main_menu(role: str) -> ReplyKeyboardMarkup:
    """Rolga mos asosiy menyu (API_CONTRACT_V3 §14.4).

    OWNER: lokatsiya · topshiriqlar + bildirishnomalar · hisobot, profil, yordam;
    qolgan rollar: topshiriqlar + bildirishnomalar · hisobot, profil, yordam.
    """
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    if role == OWNER:
        markup.row(KeyboardButton(BTN_LOCATION, request_location=True))
    markup.row(KeyboardButton(tasks_button_text(role)), KeyboardButton(BTN_NOTIFICATIONS))
    markup.row(KeyboardButton(BTN_REPORTS), KeyboardButton(BTN_PROFILE), KeyboardButton(BTN_HELP))
    return markup


remove_keyboard = ReplyKeyboardRemove()
