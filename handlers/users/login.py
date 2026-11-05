"""Login va parol orqali Telegram akkauntni tizimga bog'lash (FSM)."""
import logging

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.utils.exceptions import TelegramAPIError

from loader import api, dp
from states import LoginStates
from utils.api import ApiError, Forbidden, TooManyRequests, Unavailable
from utils.misc import rate_limit

from .common import PRIVATE, esc, greeting_text, send_main_menu

log = logging.getLogger(__name__)

LOGIN_STATES = [LoginStates.username, LoginStates.password]
MAX_USERNAME_LENGTH = 150
MAX_PASSWORD_LENGTH = 128  # backenddagi LinkSerializer.password chegarasi

# Parol bosqichida "/" bilan boshlangan matn ham parol bo'lishi mumkin. Faqat shu buyruqlar
# parol deb hisoblanmaydi (/start, /cancel, /help esa oldinroq ro'yxatdan o'tgan handlerlarga tushadi).
NAVIGATION_COMMANDS = frozenset({"menu", "profile", "reports", "logout"})

IN_PROGRESS_TEXT = "Hozir tizimga kirish jarayoni davom etmoqda. Bekor qilish uchun /cancel yuboring."
RETRY_LATER_SUFFIX = "\nQayta urinish uchun /start buyrug‘ini yuboring."
BAD_CREDENTIALS_TEXT = "Login yoki parol noto‘g‘ri"


@dp.message_handler(state=LoginStates.username, content_types=types.ContentType.TEXT, chat_type=PRIVATE)
async def login_username(message: types.Message, state: FSMContext) -> None:
    if message.is_command():
        await message.answer(IN_PROGRESS_TEXT)
        return

    username = message.text.strip()
    if not username or len(username) > MAX_USERNAME_LENGTH or any(ch.isspace() for ch in username):
        await message.answer("Login noto‘g‘ri ko‘rinishda. Iltimos, loginni qayta yuboring.")
        return

    await state.update_data(username=username)
    await LoginStates.password.set()
    await message.answer(
        f"Login: <code>{esc(username)}</code>\n"
        "Endi <b>parol</b>ni yuboring.\n"
        "🔒 Xavfsizlik uchun parolli xabar darhol o‘chiriladi."
    )


# rate_limit(0): throttling middleware parolli xabarni o'chirilishidan oldin to'xtatib qolmasin.
@dp.message_handler(state=LoginStates.password, content_types=types.ContentType.TEXT, chat_type=PRIVATE)
@rate_limit(0, "login_password")
async def login_password(message: types.Message, state: FSMContext) -> None:
    # Parolli xabar hech qanday shartsiz birinchi navbatda o'chiriladi.
    password = message.text
    await _delete_quietly(message)

    if message.get_command(pure=True) in NAVIGATION_COMMANDS:
        await message.answer(IN_PROGRESS_TEXT)
        return

    username = (await state.get_data()).get("username")
    if not username:
        await LoginStates.username.set()
        await message.answer("Iltimos, avval loginni yuboring.")
        return

    if not password or len(password) > MAX_PASSWORD_LENGTH:
        await _ask_again(state, BAD_CREDENTIALS_TEXT, message)
        return

    try:
        user = await api.link(message.from_user.id, username, password)
    except Unavailable as exc:
        await state.finish()
        await message.answer(exc.detail + RETRY_LATER_SUFFIX)
        return
    except (Forbidden, TooManyRequests) as exc:
        await state.finish()
        await message.answer(esc(exc.detail) + RETRY_LATER_SUFFIX)
        return
    except ApiError as exc:
        if exc.status >= 500:
            await state.finish()
            await message.answer(esc(exc.detail) + RETRY_LATER_SUFFIX)
            return
        await _ask_again(state, exc.detail, message)
        return

    await state.finish()
    await send_main_menu(message, user, text=f"✅ Tizimga muvaffaqiyatli kirdingiz.\n\n{greeting_text(user)}")


@dp.message_handler(state=LOGIN_STATES, content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def login_unexpected(message: types.Message) -> None:
    await message.answer("Iltimos, matn ko‘rinishida yuboring. Bekor qilish uchun /cancel.")


async def _ask_again(state: FSMContext, detail: str, message: types.Message) -> None:
    """Login bosqichiga qaytaradi (oldingi login unutiladi)."""
    await state.set_data({})
    await LoginStates.username.set()
    await message.answer(
        f"❌ {esc(detail)}\n\n"
        "Loginni qayta yuboring yoki /cancel bilan bekor qiling."
    )


async def _delete_quietly(message: types.Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as exc:
        log.warning("Parolli xabarni o‘chirib bo‘lmadi: %s", type(exc).__name__)
