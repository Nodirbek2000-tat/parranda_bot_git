"""Logistika topshiriqlari: ``/tasks`` matnlari, inline tugmalar va callback ma'lumoti (API_CONTRACT_V3 §14.2).

- LOGISTICS / OWNER: har bir topshiriq alohida xabar (o‘z tugmalari bilan), eng ko‘pi 10 ta;
- WAREHOUSE: bitta xulosa xabari (yuklash kutilayotganlar, kam qolgan mahsulotlar, muddati yaqin partiyalar).

Callback ma'lumoti ``t:<amal>:<id>`` (≤ 64 bayt). Bot uni faqat qat'iy shablon bo‘yicha qabul qiladi; qolgan barcha
tekshiruvlar (rol, xonadon egasi, holat) serverda. Tugmalar faqat server qaytargan ``allowed_actions`` bo‘yicha chiziladi.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any, Iterable, Mapping, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from keyboards.inline.webapp import WEBAPP_BUTTON_TEXT
from utils.formatting import EMPTY, fmt_date, fmt_number, local_today
from utils.roles import OWNER

TITLE = "📋 <b>Mening topshiriqlarim</b>"
NO_ACTIVE_TASKS = "Hozircha faol topshiriq yo‘q ✅"
MAX_TASKS = 10
MAX_LINES = 10
#: Telegram ``answerCallbackQuery`` matni chegarasi.
MAX_ALERT = 200

# -- callback ma'lumoti

ACCEPT = "acc"
START = "go"
DELIVER = "dlv"
CONFIRM = "cnf"
ISSUE = "iss"

#: callback kodi -> backenddagi ``allowed_actions`` nomi.
CALLBACK_ACTIONS: dict[str, str] = {
    ACCEPT: "accept",
    START: "start",
    DELIVER: "deliver",
    CONFIRM: "confirm",
    ISSUE: "confirm",
}
_MAX_ID = 2**63 - 1  # backenddagi ``MAX_DB_INT``
_CALLBACK_RE = re.compile(r"t:(acc|go|dlv|cnf|iss):([1-9][0-9]{0,18})")

BUTTON_TEXTS: dict[str, str] = {
    ACCEPT: "✅ Qabul qilish",
    START: "🛻 Yo‘lga chiqdim",
    DELIVER: "📦 Yetkazdim (foto bilan)",
    CONFIRM: "✅ Qabul qildim",
    ISSUE: "⚠️ Muammo bor",
}
#: ``allowed_actions`` -> tugmalar (tartib bilan). ``assign``, ``cancel``, ``edit`` — faqat Web App’da.
_ACTION_BUTTONS: dict[str, tuple[str, ...]] = {
    "accept": (ACCEPT,),
    "start": (START,),
    "deliver": (DELIVER,),
    "confirm": (CONFIRM, ISSUE),
}


def callback_data(code: str, task_id: int) -> str:
    return f"t:{code}:{int(task_id)}"


def parse_callback(data: Optional[str]) -> Optional[tuple[str, int]]:
    """``"t:acc:12"`` -> ``("acc", 12)``; shablonga mos kelmasa (yoki id juda katta) ``None``."""
    if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
        return None
    match = _CALLBACK_RE.fullmatch(data)
    if match is None:
        return None
    task_id = int(match.group(2))
    if task_id > _MAX_ID:
        return None
    return match.group(1), task_id


# -- matnlar


def _esc(value: Any) -> str:
    return escape(str(value), quote=False)


def household_label(item: Mapping[str, Any]) -> str:
    household = item.get("household") or {}
    name = str(household.get("name") or "")
    code = str(household.get("code") or "")
    return f"{name} ({code})" if code else name


def task_text(task: Mapping[str, Any]) -> str:
    """Bitta topshiriq xabari (kontrakt §14.2 namunasi; bo‘sh qatorlar tashlab ketiladi)."""
    lines = [f"🚚 <b>{_esc(task.get('code', ''))}</b> — {_esc(task.get('status_display') or task.get('status', ''))}"]
    household = household_label(task)
    if household:
        lines.append(f"Xonadon: {_esc(household)}")
    if task.get("address"):
        lines.append(f"Manzil: {_esc(task['address'])}")
    if task.get("items_text"):
        lines.append(f"Yuk: {_esc(task['items_text'])}")
    if task.get("vehicle_text"):
        lines.append(f"Transport: {_esc(task['vehicle_text'])}")
    if task.get("driver_text"):
        lines.append(f"Haydovchi: {_esc(task['driver_text'])}")
    planned = fmt_date(task.get("planned_date"))
    if planned != EMPTY:
        lines.append(f"Reja: {planned}" + (" ⚠️ muddati o‘tgan" if task.get("is_overdue") else ""))
    return "\n".join(lines)


def task_webapp_path(task: Mapping[str, Any], role: str) -> str:
    """Topshiriqning Web App sahifasi: xodimlar ``/logistics/{id}``, egasi buyurtma yoki ``/my/deliveries``."""
    if role == OWNER:
        order = task.get("order") or {}
        order_id = order.get("id") if isinstance(order, Mapping) else None
        return f"/my/orders/{int(order_id)}" if isinstance(order_id, int) else "/my/deliveries"
    return f"/logistics/{int(task['id'])}"


def task_markup(
    task: Mapping[str, Any], role: str, webapp_url: str = "", *, with_actions: bool = True
) -> Optional[InlineKeyboardMarkup]:
    """Server ruxsat bergan amallar tugmalari + (https bo‘lsa) Web App tugmasi; hech biri bo‘lmasa ``None``."""
    rows: list[list[InlineKeyboardButton]] = []
    if with_actions:
        allowed = task.get("allowed_actions") or []
        for action, codes in _ACTION_BUTTONS.items():
            if action in allowed:
                rows.append(
                    [InlineKeyboardButton(text=BUTTON_TEXTS[code], callback_data=callback_data(code, task["id"]))
                     for code in codes]
                )
    if webapp_url:
        rows.append([InlineKeyboardButton(
            text=WEBAPP_BUTTON_TEXT, web_app=WebAppInfo(url=f"{webapp_url}{task_webapp_path(task, role)}")
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def find_task(payload: Mapping[str, Any], task_id: int) -> Optional[dict[str, Any]]:
    """``/tasks`` javobidagi barcha ro‘yxatlardan topshiriqni id bo‘yicha topadi."""
    for key in ("tasks", "deliveries_to_confirm", "in_transit", "to_load"):
        for task in payload.get(key) or []:
            if isinstance(task, dict) and task.get("id") == task_id:
                return task
    return None


def owner_tasks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Egasi uchun alohida xabarlar: avval tasdiq kutayotganlar, keyin yo‘ldagilar (jami ≤ 10)."""
    rows = [*(payload.get("deliveries_to_confirm") or []), *(payload.get("in_transit") or [])]
    return rows[:MAX_TASKS]


def _counts_line(parts: Iterable[tuple[str, int]]) -> str:
    return " · ".join(f"{label}: <b>{fmt_number(value)}</b>" for label, value in parts)


def logistics_header(payload: Mapping[str, Any]) -> str:
    tasks = payload.get("tasks") or []
    lines = [TITLE, f"Sana: {fmt_date(local_today())}"]
    if not tasks:
        return "\n".join([*lines, "", NO_ACTIVE_TASKS])
    overdue = sum(1 for task in tasks if task.get("is_overdue"))
    new = sum(1 for task in tasks if task.get("status") == "NEW")
    in_transit = sum(1 for task in tasks if task.get("status") == "IN_TRANSIT")
    parts = [("Faol", len(tasks)), ("yo‘lda", in_transit), ("biriktirilmagan", new)]
    if overdue:
        parts.append(("muddati o‘tgan", overdue))
    lines.append(_counts_line(parts))
    if len(tasks) >= MAX_TASKS:
        lines.append(f"Birinchi {MAX_TASKS} tasi ko‘rsatilgan, qolganlari Web App’da.")
    return "\n".join(lines)


def _vet_line(item: Mapping[str, Any]) -> str:
    title = item.get("vaccine_name") or item.get("purpose") or ""
    parts = [f"<b>{_esc(item.get('code', ''))}</b>"]
    if title:
        parts[0] += f" — {_esc(str(title)[:80])}"
    parts.append(fmt_date(item.get("planned_date")))
    return "• " + " · ".join(parts)


def owner_header(payload: Mapping[str, Any]) -> str:
    lines = [TITLE, f"Sana: {fmt_date(local_today())}"]
    to_confirm = payload.get("deliveries_to_confirm") or []
    in_transit = payload.get("in_transit") or []
    orders = payload.get("open_orders") or []
    vet = payload.get("upcoming_vet") or []
    if not (to_confirm or in_transit or orders or vet):
        return "\n".join([*lines, "", NO_ACTIVE_TASKS])
    lines.append(_counts_line([("Tasdiqlash kutilmoqda", len(to_confirm)), ("Yo‘lda", len(in_transit))]))
    if to_confirm:
        lines.append("Mahsulotni qabul qilgach «✅ Qabul qildim» tugmasini bosing.")
    if orders:
        lines += ["", f"🛒 <b>Ochiq buyurtmalar</b> ({len(orders)})"]
        lines += [
            f"• <b>{_esc(order.get('code', ''))}</b> — {_esc(order.get('status_display') or order.get('status', ''))}"
            for order in orders[:MAX_LINES]
        ]
    if vet:
        lines += ["", "🩺 <b>Yaqin veterinariya ishlari</b>"]
        lines += [_vet_line(item) for item in vet[:MAX_LINES]]
    return "\n".join(lines)


def warehouse_text(payload: Mapping[str, Any]) -> str:
    lines = [TITLE, f"Sana: {fmt_date(local_today())}", ""]
    to_load = payload.get("to_load") or []
    if to_load:
        lines.append(f"🚚 <b>Yuklash kutilmoqda</b> ({len(to_load)})")
        for task in to_load[:MAX_LINES]:
            parts = [f"<b>{_esc(task.get('code', ''))}</b> — {_esc(household_label(task))}"]
            if task.get("items_text"):
                parts.append(_esc(task["items_text"]))
            planned = fmt_date(task.get("planned_date"))
            if planned != EMPTY:
                parts.append(planned)
            parts.append(_esc(task.get("status_display") or task.get("status", "")))
            lines.append("• " + " · ".join(parts))
    else:
        lines.append("🚚 Yuklash kutilayotgan topshiriq yo‘q.")
    lines += [
        "",
        f"📉 Kam qolgan mahsulotlar: <b>{fmt_number(payload.get('low_stock_count') or 0)}</b>",
        f"⏳ Muddati yaqin partiyalar: <b>{fmt_number(payload.get('expiring_lots') or 0)}</b>",
    ]
    return "\n".join(lines)


def alert_text(text: str) -> str:
    """Callback javobi uchun matn (Telegram chegarasi 200 belgi)."""
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_ALERT else text[: MAX_ALERT - 1] + "…"
