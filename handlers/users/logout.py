import logging

from aiogram import types
from aiogram.utils.exceptions import MessageNotModified, TelegramAPIError

from keyboards.inline.logout import CONFIRM, logout_cb, logout_confirm_markup
from loader import api, dp
from utils.api import NotFound

from .common import PRIVATE, require_user

log = logging.getLogger(__name__)

CONFIRM_TEXT = (
    "Tizimdan chiqmoqchimisiz?\n"
    "Shundan so‘ng bot sizga bildirishnomalar yubormaydi, "
    "Web App’dagi barcha ochiq sessiyalaringiz ham yakunlanadi."
)


@dp.message_handler(commands="logout", chat_type=PRIVATE)
async def bot_logout(message: types.Message) -> None:
    user = await require_user(message, allow_temp_password=True)
    if user is not None:
        await message.answer(CONFIRM_TEXT, reply_markup=logout_confirm_markup())


@dp.callback_query_handler(logout_cb.filter(), state="*", chat_type=PRIVATE)
async def bot_logout_answer(call: types.CallbackQuery, callback_data: dict[str, str]) -> None:
    if callback_data["action"] != CONFIRM:
        await _edit_quietly(call.message, "Chiqish bekor qilindi.")
        await call.answer()
        return

    try:
        await api.unlink(call.from_user.id)
    except NotFound:
        pass  # allaqachon uzilgan — natija bir xil

    await _edit_quietly(call.message, "Siz tizimdan chiqdingiz. Telegram akkauntingiz uzildi.")
    await call.message.answer(
        "Qayta kirish uchun /start buyrug‘ini yuboring.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await call.answer()


async def _edit_quietly(message: types.Message, text: str) -> None:
    """Tasdiqlash xabarini yangilaydi; eski (tahrirlab bo'lmaydigan) xabar oqimni to'xtatmaydi."""
    try:
        await message.edit_text(text)
    except MessageNotModified:
        pass
    except TelegramAPIError as exc:
        log.info("Tasdiqlash xabarini tahrirlab bo‘lmadi: %s", type(exc).__name__)
