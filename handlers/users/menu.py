from aiogram import types

from keyboards.default.menu import BTN_PROFILE, main_menu
from loader import dp

from .common import PRIVATE, profile_text, require_user, send_main_menu


@dp.message_handler(commands="menu", chat_type=PRIVATE)
async def bot_menu(message: types.Message) -> None:
    user = await require_user(message, allow_temp_password=True)
    if user is not None:
        await send_main_menu(message, user)


@dp.message_handler(commands="profile", chat_type=PRIVATE)
@dp.message_handler(text=BTN_PROFILE, chat_type=PRIVATE)
async def bot_profile(message: types.Message) -> None:
    user = await require_user(message, allow_temp_password=True)
    if user is not None:
        await message.answer(profile_text(user), reply_markup=main_menu(user["role"]))
