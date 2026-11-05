"""``/notifications`` va «🔔 Bildirishnomalar» tugmasi (API_CONTRACT_V3 §14.3).

Manba: ``GET bot/users/{telegram_id}/notifications?limit=10`` — Web App qo‘ng‘iroqchasidagi bilan bir xil
qatorlar (Telegramga yuborilmaganlari ham). O‘qilmaganlari 🆕 bilan belgilanadi.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from aiogram import types

from data import config
from keyboards.default.menu import BTN_NOTIFICATIONS, main_menu
from keyboards.inline.webapp import WEBAPP_BUTTON_TEXT, webapp_button_markup
from loader import api, dp
from utils.api import Forbidden, NotFound
from utils.formatting import fmt_datetime

from .common import NOT_LINKED_TEXT, PRIVATE, esc, require_user

INBOX_LIMIT = 10
INBOX_TITLE = "🔔 <b>Bildirishnomalar</b>"
INBOX_EMPTY = "Hozircha bildirishnoma yo‘q."


def inbox_text(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return f"{INBOX_TITLE}\n\n{INBOX_EMPTY}"
    lines = [INBOX_TITLE, ""]
    for row in rows:
        mark = "🆕" if not row.get("read_at") else "•"
        title = row.get("title") or "NNP"
        lines.append(f"{mark} {fmt_datetime(row.get('created_at'))} — {esc(title)}")
    return "\n".join(lines)


@dp.message_handler(commands="notifications", chat_type=PRIVATE)
@dp.message_handler(text=BTN_NOTIFICATIONS, chat_type=PRIVATE)
async def bot_notifications(message: types.Message) -> None:
    user = await require_user(message)
    if user is None:
        return
    try:
        rows = await api.get_inbox(message.from_user.id, INBOX_LIMIT)
    except NotFound:
        await message.answer(NOT_LINKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return
    except Forbidden as exc:
        await message.answer(f"⚠️ {esc(exc.detail)}")
        return
    # Web App qo'ng'iroqchasi shell'da (``/``): u yerdan xabarni ochib, kerakli sahifaga o'tiladi.
    markup = webapp_button_markup(WEBAPP_BUTTON_TEXT, f"{config.WEBAPP_URL}/") if config.WEBAPP_ENABLED else None
    await message.answer(inbox_text(rows), reply_markup=markup or main_menu(user["role"]))
