"""``/tasks`` va «📋 Topshiriqlar / Topshiriqlarim / Bugungi ishlar» tugmalari (API_CONTRACT_V3 §14.2).

Manba: ``GET bot/users/{tid}/tasks`` (har safar yangidan).

- LOGISTICS: sarlavha + har bir faol topshiriq alohida xabar (``✅ Qabul qilish``, ``🛻 Yo‘lga chiqdim``,
  ``📦 Yetkazdim (foto bilan)`` — faqat server ruxsat bergan amallar), eng ko‘pi 10 ta;
- OWNER: sarlavha (ochiq buyurtmalar, yaqin veterinariya ishlari) + tasdiq kutayotgan va yo‘ldagi yetkazib
  berishlar alohida xabar (``✅ Qabul qildim`` / ``⚠️ Muammo bor``);
- VET / ADMIN / WAREHOUSE: bitta xulosa xabari + Web App tugmalari.

Backend javob bermasa — rolga mos Web App bo‘limi tugmasi (https ``WEBAPP_URL`` bo‘lmasa — tushuntirish matni).
Tugmalar bosilishi: ``handlers/users/task_actions.py``.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from data import config
from keyboards.default.menu import TASK_BUTTONS, main_menu
from keyboards.inline.webapp import webapp_button_markup
from loader import api, dp
from utils.api import ApiError
from utils.logistics_tasks import (
    MAX_TASKS,
    logistics_header,
    owner_header,
    owner_tasks,
    task_markup,
    task_text,
    warehouse_text,
)
from utils.roles import ADMIN, LOGISTICS, OWNER, VET, WAREHOUSE, home_path
from utils.vet_tasks import admin_tasks_text, vet_tasks_text

from .common import PRIVATE, WEBAPP_NOT_CONFIGURED_TEXT, require_user

log = logging.getLogger(__name__)

TASKS_TITLE = "📋 <b>Mening topshiriqlarim</b>"

#: Rol -> (matn, Web App yo'li, tugma matni) — backend javob bermaganda.
_ROLE_TASKS: dict[str, tuple[str, str, str]] = {
    LOGISTICS: (
        "Yetkazib berish topshiriqlari Web App’ning «Logistika» bo‘limida.",
        "/logistics",
        "🚚 Logistika",
    ),
    VET: (
        "Bugungi tekshiruvlar, emlashlar va murojaatlar Web App’ning «Veterinariya» bo‘limida.",
        "/vet",
        "🩺 Veterinariya",
    ),
    OWNER: (
        "Buyurtmalaringiz va yetkazib berishlar Web App’da.",
        "/my/orders",
        "🛒 Buyurtmalarim",
    ),
}


def tasks_text(role: str) -> tuple[str, str, str]:
    """``(matn, Web App yo'li, tugma matni)`` — ADMIN/WAREHOUSE uchun bosh sahifa."""
    text, path, button = _ROLE_TASKS.get(
        role, ("Buyurtmalar, yetkazib berish va ombor holati Web App’da.", home_path(role), "🚀 Platformani ochish")
    )
    return f"{TASKS_TITLE}\n\n{text}", path, button


#: Xulosa xabarlari tugmalari (V3 §14.2): VET ``/vet``, ADMIN ``/orders``, WAREHOUSE ``/warehouse``.
#: Konstruktor vazifalari va dalolatnomalar (API_CONTRACT_V4 §3, §6) — har bir rolda oxirgi tugmalar.
WORK_BUTTONS: list[tuple[str, str]] = [("📝 Vazifalar", "/tasks"), ("📄 Dalolatnomalar", "/acts")]
_SUMMARY_BUTTONS: dict[str, list[tuple[str, str]]] = {
    VET: [("🩺 Veterinariya", "/vet"), ("📨 Murojaatlar", "/vet/requests"), *WORK_BUTTONS],
    ADMIN: [
        ("🛒 Buyurtmalar", "/orders"), ("🚚 Logistika", "/logistics"), ("🩺 Veterinariya", "/vet"),
        ("🔄 Jarayonlar", "/processes"), *WORK_BUTTONS,
    ],
    WAREHOUSE: [("📦 Ombor", "/warehouse"), ("🚚 Logistika", "/logistics"), *WORK_BUTTONS],
}
#: Sarlavha xabari tugmalari (LOGISTICS / OWNER).
_HEADER_BUTTONS: dict[str, list[tuple[str, str]]] = {
    LOGISTICS: [("🚚 Logistika", "/logistics"), *WORK_BUTTONS],
    OWNER: [("🛒 Buyurtmalarim", "/my/orders"), ("🚚 Yetkazib berishlar", "/my/deliveries"), *WORK_BUTTONS],
}
#: ADMIN: yangi buyurtmalarning to‘g‘ridan-to‘g‘ri havolalari (eng ko‘pi shuncha).
ADMIN_ORDER_LINKS = 4


def _webapp_rows(buttons: list[tuple[str, str]]) -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{config.WEBAPP_URL}{path}"))]
        for text, path in buttons
    ]


def summary_markup(role: str, payload: dict[str, Any] | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if role == ADMIN and payload:
        # Tasdiq kutayotgan buyurtmalar — har biri o‘z sahifasiga (ikkitadan bir qatorda).
        links = [
            InlineKeyboardButton(
                text=f"🛒 {order.get('code', '')}", web_app=WebAppInfo(url=f"{config.WEBAPP_URL}/orders/{order['id']}")
            )
            for order in (payload.get("orders_new") or [])[:ADMIN_ORDER_LINKS]
            if isinstance(order.get("id"), int)
        ]
        rows += [links[i:i + 2] for i in range(0, len(links), 2)]
    rows += _webapp_rows(_SUMMARY_BUTTONS[role])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_SUMMARY_TEXTS = {VET: vet_tasks_text, ADMIN: admin_tasks_text, WAREHOUSE: warehouse_text}


async def _send_summary(message: types.Message, role: str, payload: dict[str, Any]) -> None:
    text = _SUMMARY_TEXTS[role](payload)
    if config.WEBAPP_ENABLED:
        await message.answer(text, reply_markup=summary_markup(role, payload), disable_web_page_preview=True)
    else:
        await message.answer(f"{text}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}", reply_markup=main_menu(role))


async def _send_task_list(message: types.Message, role: str, payload: dict[str, Any]) -> None:
    """Sarlavha + har bir topshiriq alohida xabar (o‘z tugmalari bilan)."""
    if role == LOGISTICS:
        header, tasks = logistics_header(payload), (payload.get("tasks") or [])[:MAX_TASKS]
    else:
        header, tasks = owner_header(payload), owner_tasks(payload)
    if config.WEBAPP_ENABLED:
        await message.answer(header, reply_markup=InlineKeyboardMarkup(inline_keyboard=_webapp_rows(_HEADER_BUTTONS[role])))
    else:
        await message.answer(f"{header}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}", reply_markup=main_menu(role))
    webapp = config.WEBAPP_URL if config.WEBAPP_ENABLED else ""
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), int):
            continue
        await message.answer(task_text(task), reply_markup=task_markup(task, role, webapp))


async def _send_fallback(message: types.Message, role: str) -> None:
    text, path, button = tasks_text(role)
    if config.WEBAPP_ENABLED:
        await message.answer(text, reply_markup=webapp_button_markup(button, f"{config.WEBAPP_URL}{path}"))
    else:
        await message.answer(f"{text}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}", reply_markup=main_menu(role))


@dp.message_handler(commands="tasks", chat_type=PRIVATE)
@dp.message_handler(text=list(TASK_BUTTONS), chat_type=PRIVATE)
async def bot_tasks(message: types.Message) -> None:
    user = await require_user(message)
    if user is None:
        return
    role = user["role"]
    try:
        payload = await api.get_tasks(message.from_user.id)
    except ApiError as exc:
        log.warning("/tasks ma'lumotini olib bo'lmadi: %s", exc)
        await _send_fallback(message, role)
        return
    # Rol foydalanuvchi so‘rovi va /tasks so‘rovi orasida o‘zgargan bo‘lishi mumkin: backend javobi ustun.
    role = str(payload.get("role") or role)
    if role in (LOGISTICS, OWNER):
        await _send_task_list(message, role, payload)
    elif role in _SUMMARY_TEXTS:
        await _send_summary(message, role, payload)
    else:
        await _send_fallback(message, role)
