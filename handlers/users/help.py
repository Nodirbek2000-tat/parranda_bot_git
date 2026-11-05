from aiogram import types
from aiogram.dispatcher.filters.builtin import CommandHelp

from keyboards.default.menu import BTN_HELP
from loader import dp

from .common import HELP_TEXT, PRIVATE


@dp.message_handler(CommandHelp(), state="*", chat_type=PRIVATE)
@dp.message_handler(text=BTN_HELP, chat_type=PRIVATE)
async def bot_help(message: types.Message) -> None:
    await message.answer(HELP_TEXT)
