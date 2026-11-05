"""``/settings`` — shaxsiy bildirishnoma sozlamalari (TZ §11.3): Web App'dagi sozlamalar oynasiga yo'l."""
from aiogram import types

from data import config
from keyboards.inline.webapp import platform_markup
from loader import dp

from .common import PRIVATE, WEBAPP_NOT_CONFIGURED_TEXT, require_user

SETTINGS_TEXT = (
    "<b>⚙️ Bildirishnoma sozlamalari</b>\n\n"
    "Qaysi xabarlarni olishni o‘zingiz tanlashingiz mumkin: xabarni butunlay o‘chirish yoki faqat "
    "platformadagi qo‘ng‘iroqchada qoldirish (Telegramga yubormaslik).\n\n"
    "Platformani oching → 🔔 qo‘ng‘iroqcha → ⚙️ «Bildirishnoma sozlamalari»."
)


@dp.message_handler(commands="settings", chat_type=PRIVATE)
async def bot_settings(message: types.Message) -> None:
    user = await require_user(message)
    if user is None:
        return
    if config.WEBAPP_ENABLED:
        await message.answer(SETTINGS_TEXT, reply_markup=platform_markup(config.WEBAPP_URL))
    else:
        await message.answer(f"{SETTINGS_TEXT}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}")
