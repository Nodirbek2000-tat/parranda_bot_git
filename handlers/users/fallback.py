from aiogram import types

from loader import dp

from .common import PRIVATE, require_user, send_main_menu


@dp.message_handler(state=None, content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def bot_fallback(message: types.Message) -> None:
    """Tanilmagan xabarlar: aks-sado bermaymiz, menyuni ko'rsatamiz."""
    user = await require_user(message)
    if user is not None:
        await send_main_menu(message, user, text="Iltimos, quyidagi menyudan foydalaning.")
