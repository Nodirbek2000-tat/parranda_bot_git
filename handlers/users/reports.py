"""``/reports`` va «📊 Hisobot» tugmasi: rolga mos bugungi statistika.

Manba: ``GET bot/users/{telegram_id}/summary`` (docs/API_CONTRACT_V2.md, 5.1–5.2). Bot hech narsani
o'zi hisoblamaydi va keshlamaydi — faqat backend qiymatlarini formatlaydi:
sonlar ``2 800`` / ``310.5``, foizlar 1 xona kasr bilan ``81.2%``, ``null`` -> ``—``, sanalar ``DD.MM.YYYY``.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from aiogram import types

from data import config
from keyboards.default.menu import BTN_REPORTS, main_menu
from keyboards.inline.webapp import WEBAPP_BUTTON_TEXT, webapp_button_markup
from loader import api, dp
from utils.api import Forbidden, NotFound, UserSummary
from utils.formatting import EMPTY, fmt_date, fmt_number, fmt_percent, fmt_quantity, local_today, parse_date
from utils.roles import LOGISTICS, OWNER, VET

from .common import NOT_LINKED_TEXT, PRIVATE, esc, require_user

OWNER_WEBAPP_PATH = "/my"
STAFF_WEBAPP_PATH = "/stats"
ROLE_WEBAPP_PATHS = {OWNER: OWNER_WEBAPP_PATH, LOGISTICS: "/logistics", VET: "/vet"}


def _section(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Ichki obyekt; yo'q yoki noto'g'ri turdagi bo'lsa bo'sh lug'at (barcha qiymatlar ``—`` bo'ladi)."""
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _report_date(summary: Mapping[str, Any]) -> str:
    """Backend qaytargan mahalliy sana; bo'lmasa Toshkent vaqti bo'yicha bugun."""
    return fmt_date(parse_date(summary.get("date")) or local_today())


def _ratio(done: Any, total: Any) -> str:
    return f"{fmt_number(done)} / {fmt_number(total)}"


def _first(section: Mapping[str, Any], *keys: str) -> Any:
    """Birinchi mavjud kalit qiymati (eski backend javoblari bilan ham ishlash uchun)."""
    for key in keys:
        if key in section:
            return section[key]
    return None


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _death_lines(today: Mapping[str, Any]) -> list[str]:
    """``deaths`` = xonadonlardagi nobud (Web App /stats bilan bir xil), ``deaths_center`` alohida."""
    households = today.get("deaths")
    center = today.get("deaths_center")
    if not (_is_count(households) and _is_count(center)):
        return [f"Nobud: {fmt_quantity(households, 'dona')}"]
    return [
        f"Nobud: {fmt_quantity(households + center, 'dona')}",
        f"  xonadonlarda: {fmt_number(households)} · markazda: {fmt_number(center)}",
    ]


def _has_meat(value: Any) -> bool:
    """Go'sht qatori faqat go'sht kiritilgan bo'lsa ko'rsatiladi (broyler; tuxum xonadonlarida shovqin bo'lmasin)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def owner_report_text(summary: Mapping[str, Any]) -> str:
    household = _section(summary, "household")
    today = _section(summary, "today")
    week = _section(summary, "last_7d")
    submitted = today.get("report_submitted") is True

    name = household.get("name")
    code = household.get("code")
    if name and code:
        household_line = f"{esc(name)} ({esc(code)})"
    else:
        household_line = esc(name or code or EMPTY)

    def today_value(key: str, unit: str) -> str:
        # Hisobot topshirilmagan bo'lsa tuxum/yem qiymati yo'q (kontrakt: null).
        return fmt_quantity(today.get(key), unit) if submitted else EMPTY

    meat_today = [f"Bugun go‘sht: {fmt_quantity(today.get('meat_kg'), 'kg')}"] if _has_meat(today.get("meat_kg")) else []
    meat_week = [f"Go‘sht: {fmt_quantity(week.get('meat_kg'), 'kg')}"] if _has_meat(week.get("meat_kg")) else []
    return "\n".join([
        "📊 <b>NNP — XONADON HISOBOTI</b>",
        "",
        f"Xonadon: {household_line}",
        f"Sana: {_report_date(summary)}",
        "",
        f"Parranda soni: {fmt_quantity(summary.get('bird_count'), 'dona')}",
        "Bugungi hisobot: " + ("✅ topshirilgan" if submitted else "❌ topshirilmagan"),
        f"Bugun tuxum: {today_value('eggs', 'dona')}",
        f"Bugun yem: {today_value('feed_kg', 'kg')}",
        *meat_today,
        f"Bugun nobud: {fmt_quantity(today.get('deaths'), 'dona')}",
        "",
        f"<b>Oxirgi 7 kun</b> ({fmt_date(week.get('date_from'))} – {fmt_date(week.get('date_to'))})",
        f"Tuxum: {fmt_quantity(week.get('eggs'), 'dona')}",
        f"Tuxumdorlik: {fmt_percent(week.get('laying_rate_pct'))}",
        f"Yem: {fmt_quantity(week.get('feed_kg'), 'kg')}",
        *meat_week,
        f"Nobud: {fmt_quantity(week.get('deaths'), 'dona')}",
        # Kiritilgan = kutilgan kunlardan hisobot borlari (Web App «Hisobot intizomi» bilan bir xil).
        f"Hisobotlar: {_ratio(_first(week, 'reported', 'reports'), week.get('expected'))}",
    ])


def staff_report_text(summary: Mapping[str, Any]) -> str:
    today = _section(summary, "today")
    return "\n".join([
        "📊 <b>NNP — BUGUNGI HOLAT</b>",
        "",
        f"Sana: {_report_date(summary)}",
        "",
        # Maxraj: bugun hisobot kutilgan xonadonlar (faol, parrandasi bor) — /stats grafigi bilan bir xil.
        "Hisobot topshirgan xonadonlar: "
        f"{_ratio(today.get('households_reported'), _first(today, 'households_expected', 'households_active'))} "
        f"({fmt_percent(today.get('report_discipline_pct'))})",
        f"Tuxum: {fmt_quantity(today.get('eggs'), 'dona')}",
        f"Tuxumdorlik: {fmt_percent(today.get('laying_rate_pct'))}",
        f"Yem sarfi: {fmt_quantity(today.get('feed_kg'), 'kg')}",
        *([f"Go‘sht: {fmt_quantity(today.get('meat_kg'), 'kg')}"] if _has_meat(today.get("meat_kg")) else []),
        *_death_lines(today),
        f"Jami parranda: {fmt_quantity(today.get('birds_total'), 'dona')}",
        f"  xonadonlarda: {fmt_number(today.get('birds_in_households'))} · "
        f"markazda: {fmt_number(today.get('birds_in_center'))}",
        f"Kam qolgan mahsulotlar: {fmt_quantity(today.get('low_stock_count'), 'ta')}",
    ])


def logistics_report_text(summary: Mapping[str, Any]) -> str:
    """LOGISTICS (API_CONTRACT_V3 §10.3, §14.4)."""
    today = _section(summary, "today")
    return "\n".join([
        "📊 <b>NNP — LOGISTIKA HOLATI</b>",
        f"Sana: {_report_date(summary)}",
        f"Mening faol topshiriqlarim: {fmt_number(today.get('my_active'))}",
        f"  yo‘lda: {fmt_number(today.get('my_in_transit'))}",
        f"Biriktirilmagan yangi: {fmt_number(today.get('new_unassigned'))}",
        f"Muddati o‘tgan: {fmt_number(today.get('overdue'))}",
        f"Bugun yetkazildi: {fmt_number(today.get('delivered_today'))}",
        f"Tasdiq kutilmoqda: {fmt_number(today.get('awaiting_confirmation'))}",
    ])


def vet_report_text(summary: Mapping[str, Any]) -> str:
    """VET (API_CONTRACT_V3 §10.3, §14.4)."""
    today = _section(summary, "today")
    return "\n".join([
        "📊 <b>NNP — VETERINARIYA HOLATI</b>",
        f"Sana: {_report_date(summary)}",
        f"Bugungi tekshiruvlar: {fmt_number(today.get('visits_today'))}",
        f"Muddati o‘tgan tekshiruvlar: {fmt_number(today.get('visits_overdue'))}",
        f"7 kun ichida emlash: {fmt_number(today.get('vaccinations_due_7d'))}",
        f"Muddati o‘tgan emlash: {fmt_number(today.get('vaccinations_overdue'))}",
        f"Ochiq kasalliklar: {fmt_number(today.get('open_diseases'))}",
        f"Yangi murojaatlar: {fmt_number(today.get('new_requests'))}",
    ])


def report_text(summary: Mapping[str, Any]) -> str:
    """Rolga mos matn: ``role`` — backend qaytargan samarali rol."""
    role = summary.get("role")
    if role == OWNER:
        return owner_report_text(summary)
    if role == LOGISTICS:
        return logistics_report_text(summary)
    if role == VET:
        return vet_report_text(summary)
    return staff_report_text(summary)


def report_webapp_markup(summary: Mapping[str, Any]) -> Optional[types.InlineKeyboardMarkup]:
    """«🔎 Web App orqali ko‘rish»: OWNER -> ``/my``, xodimlar -> ``/stats`` (faqat https ``WEBAPP_URL``)."""
    if not config.WEBAPP_ENABLED:
        return None
    path = ROLE_WEBAPP_PATHS.get(str(summary.get("role")), STAFF_WEBAPP_PATH)
    return webapp_button_markup(WEBAPP_BUTTON_TEXT, f"{config.WEBAPP_URL}{path}")


@dp.message_handler(commands="reports", chat_type=PRIVATE)
@dp.message_handler(text=BTN_REPORTS, chat_type=PRIVATE)
async def bot_reports(message: types.Message) -> None:
    user = await require_user(message)
    if user is None:
        return

    try:
        summary: UserSummary = await api.get_summary(message.from_user.id)
    except NotFound:
        await message.answer(NOT_LINKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return
    except Forbidden as exc:
        # Bloklangan yoki xonadon biriktirilmagan: backend matni aynan ko'rsatiladi.
        await message.answer(f"⚠️ {esc(exc.detail)}")
        return
    # Unavailable va boshqa ApiError lar umumiy xatolik handleriga (handlers/errors/api_errors.py) uzatiladi.

    markup = report_webapp_markup(summary)
    await message.answer(report_text(summary), reply_markup=markup or main_menu(user["role"]))
