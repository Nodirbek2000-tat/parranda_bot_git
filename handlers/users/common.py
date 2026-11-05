"""Foydalanuvchi handlerlari uchun umumiy matnlar va yordamchi funksiyalar."""
from __future__ import annotations

from html import escape
from typing import Optional

from aiogram import types

from data import config
from keyboards.default.menu import main_menu
from keyboards.inline.webapp import platform_markup
from loader import api
from utils.api import BotUser, NotFound
from utils.roles import OWNER, household_code, role_name

PRIVATE = types.ChatType.PRIVATE

NOT_LINKED_TEXT = (
    "Siz hali tizimga kirmagansiz.\n"
    "Kirish uchun /start buyrug‘ini yuboring."
)
BLOCKED_TEXT = "Hisobingiz bloklangan. Administratorga murojaat qiling."
WEBAPP_NOT_CONFIGURED_TEXT = "ℹ️ Platforma havolasi hali sozlanmagan."
PLATFORM_PROMPT_TEXT = "Platformani Telegram ichida oching:"
MUST_CHANGE_PASSWORD_TEXT = (
    "⚠️ Sizda vaqtinchalik parol. Bot amallaridan foydalanish uchun avval platformaga kirib, "
    "parolingizni almashtiring."
)

HELP_TEXT = (
    "<b>Buyruqlar</b>\n"
    "/start — tizimga kirish\n"
    "/menu — asosiy menyu\n"
    "/profile — mening profilim\n"
    "/tasks — mening topshiriqlarim\n"
    "/notifications — oxirgi bildirishnomalar\n"
    "/reports — hisobot va statistika\n"
    "/settings — bildirishnoma sozlamalari\n"
    "/help — yordam\n"
    "/cancel — joriy amalni bekor qilish\n"
    "/logout — tizimdan chiqish\n\n"
    "Bot NNP platformasidagi muhim voqealar haqida xabar beradi. "
    "«📊 Hisobot» tugmasi bugungi statistikani, «🔔 Bildirishnomalar» esa oxirgi xabarlarni ko‘rsatadi. "
    "«📋 Topshiriqlar» — faol ishlar: logistika xodimi topshiriqni qabul qiladi, yo‘lga chiqadi va "
    "yetkazganini rasm bilan tasdiqlaydi; xonadon egasi mahsulotni qabul qilganini tasdiqlaydi. "
    "Xonadon egalari «📍 Lokatsiyani yuborish» tugmasi orqali xonadon joylashuvini yuborishi mumkin."
)


def esc(value: object) -> str:
    """Foydalanuvchi kiritgan qiymatni HTML uchun xavfsiz qiladi."""
    return escape(str(value), quote=False)


async def fetch_user(telegram_id: int) -> Optional[BotUser]:
    """Bog'langan foydalanuvchini qaytaradi; bog'lanmagan bo'lsa ``None``.

    ``Unavailable`` va boshqa backend xatolari umumiy xatolik handleriga uzatiladi.
    """
    try:
        return await api.get_user(telegram_id)
    except NotFound:
        return None


def greeting_text(user: BotUser) -> str:
    return (
        f"Assalomu alaykum, <b>{esc(user['full_name'])}</b>!\n"
        f"Rolingiz: {esc(role_name(user['role']))}."
    )


def profile_text(user: BotUser) -> str:
    lines = [
        "<b>👤 Profil</b>",
        "",
        f"F.I.Sh.: {esc(user['full_name'])}",
        f"Login: <code>{esc(user['username'])}</code>",
        f"Rol: {esc(role_name(user['role']))}",
    ]
    if user.get("phone"):
        lines.append(f"Telefon: {esc(user['phone'])}")
    if user["role"] == OWNER and user.get("household_id"):
        lines.append(f"Xonadon kodi: {household_code(int(user['household_id']))}")
    if user.get("must_change_password"):
        lines += ["", "⚠️ Platformaga kirib, vaqtinchalik parolingizni almashtiring."]
    return "\n".join(lines)


async def send_main_menu(message: types.Message, user: BotUser, text: Optional[str] = None) -> None:
    """Asosiy menyu: rolga mos reply klaviatura va (sozlangan bo'lsa) platforma tugmasi."""
    body = text or greeting_text(user)
    if user.get("must_change_password"):
        body = f"{body}\n\n{MUST_CHANGE_PASSWORD_TEXT}"
    if not config.WEBAPP_ENABLED:
        body = f"{body}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}"
    await message.answer(body, reply_markup=main_menu(user["role"]))
    if config.WEBAPP_ENABLED:
        await message.answer(PLATFORM_PROMPT_TEXT, reply_markup=platform_markup(config.WEBAPP_URL))


async def require_user(message: types.Message, *, allow_temp_password: bool = False) -> Optional[BotUser]:
    """Faol, bog'langan foydalanuvchini qaytaradi; aks holda tushuntirish yuborib ``None`` qaytaradi.

    Vaqtinchalik parolli foydalanuvchi (``must_change_password``) faqat ``allow_temp_password=True``
    bo'lgan buyruqlardan (profil, menyu, chiqish) foydalana oladi — backend ham qolganlarini 403 bilan rad etadi.
    """
    user = await fetch_user(message.from_user.id)
    if user is None:
        await message.answer(NOT_LINKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return None
    if not user.get("is_active", True):
        await message.answer(BLOCKED_TEXT, reply_markup=types.ReplyKeyboardRemove())
        return None
    if user.get("must_change_password") and not allow_temp_password:
        await send_password_prompt(message)
        return None
    return user


async def send_password_prompt(message: types.Message) -> None:
    """Vaqtinchalik parol haqida ogohlantirish va (sozlangan bo'lsa) platforma tugmasi."""
    if config.WEBAPP_ENABLED:
        await message.answer(MUST_CHANGE_PASSWORD_TEXT, reply_markup=platform_markup(config.WEBAPP_URL))
    else:
        await message.answer(f"{MUST_CHANGE_PASSWORD_TEXT}\n\n{WEBAPP_NOT_CONFIGURED_TEXT}")
