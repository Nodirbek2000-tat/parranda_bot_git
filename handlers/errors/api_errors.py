"""Backend xatolarini (aloqa yo'qligi, 5xx, noto'g'ri X-Bot-Token) foydalanuvchiga tushunarli qilib ko'rsatish."""
import logging

from aiogram import types
from aiogram.utils.exceptions import TelegramAPIError

from loader import dp
from utils.api import SERVER_ERROR_MESSAGE, UNAVAILABLE_MESSAGE, ApiError, TooManyRequests, Unavailable

log = logging.getLogger(__name__)


async def reply_error(update: types.Update, text: str) -> None:
    """Xatolik matnini update manbasiga (xabar yoki callback) yuboradi; Telegram xatosi yutiladi."""
    try:
        if update.message:
            await update.message.answer(text)
        elif update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
    except TelegramAPIError as exc:
        log.warning("Xatolik haqidagi xabarni yuborib bo‘lmadi: %s", exc)


@dp.errors_handler(exception=ApiError)
async def api_error_handler(update: types.Update, exception: ApiError) -> bool:
    if isinstance(exception, Unavailable):
        text = UNAVAILABLE_MESSAGE
    elif isinstance(exception, TooManyRequests):
        text = exception.detail
    else:
        text = SERVER_ERROR_MESSAGE
        if exception.status == 403:
            log.error("Backend 403 qaytardi: BOT_API_TOKEN backenddagi qiymat bilan mosligini tekshiring")
        else:
            log.error("Backend xatoligi: %s", exception)

    await reply_error(update, text)
    return True
