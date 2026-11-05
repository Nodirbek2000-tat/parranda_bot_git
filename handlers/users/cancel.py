from aiogram import types
from aiogram.dispatcher import FSMContext

from loader import dp

from .common import PRIVATE, fetch_user, send_main_menu


@dp.message_handler(commands="cancel", state="*", chat_type=PRIVATE)
async def bot_cancel(message: types.Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Bekor qilinadigan amal yo‘q.")
        return

    await state.finish()
    user = await fetch_user(message.from_user.id)
    if user is not None and user.get("is_active", True):
        await send_main_menu(message, user, text="Amal bekor qilindi.")
    else:
        await message.answer(
            "Amal bekor qilindi. Tizimga kirish uchun /start buyrug‘ini yuboring.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
