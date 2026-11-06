"""Message texts and formatting (Uzbek, HTML)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Optional

ROLE_LABELS = {
    "SUPERADMIN": "Super Admin", "ADMIN": "Administrator", "INSPECTOR": "Inspektor", "HR": "HR",
    "DIRECTOR": "Direktor", "BUILDER": "Qurilish", "WAREHOUSE": "Omborchi", "INCUBATOR": "Inkubatsiya",
    "LOGISTICS": "Logistika", "VET": "Veterinar", "OWNER": "Xonadon egasi", "ACCOUNTANT": "Buxgalter",
}
STAGE_STATUS_LABELS = {
    "ACTIVE": "bajarish kerak",
    "RETURNED": "qaytarilgan, tuzatish kerak",
    "SUBMITTED": "tasdiqlash kutilmoqda",
}

ASK_LOGIN = (
    "Assalomu alaykum!\n"
    "Bu <b>NNP</b> platformasining boti.\n\n"
    "Tizimga kirish uchun <b>login</b>ingizni yuboring.\n"
    "Bekor qilish: /cancel"
)
NOT_LINKED = "Siz hali tizimga kirmagansiz. Kirish uchun /start buyrug‘ini yuboring."
WEBAPP_OFF = "ℹ️ Platforma havolasi hali sozlanmagan."
NO_TASKS = "✅ Hozircha sizni kutayotgan vazifa yo‘q. Yangi vazifa bo‘lsa, bot darhol xabar beradi."
LOGOUT_CONFIRM = "Tizimdan chiqmoqchimisiz?\nShundan so‘ng bot sizga xabarlar yubormaydi."
LOGOUT_DONE = "Siz tizimdan chiqdingiz. Qayta kirish uchun /start buyrug‘ini yuboring."
LOGOUT_CANCELLED = "Chiqish bekor qilindi."
TASKS_LIMIT = 20

HELP = (
    "<b>ℹ️ Yordam</b>\n\n"
    "Bot NNP platformasidagi vazifalaringiz haqida xabar beradi va platformani Telegram ichida ochadi.\n\n"
    "📋 <b>Vazifalarim</b> — hozir sizdan harakat kutayotgan xonadonlar\n"
    "🚀 <b>Platformani ochish</b> — Web App\n"
    "👤 <b>Profil</b> — hisobingiz ma’lumotlari\n"
    "🚪 <b>Chiqish</b> — Telegram akkauntni tizimdan uzish\n\n"
    "/start — tizimga kirish\n/menu — asosiy menyu\n/help — yordam\n/cancel — amalni bekor qilish"
)


def esc(value: Any) -> str:
    return escape(str(value), quote=False)


def _pick(data: Any, *keys: str) -> Any:
    """First non-empty value among ``keys`` (the bot tolerates small differences in the API shape)."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def fmt_datetime(value: Any) -> str:
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return esc(value)
    return moment.strftime("%d.%m.%Y %H:%M") if "T" in str(value) else moment.strftime("%d.%m.%Y")


def role_label(user: dict) -> str:
    return _pick(user, "role_display") or ROLE_LABELS.get(user.get("role", ""), user.get("role") or "—")


def greeting(user: dict) -> str:
    name = _pick(user, "full_name", "username") or ""
    text = f"Assalomu alaykum, <b>{esc(name)}</b>!\nRolingiz: {esc(role_label(user))}."
    if user.get("must_change_password"):
        text += "\n\n⚠️ Sizda vaqtinchalik parol. Platformaga kirib, parolingizni almashtiring."
    return text


def profile(user: dict) -> str:
    lines = [
        "<b>👤 Profil</b>",
        "",
        f"F.I.Sh.: {esc(_pick(user, 'full_name') or '—')}",
        f"Login: <code>{esc(_pick(user, 'username') or '—')}</code>",
        f"Rol: {esc(role_label(user))}",
    ]
    if user.get("phone"):
        lines.append(f"Telefon: {esc(user['phone'])}")
    if user.get("must_change_password"):
        lines += ["", "⚠️ Platformaga kirib, vaqtinchalik parolingizni almashtiring."]
    return "\n".join(lines)


def case_id(task: dict) -> Optional[int]:
    value = _pick(task, "id", "case_id")
    return int(value) if value is not None else None


KIND_ICONS = {"request": "📨", "visit": "🩺"}


def task_path(task: dict) -> Optional[str]:
    """Web App path of an item: its own ``path`` (requests, visits) or ``/cases/{id}``."""
    path = _pick(task, "path")
    if isinstance(path, str) and path.startswith("/"):
        return path
    cid = case_id(task)
    return f"/cases/{cid}" if cid is not None else None


def task(task: dict) -> str:
    """One item from GET /api/bot/tasks/{tid} as a short message.

    Cases accept flat fields (stage_number, stage_title, stage_status, due_at) or a nested ``stage`` object.
    Requests and visits (``kind`` = "request" / "visit") carry ``title`` and optionally code/name/due_at.
    """
    kind = _pick(task, "kind") or "case"
    if kind != "case":
        icon = KIND_ICONS.get(kind, "📌")
        code = _pick(task, "code") or ""
        name = _pick(task, "name", "household_name") or ""
        head = f"{icon} <b>{esc(_pick(task, 'title') or 'Vazifa')}</b>"
        lines = [head]
        if code or name:
            lines.append(esc(" — ".join(x for x in (code, name) if x)))
        status = _pick(task, "status_display", "status")
        if status:
            lines.append(f"Holat: {esc(status)}")
        due = _pick(task, "due_at", "planned_date")
        if due:
            overdue = bool(_pick(task, "is_overdue", "overdue"))
            lines.append(f"Muddat: {fmt_datetime(due)}" + (" 🔴 <b>muddati o‘tgan</b>" if overdue else ""))
        return "\n".join(lines)
    stage = task.get("stage") if isinstance(task.get("stage"), dict) else {}
    code = _pick(task, "code") or f"#{case_id(task)}"
    name = _pick(task, "name", "household_name", "household") or ""
    number = _pick(stage, "number") or _pick(task, "stage_number", "current_stage", "stage")
    title = _pick(stage, "title") or _pick(task, "stage_title", "stage_name")
    status = _pick(stage, "status") or _pick(task, "stage_status")
    due = _pick(stage, "due_at") or _pick(task, "due_at")
    overdue = bool(_pick(stage, "is_overdue") or _pick(task, "is_overdue", "overdue"))

    header = f"🐔 <b>{esc(code)}</b>" + (f" — {esc(name)}" if name else "")
    stage_text = f"{number}. {title}" if number and title else str(number or title or "")
    lines = [header]
    if stage_text:
        lines.append(f"Bosqich: {esc(stage_text)}")
    if status in STAGE_STATUS_LABELS:
        lines.append(f"Holat: {STAGE_STATUS_LABELS[status]}")
    if due:
        lines.append(f"Muddat: {fmt_datetime(due)}" + (" 🔴 <b>muddati o‘tgan</b>" if overdue else ""))
    return "\n".join(lines)
