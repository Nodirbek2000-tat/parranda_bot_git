"""``/tasks`` matnlari: VET va ADMIN (API_CONTRACT_V3 §14.2) — bitta xulosa xabari + Web App tugmalari.

Ma'lumot ``GET bot/users/{tid}/tasks`` javobidan olinadi; barcha qiymatlar HTML uchun escape qilinadi.
"""
from __future__ import annotations

from html import escape
from typing import Any, Iterable

from utils.formatting import fmt_date, fmt_number, local_today

TITLE = "📋 <b>Mening topshiriqlarim</b>"
NOTHING_TODAY = "Bugun uchun rejalashtirilgan ish yo‘q ✅"
MAX_LINES = 10


def _esc(value: Any) -> str:
    return escape(str(value), quote=False)


def _household(item: dict[str, Any]) -> str:
    household = item.get("household") or {}
    name = household.get("name") or ""
    code = household.get("code") or ""
    return f"{name} ({code})" if code else name


def _visit_line(item: dict[str, Any], *, with_date: bool) -> str:
    parts = [f"<b>{_esc(item.get('code', ''))}</b> — {_esc(_household(item))}"]
    purpose = (item.get("purpose") or "").strip()
    if purpose:
        parts.append(_esc(purpose[:80]))
    if with_date:
        parts.append(fmt_date(item.get("planned_date")))
    if not item.get("vet"):
        parts.append("biriktirilmagan")
    return "• " + " · ".join(parts)


def _vaccination_line(item: dict[str, Any]) -> str:
    parts = [f"<b>{_esc(item.get('code', ''))}</b> — {_esc(item.get('vaccine_name', ''))}", _esc(_household(item))]
    parts.append(fmt_date(item.get("planned_date")))
    if item.get("birds_planned"):
        parts.append(f"{fmt_number(item['birds_planned'])} bosh")
    if not item.get("vet"):
        parts.append("biriktirilmagan")
    return "• " + " · ".join(parts)


def _section(title: str, lines: Iterable[str]) -> list[str]:
    lines = list(lines)
    if not lines:
        return []
    shown = lines[:MAX_LINES]
    block = [f"{title} ({len(lines)})", *shown]
    return ["", *block]


def vet_tasks_text(payload: dict[str, Any]) -> str:
    """VET: bugungi va muddati o‘tgan tekshiruvlar, bugun/ertaga emlashlar, yangi murojaatlar."""
    day = payload.get("date") or local_today().isoformat()
    lines = [TITLE, f"Sana: {fmt_date(day)}"]
    body: list[str] = []
    body += _section("🩺 <b>Bugungi tekshiruvlar</b>",
                     (_visit_line(item, with_date=False) for item in payload.get("visits_today") or []))
    body += _section("⚠️ <b>Muddati o‘tgan tekshiruvlar</b>",
                     (_visit_line(item, with_date=True) for item in payload.get("visits_overdue") or []))
    body += _section("💉 <b>Bugun va ertaga emlash</b>",
                     (_vaccination_line(item) for item in payload.get("vaccinations_due") or []))
    body += _section("⏰ <b>Muddati o‘tgan emlashlar</b>",
                     (_vaccination_line(item) for item in payload.get("vaccinations_overdue") or []))
    new_requests = int(payload.get("new_requests") or 0)
    if new_requests:
        body += ["", f"📨 Yangi murojaatlar: <b>{fmt_number(new_requests)}</b>"]
    if not body:
        body = ["", NOTHING_TODAY]
    return "\n".join(lines + body)


def admin_tasks_text(payload: dict[str, Any]) -> str:
    """ADMIN: yangi buyurtmalar, yetkazib berish holati va muddati o‘tgan veterinariya ishlari."""
    lines = [TITLE, f"Sana: {fmt_date(local_today())}", ""]
    orders = payload.get("orders_new") or []
    count = int(payload.get("orders_new_count") or len(orders))
    lines.append(f"🛒 Yangi buyurtmalar: <b>{fmt_number(count)}</b>")
    for order in orders[:MAX_LINES]:
        text = f"• <b>{_esc(order.get('code', ''))}</b> — {_esc(_household(order))}"
        if order.get("items_text"):
            text += f" · {_esc(order['items_text'])}"
        lines.append(text)
    deliveries = payload.get("deliveries") or {}
    lines += [
        "",
        "🚚 Yetkazib berish: "
        f"yo‘lda {fmt_number(deliveries.get('in_transit') or 0)} · "
        f"yetkazildi {fmt_number(deliveries.get('delivered') or 0)} · "
        f"muddati o‘tgan {fmt_number(deliveries.get('overdue') or 0)}",
        f"🩺 Muddati o‘tgan veterinariya ishlari: <b>{fmt_number(payload.get('vet_overdue') or 0)}</b>",
    ]
    return "\n".join(lines)
