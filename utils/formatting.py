"""Telegram matnlari uchun formatlash: ``2 800``, ``310.5``, ``81.2%``, ``04.11.2026``; ``None`` -> ``—``.

Qoidalar backenddagi ``common/formatting.py`` (Phase 1 formatter) bilan bir xil:
minglik ajratuvchi — bo'shliq, kasr qismining oxiridagi nollar tashlanadi.
Foizlar doim 1 xona kasr bilan (``ROUND_HALF_UP``) — docs/API_CONTRACT_V2.md, 1- va 5-bo'limlar.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

EMPTY = "—"

# Asia/Tashkent: UTC+5, yozgi vaqt yo'q (1992 yildan beri). Windows'da tzdata o'rnatilmagan bo'lishi mumkin,
# shuning uchun zoneinfo o'rniga qat'iy siljish ishlatiladi.
TASHKENT_TZ = timezone(timedelta(hours=5), name="Asia/Tashkent")

_ONE_DECIMAL = Decimal("0.1")


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Son (int/float/Decimal yoki sonli satr) -> chekli ``Decimal``; aks holda ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _group(integer_part: int) -> str:
    return f"{integer_part:,}".replace(",", " ")


def fmt_number(value: Any) -> str:
    """``2800`` -> ``2 800``, ``310.50`` -> ``310.5``, ``380.0`` -> ``380``, ``None`` -> ``—``."""
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    sign = "-" if number < 0 else ""
    number = abs(number)
    integer_part = int(number)
    text = _group(integer_part)
    fraction = number - integer_part
    if fraction:
        text = f"{text}.{format(fraction.normalize(), 'f').split('.')[1]}"
    return f"{sign}{text}"


def fmt_percent(value: Any) -> str:
    """Foiz 1 xona kasr bilan: ``81.25`` -> ``81.3%``, ``80`` -> ``80.0%``, ``None`` -> ``—``."""
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    number = number.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    number = abs(number)
    integer_part = int(number)
    tenths = int((number - integer_part) * 10)
    return f"{sign}{_group(integer_part)}.{tenths}%"


def fmt_fixed(value: Any, places: int = 2) -> str:
    """Belgilangan xona kasr bilan (``ROUND_HALF_UP``): ``1.8`` -> ``1.80`` (FCR); ``None`` -> ``—``."""
    number = _to_decimal(value)
    if number is None:
        return EMPTY
    number = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    number = abs(number)
    integer_part = int(number)
    text = _group(integer_part)
    if places > 0:
        text = f"{text}.{format(number, 'f').split('.')[1]}"
    return f"{sign}{text}"


def fmt_quantity(value: Any, unit: str) -> str:
    """Son va o'lchov birligi: ``2 800 dona``; qiymat yo'q bo'lsa birliksiz ``—``."""
    text = fmt_number(value)
    return text if text == EMPTY else f"{text} {unit}"


def parse_date(value: Any) -> Optional[date]:
    """ISO sana (``2026-11-04``) yoki ``date``/``datetime`` -> ``date``; noto'g'ri bo'lsa ``None``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def fmt_date(value: Any) -> str:
    """``2026-11-04`` -> ``04.11.2026``; noto'g'ri qiymat -> ``—``."""
    parsed = parse_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed else EMPTY


def local_today() -> date:
    """Toshkent vaqti bo'yicha bugungi sana."""
    return datetime.now(TASHKENT_TZ).date()


def fmt_datetime(value: Any) -> str:
    """ISO datetime -> ``04.11.2026 18:20`` (Toshkent vaqti); noto'g'ri qiymat -> ``—``."""
    if not isinstance(value, str) or not value.strip():
        return EMPTY
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return EMPTY
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(TASHKENT_TZ)
    return parsed.strftime("%d.%m.%Y %H:%M")
