"""Qolgan barcha xatolar uchun yakuniy handler.

Muhim: aiogram 2 da ``errors_handlers`` barcha mos handlerlarni chaqiradi (``once=False``),
shuning uchun ``ApiError`` bu yerda qayta ishlanmaydi. Update matni logga yozilmaydi —
unda foydalanuvchi paroli bo'lishi mumkin.
"""
import logging

from aiogram import types
from aiogram.utils.exceptions import (
    InvalidQueryID,
    MessageCantBeDeleted,
    MessageCantBeEdited,
    MessageNotModified,
    MessageToDeleteNotFound,
    TelegramAPIError,
)

from loader import dp
from utils.api import ApiError, SERVER_ERROR_MESSAGE

from .api_errors import reply_error

log = logging.getLogger(__name__)

# Foydalanuvchi uchun ahamiyatsiz, kutiladigan Telegram javoblari.
_HARMLESS = (
    MessageNotModified,
    MessageCantBeEdited,
    MessageCantBeDeleted,
    MessageToDeleteNotFound,
    InvalidQueryID,
)


@dp.errors_handler()
async def errors_handler(update: types.Update, exception: BaseException) -> bool:
    if isinstance(exception, ApiError):
        return True  # api_errors.api_error_handler javob bergan

    update_id = getattr(update, "update_id", None)
    if isinstance(exception, _HARMLESS):
        log.info("Update %s: %s", update_id, type(exception).__name__)
        return True
    if isinstance(exception, TelegramAPIError):
        log.warning("Update %s: Telegram API xatoligi %s: %s", update_id, type(exception).__name__, exception)
        return True

    log.error("Update %s: kutilmagan xatolik", update_id, exc_info=exception)
    await reply_error(update, SERVER_ERROR_MESSAGE)
    return True
