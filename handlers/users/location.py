from aiogram import types

from keyboards.default.menu import main_menu
from loader import api, dp
from utils.api import ApiError, NotFound
from utils.roles import OWNER

from .common import NOT_LINKED_TEXT, PRIVATE, esc


@dp.message_handler(content_types=types.ContentType.LOCATION, chat_type=PRIVATE)
async def bot_location(message: types.Message) -> None:
    latitude = round(message.location.latitude, 6)
    longitude = round(message.location.longitude, 6)

    try:
        household = await api.send_location(message.from_user.id, latitude, longitude)
    except NotFound:
        await message.answer(NOT_LINKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return
    except ApiError as exc:
        if exc.status == 0 or exc.status >= 500:
            raise  # umumiy xatolik handleri javob beradi
        # 403: xonadon egasi emas yoki hisob bloklangan — backend matni aynan ko'rsatiladi.
        await message.answer(f"⚠️ {esc(exc.detail)}")
        return

    saved_lat = household.get("latitude")
    saved_lon = household.get("longitude")
    lat = latitude if saved_lat is None else float(saved_lat)
    lon = longitude if saved_lon is None else float(saved_lon)
    await message.answer(
        "✅ <b>Lokatsiya saqlandi</b>\n\n"
        f"Xonadon: {esc(household['name'])} ({esc(household['code'])})\n"
        f"Koordinatalar: <code>{lat:.6f}, {lon:.6f}</code>",
        reply_markup=main_menu(OWNER),
    )
