from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.builtin import CommandStart

from loader import dp
from states import LoginStates

from .common import BLOCKED_TEXT, PRIVATE, fetch_user, send_main_menu

WELCOME_TEXT = (
    "Assalomu alaykum!\n"
    "Bu <b>NNP — Navobod naslli parranda qisqarmasi</b> platformasining rasmiy boti.\n\n"
    "Tizimga kirish uchun <b>login</b>ingizni yuboring.\n"
    "Bekor qilish: /cancel"
)


@dp.message_handler(CommandStart(), state="*", chat_type=PRIVATE)
async def bot_start(message: types.Message, state: FSMContext) -> None:
    await state.finish()
    user = await fetch_user(message.from_user.id)

    if user is None:
        await LoginStates.username.set()
        await message.answer(WELCOME_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return

    if not user.get("is_active", True):
        await message.answer(BLOCKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return

    await send_main_menu(message, user)
