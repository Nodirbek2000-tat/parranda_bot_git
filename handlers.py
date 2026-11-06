"""User handlers. The bot answers only in private chats.

Registration order matters in aiogram 2: commands with state="*" first, then the login states,
then the reply-menu buttons, and the fallback last.
"""
from __future__ import annotations

import logging
from typing import Optional

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.exceptions import MessageNotModified, TelegramAPIError

import config
import keyboards as kb
import texts
from api import ApiError, NotFound
from loader import api, dp

log = logging.getLogger(__name__)

PRIVATE = types.ChatType.PRIVATE
MAX_USERNAME = 150
MAX_PASSWORD = 128


class Login(StatesGroup):
    username = State()
    password = State()


# ------------------------------------------------------------------ helpers


async def linked_user(telegram_id: int) -> Optional[dict]:
    try:
        return await api.me(telegram_id)
    except NotFound:
        return None


async def require_user(message: types.Message) -> Optional[dict]:
    user = await linked_user(message.from_user.id)
    if user is None:
        await message.answer(texts.NOT_LINKED, reply_markup=kb.remove_keyboard)
    return user


async def send_menu(message: types.Message, user: dict, text: Optional[str] = None) -> None:
    body = text or texts.greeting(user)
    if not config.webapp_enabled():
        body += "\n\n" + texts.WEBAPP_OFF
    await message.answer(body, reply_markup=kb.main_menu())


async def _delete_quietly(message: types.Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as exc:
        log.warning("Could not delete the password message: %s", type(exc).__name__)


async def _edit_quietly(message: types.Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except MessageNotModified:
        pass
    except TelegramAPIError as exc:
        log.info("Could not edit the message: %s", type(exc).__name__)


# ----------------------------------------------------------------- commands


@dp.message_handler(commands="start", state="*", chat_type=PRIVATE)
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    await state.finish()
    user = await linked_user(message.from_user.id)
    if user is None:
        await state.set_state(Login.username)
        await message.answer(texts.ASK_LOGIN, reply_markup=kb.remove_keyboard)
        return
    await send_menu(message, user)


@dp.message_handler(commands="cancel", state="*", chat_type=PRIVATE)
async def cmd_cancel(message: types.Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Bekor qilinadigan amal yo‘q.")
        return
    await state.finish()
    user = await linked_user(message.from_user.id)
    if user is None:
        await message.answer("Amal bekor qilindi. Kirish uchun /start.", reply_markup=kb.remove_keyboard)
    else:
        await send_menu(message, user, text="Amal bekor qilindi.")


@dp.message_handler(commands="help", state="*", chat_type=PRIVATE)
@dp.message_handler(text=kb.BTN_HELP, chat_type=PRIVATE)
async def cmd_help(message: types.Message) -> None:
    await message.answer(texts.HELP)


@dp.message_handler(commands="menu", state="*", chat_type=PRIVATE)
async def cmd_menu(message: types.Message, state: FSMContext) -> None:
    await state.finish()
    user = await require_user(message)
    if user is not None:
        await send_menu(message, user)


# --------------------------------------------------------------- login flow


@dp.message_handler(state=Login.username, content_types=types.ContentType.TEXT, chat_type=PRIVATE)
async def login_username(message: types.Message, state: FSMContext) -> None:
    if message.is_command():
        await message.answer("Hozir tizimga kirish davom etmoqda. Loginni yuboring yoki /cancel.")
        return
    username = message.text.strip()
    if not username or len(username) > MAX_USERNAME or any(ch.isspace() for ch in username):
        await message.answer("Login noto‘g‘ri ko‘rinishda. Iltimos, loginni qayta yuboring.")
        return
    await state.update_data(username=username)
    await state.set_state(Login.password)
    await message.answer(
        f"Login: <code>{texts.esc(username)}</code>\n"
        "Endi <b>parol</b>ni yuboring.\n"
        "🔒 Xavfsizlik uchun parolli xabar darhol o‘chiriladi."
    )


@dp.message_handler(state=Login.password, content_types=types.ContentType.TEXT, chat_type=PRIVATE)
async def login_password(message: types.Message, state: FSMContext) -> None:
    password = message.text
    await _delete_quietly(message)  # first, unconditionally

    username = (await state.get_data()).get("username")
    if not username:
        await state.set_state(Login.username)
        await message.answer("Iltimos, avval loginni yuboring.")
        return
    if not password or len(password) > MAX_PASSWORD:
        await _ask_login_again(message, state, "Login yoki parol noto‘g‘ri.")
        return

    try:
        user = await api.link(message.from_user.id, username, password)
    except ApiError as exc:
        if exc.temporary:
            await state.finish()
            await message.answer(f"{texts.esc(exc.detail)}\nQayta urinish uchun /start.")
        else:
            await _ask_login_again(message, state, exc.detail)
        return

    await state.finish()
    await send_menu(message, user, text="✅ Tizimga muvaffaqiyatli kirdingiz.\n\n" + texts.greeting(user))


@dp.message_handler(state=[Login.username, Login.password], content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def login_not_text(message: types.Message) -> None:
    await message.answer("Iltimos, matn ko‘rinishida yuboring. Bekor qilish: /cancel.")


async def _ask_login_again(message: types.Message, state: FSMContext, detail: str) -> None:
    await state.set_data({})
    await state.set_state(Login.username)
    await message.answer(f"❌ {texts.esc(detail)}\n\nLoginni qayta yuboring yoki /cancel bilan bekor qiling.")


# --------------------------------------------------------------------- menu


@dp.message_handler(text=kb.BTN_TASKS, chat_type=PRIVATE)
async def menu_tasks(message: types.Message) -> None:
    try:
        tasks = await api.tasks(message.from_user.id)
    except NotFound:
        await message.answer(texts.NOT_LINKED, reply_markup=kb.remove_keyboard)
        return
    if not tasks:
        await message.answer(texts.NO_TASKS)
        return

    header = f"📋 <b>Vazifalarim</b>: {len(tasks)} ta"
    if not config.webapp_enabled():
        header += "\n" + texts.WEBAPP_OFF
    await message.answer(header)
    for item in tasks[: texts.TASKS_LIMIT]:
        path = texts.task_path(item)
        markup = kb.webapp_button(kb.OPEN_CASE_TEXT, path) if path else None
        await message.answer(texts.task(item), reply_markup=markup)
    rest = len(tasks) - texts.TASKS_LIMIT
    if rest > 0:
        await message.answer(
            f"… yana {rest} ta vazifa. Hammasini platformada ko‘ring.",
            reply_markup=kb.webapp_button(kb.OPEN_PLATFORM_TEXT, "/tasks"),
        )


@dp.message_handler(text=kb.BTN_PLATFORM, chat_type=PRIVATE)
async def menu_platform(message: types.Message) -> None:
    markup = kb.webapp_button(kb.OPEN_PLATFORM_TEXT, "/")
    if markup is None:
        await message.answer(texts.WEBAPP_OFF)
    else:
        await message.answer("Platformani Telegram ichida oching:", reply_markup=markup)


@dp.message_handler(text=kb.BTN_PROFILE, chat_type=PRIVATE)
async def menu_profile(message: types.Message) -> None:
    user = await require_user(message)
    if user is not None:
        await message.answer(texts.profile(user))


@dp.message_handler(text=kb.BTN_LOGOUT, chat_type=PRIVATE)
async def menu_logout(message: types.Message) -> None:
    user = await require_user(message)
    if user is not None:
        await message.answer(texts.LOGOUT_CONFIRM, reply_markup=kb.logout_confirm())


@dp.callback_query_handler(text=[kb.LOGOUT_YES, kb.LOGOUT_NO], state="*", chat_type=PRIVATE)
async def logout_answer(call: types.CallbackQuery) -> None:
    if call.data != kb.LOGOUT_YES:
        await _edit_quietly(call.message, texts.LOGOUT_CANCELLED)
        await call.answer()
        return
    try:
        await api.unlink(call.from_user.id)
    except NotFound:
        pass  # already unlinked: same result
    await _edit_quietly(call.message, "🚪 Chiqildi.")
    await call.message.answer(texts.LOGOUT_DONE, reply_markup=kb.remove_keyboard)
    await call.answer()


@dp.message_handler(content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def fallback(message: types.Message) -> None:
    await message.answer("Menyudagi tugmalardan foydalaning yoki /menu yuboring.")


# ------------------------------------------------------------------- errors


@dp.errors_handler(exception=ApiError)
async def api_error(update: types.Update, exception: ApiError) -> bool:
    """Backend unavailable or returned an error: tell the user instead of staying silent."""
    try:
        if update.callback_query:
            await update.callback_query.answer(exception.detail, show_alert=True)
        elif update.message:
            await update.message.answer(texts.esc(exception.detail))
    except TelegramAPIError:
        pass
    return True
