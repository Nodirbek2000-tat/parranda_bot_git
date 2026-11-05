import logging
from collections.abc import Iterable

from aiogram import Bot
from aiogram.utils.exceptions import TelegramAPIError

log = logging.getLogger(__name__)


async def on_startup_notify(bot: Bot, admins: Iterable[int]) -> None:
    """Bot ishga tushgani haqida adminlarga xabar beradi (ro'yxat bo'sh bo'lsa hech narsa qilmaydi)."""
    for admin_id in admins:
        try:
            await bot.send_message(admin_id, "✅ NNP boti ishga tushdi.")
        except TelegramAPIError as exc:
            log.warning("Admin %s ga xabar yuborilmadi: %s", admin_id, exc)
