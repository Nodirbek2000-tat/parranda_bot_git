"""Topshiriq tugmalari va dalil / muammo bosqichlari (API_CONTRACT_V3 §14.2).

Tugmalar (callback ``t:<amal>:<id>``):

- ``acc`` ✅ Qabul qilish, ``go`` 🛻 Yo‘lga chiqdim — darhol ``POST bot/tasks/{id}/accept|start``;
- ``dlv`` 📦 Yetkazdim (foto bilan) — ``DeliveryProof.photo``: rasm (yoki JPG/PNG/WEBP/PDF hujjat) → Telegramdan
  yuklab olish → ``POST bot/files`` (``DELIVERY_PROOF``) → ``POST bot/tasks/{id}/deliver``;
- ``cnf`` ✅ Qabul qildim — ``confirm`` (``received_ok=true``);
- ``iss`` ⚠️ Muammo bor — ``DeliveryIssue.note``: qisqa matn → ``confirm`` (``received_ok=false``).

Muvaffaqiyatda xabar tahrirlanadi (yangi holat, yangi tugmalar) va callback «Bajarildi ✅» bilan javob oladi.
``400/403/404/409`` — server matni ko‘rsatiladi va xabar ``/tasks`` ma'lumoti bo‘yicha yangilanadi.
Bot hech narsani o‘zi hal qilmaydi: rol, xonadon egasi va holatni har safar server tekshiradi.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional, Union

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.utils.exceptions import TelegramAPIError

from data import config
from keyboards.default.menu import main_menu
from loader import api, bot, dp
from states import DeliveryIssue, DeliveryProof
from utils.api import ApiError, LogisticsTaskShort
from utils.logistics_tasks import (
    ACCEPT,
    CALLBACK_ACTIONS,
    DELIVER,
    ISSUE,
    MAX_TASKS,
    START,
    alert_text,
    find_task,
    parse_callback,
    task_markup,
    task_text,
)
from utils.misc import rate_limit

from .common import BLOCKED_TEXT, MUST_CHANGE_PASSWORD_TEXT, NOT_LINKED_TEXT, PRIVATE, esc, fetch_user

log = logging.getLogger(__name__)

DONE_TEXT = "Bajarildi ✅"
INVALID_BUTTON_TEXT = "Bu tugma eskirgan yoki noto‘g‘ri. Ro‘yxatni /tasks orqali yangilang."
WRONG_STATUS_TEXT = "Topshiriq holati: {status}. Bu amalni bajarib bo‘lmaydi."
NOT_ACTIVE_TEXT = "Bu topshiriq faol ro‘yxatda yo‘q: u allaqachon bajarilgan yoki bekor qilingan."

PROOF_PROMPT = "Yetkazib berish dalili: mahsulot yoki imzo rasmini yuboring (bekor qilish: /cancel)"
PROOF_BAD_TYPE = "Faqat JPG, PNG, WEBP rasm yoki PDF fayl yuborish mumkin."
PROOF_TOO_BIG = "Fayl hajmi 10 MB dan oshmasligi kerak."
PROOF_DOWNLOAD_FAILED = "Faylni Telegramdan olib bo‘lmadi."
PROOF_BUSY = "⏳ Dalil yuklanmoqda, biroz kuting."
PROOF_DONE = "✅ <b>{code}</b> — {status}. Xonadon egasining tasdig‘i kutilmoqda."

ISSUE_PROMPT = "Muammoni qisqacha yozing (3–1000 belgi). Bekor qilish: /cancel"
ISSUE_LENGTH = "Muammo matni 3 dan 1000 belgigacha bo‘lishi kerak."
ISSUE_BUSY = "⏳ Yuborilmoqda, biroz kuting."
ISSUE_DONE = "⚠️ <b>{code}</b> — muammo qayd etildi. Ma’lumot administratorga yuborildi."

RETRY_SUFFIX = "Qayta urinib ko‘ring yoki /cancel."

PROOF_PURPOSE = "DELIVERY_PROOF"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # backenddagi MAX_UPLOAD_BYTES (V3 §4.2)
ISSUE_MIN, ISSUE_MAX = 3, 1000
#: Hujjat sifatida yuborilgan fayllar: MIME -> kengaytma (backend kengaytma va baytlarni ham tekshiradi).
DOCUMENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
#: Foydalanuvchi qayta urinib ko‘rishi mumkin bo‘lgan javoblar (bosqich davom etadi).
#: ``0`` — aloqa yo‘q, ``429`` — cheklov, ``5xx`` — server xatosi, ``400`` — fayl yoki matn noto‘g‘ri.
_FINAL_STATUSES = (403, 404, 409)
_HANDLED_STATUSES = (400, *_FINAL_STATUSES)

#: Albom (bir nechta rasm) yuborilganda qolgan rasmlar menyuga tushmasin: user -> oxirgi ``media_group_id``.
_recent_media_groups: dict[int, str] = {}


def _webapp() -> str:
    return config.WEBAPP_URL if config.WEBAPP_ENABLED else ""


def _retryable(exc: ApiError) -> bool:
    return exc.status not in _FINAL_STATUSES


# ---------------------------------------------------------------- message helpers


async def show_task(chat_id: int, message_id: int, task: LogisticsTaskShort, role: str) -> None:
    """Topshiriq xabarini yangi holat va server ruxsat bergan tugmalar bilan qayta chizadi."""
    try:
        await bot.edit_message_text(
            task_text(task), chat_id, message_id, reply_markup=task_markup(task, role, _webapp())
        )
    except TelegramAPIError as exc:  # MessageNotModified, xabar o‘chirilgan va h.k.
        log.info("Topshiriq xabarini tahrirlab bo‘lmadi: %s", exc)


async def refresh_task(chat_id: int, message_id: int, telegram_id: int, task_id: int, role: str) -> None:
    """``/tasks`` ma'lumotidan xabarni yangilaydi; topshiriq ro‘yxatda bo‘lmasa amal tugmalari olib tashlanadi."""
    try:
        payload = await api.get_tasks(telegram_id)
    except ApiError as exc:
        log.info("Topshiriqni yangilab bo‘lmadi: %s", exc)
        return
    task = find_task(payload, task_id)
    if task is not None:
        await show_task(chat_id, message_id, task, role)
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id, message_id, reply_markup=task_markup({"id": task_id}, role, _webapp(), with_actions=False)
        )
    except TelegramAPIError as exc:
        log.info("Tugmalarni olib tashlab bo‘lmadi: %s", exc)


async def _clear_step_for(state: FSMContext, task_id: int) -> None:
    """Shu topshiriq uchun ochiq dalil/muammo bosqichi bo‘lsa yopiladi (amal boshqa tugma orqali bajarildi)."""
    current = await state.get_state()
    if current in (DeliveryProof.photo.state, DeliveryIssue.note.state):
        if (await state.get_data()).get("task_id") == task_id:
            await state.finish()


def _list_is_complete(payload: dict) -> bool:
    """``/tasks`` ro‘yxatlari (LOGISTICS ``tasks``, OWNER ``deliveries_to_confirm``) kesilmaganmi."""
    lists = [payload[key] for key in ("tasks", "deliveries_to_confirm") if isinstance(payload.get(key), list)]
    return bool(lists) and all(len(rows) < MAX_TASKS for rows in lists)


# ---------------------------------------------------------------- callbacks


@dp.callback_query_handler(text_startswith="t:", state="*")
async def task_button(call: types.CallbackQuery, state: FSMContext) -> None:
    parsed = parse_callback(call.data)
    if parsed is None or call.message is None or call.message.chat.type != types.ChatType.PRIVATE:
        await call.answer(INVALID_BUTTON_TEXT, show_alert=True)
        return
    code, task_id = parsed
    user = await fetch_user(call.from_user.id)
    if user is None:
        await call.answer(alert_text(NOT_LINKED_TEXT), show_alert=True)
        return
    if not user.get("is_active", True):
        await call.answer(BLOCKED_TEXT, show_alert=True)
        return
    if user.get("must_change_password"):
        await call.answer(alert_text(MUST_CHANGE_PASSWORD_TEXT), show_alert=True)
        return
    role = user["role"]
    if code in (DELIVER, ISSUE):
        await _begin_step(call, state, role, code, task_id)
        return

    telegram_id = call.from_user.id
    chat_id, message_id = call.message.chat.id, call.message.message_id
    try:
        if code == ACCEPT:
            task = await api.accept_task(telegram_id, task_id)
        elif code == START:
            task = await api.start_task(telegram_id, task_id)
        else:
            task = await api.confirm_task(telegram_id, task_id, received_ok=True)
    except ApiError as exc:
        if exc.status not in _HANDLED_STATUSES:
            raise  # aloqa yo‘q / 429 / 5xx — umumiy xatolik handleri (alert)
        await call.answer(alert_text(exc.detail), show_alert=True)
        await refresh_task(chat_id, message_id, telegram_id, task_id, role)
        return
    await _clear_step_for(state, task_id)
    await show_task(chat_id, message_id, task, role)
    await call.answer(DONE_TEXT)


async def _begin_step(call: types.CallbackQuery, state: FSMContext, role: str, code: str, task_id: int) -> None:
    """``dlv`` / ``iss``: amal hozir ruxsat etilganini tekshirib, rasm yoki matn bosqichini ochadi."""
    action = CALLBACK_ACTIONS[code]
    telegram_id = call.from_user.id
    chat_id, message_id = call.message.chat.id, call.message.message_id
    try:
        payload = await api.get_tasks(telegram_id)
    except ApiError as exc:
        if exc.status not in _HANDLED_STATUSES:
            raise
        await call.answer(alert_text(exc.detail), show_alert=True)
        return
    task = find_task(payload, task_id)
    if task is not None and action not in (task.get("allowed_actions") or []):
        status = task.get("status_display") or task.get("status") or ""
        await call.answer(alert_text(WRONG_STATUS_TEXT.format(status=status)), show_alert=True)
        await show_task(chat_id, message_id, task, role)
        return
    if task is None and _list_is_complete(payload):
        # Ro‘yxat to‘liq (10 tadan kam), topshiriq unda yo‘q — demak u allaqachon bajarilgan yoki bekor qilingan.
        await call.answer(NOT_ACTIVE_TEXT, show_alert=True)
        await refresh_task(chat_id, message_id, telegram_id, task_id, role)
        return
    # Ro‘yxat kesilgan bo‘lsa (10 ta) bosqich ochiladi — yakuniy tekshiruv baribir serverda.
    step = DeliveryProof.photo if code == DELIVER else DeliveryIssue.note
    await state.set_state(step.state)
    await state.set_data({
        "task_id": task_id,
        "code": (task or {}).get("code") or "",
        "chat_id": chat_id,
        "message_id": message_id,
        "role": role,
    })
    await call.answer()
    title = f"<b>{esc(task['code'])}</b>\n" if task and task.get("code") else ""
    if code == DELIVER:
        await call.message.answer(f"📦 {title}{PROOF_PROMPT}")
    else:
        await call.message.answer(f"⚠️ {title}{ISSUE_PROMPT}")


# ---------------------------------------------------------------- delivery proof (photo step)


@dataclass(frozen=True)
class Proof:
    file_id: str
    filename: str
    content_type: str
    size: Optional[int]


def pick_proof(message: types.Message) -> Union[Proof, str, None]:
    """Xabardan dalil faylini tanlaydi: ``Proof``; noto‘g‘ri fayl — xato matni; rasm/hujjat emas — ``None``."""
    if message.photo:
        fitting = [size for size in message.photo if (size.file_size or 0) <= MAX_UPLOAD_BYTES]
        if not fitting:
            return PROOF_TOO_BIG
        best = max(fitting, key=lambda size: (size.width or 0) * (size.height or 0))
        return Proof(best.file_id, f"dalil_{message.message_id}.jpg", "image/jpeg", best.file_size)
    document = message.document
    if document:
        mime = (document.mime_type or "").lower()
        if mime not in DOCUMENT_TYPES:
            return PROOF_BAD_TYPE
        if (document.file_size or 0) > MAX_UPLOAD_BYTES:
            return PROOF_TOO_BIG
        name = (document.file_name or "").strip()[-100:]
        if not any(name.lower().endswith(ext) for ext in _EXTENSIONS):
            name = f"dalil_{message.message_id}{DOCUMENT_TYPES[mime]}"
        return Proof(document.file_id, name, mime, document.file_size)
    return None


async def download_file(file_id: str) -> bytes:
    """Telegram serveridan faylni xotiraga yuklab oladi (testlarda almashtiriladi)."""
    buffer = io.BytesIO()
    await bot.download_file_by_id(file_id, destination=buffer)
    return buffer.getvalue()


@dp.message_handler(state=DeliveryProof.photo, content_types=types.ContentType.ANY, chat_type=PRIVATE)
@rate_limit(0, "delivery_proof")
async def delivery_proof(message: types.Message, state: FSMContext) -> None:
    proof = pick_proof(message)
    if proof is None:
        await message.answer(PROOF_PROMPT)
        return
    if isinstance(proof, str):
        await message.answer(f"⚠️ {proof}\n{PROOF_PROMPT}")
        return

    # Bosqich darhol band qilinadi: albomdagi qolgan rasmlar yoki ikkinchi yuborish qayta yuklanmaydi.
    await state.set_state(DeliveryProof.uploading.state)
    await state.update_data(media_group_id=message.media_group_id or "")
    data = await state.get_data()
    if message.media_group_id:
        _recent_media_groups[message.from_user.id] = message.media_group_id
    telegram_id = message.from_user.id
    role = data.get("role") or ""
    task_id = int(data["task_id"])
    finished = False
    try:
        try:
            content = await download_file(proof.file_id)
        except TelegramAPIError as exc:
            log.warning("Dalil faylini Telegramdan olib bo‘lmadi: %s", exc)
            await message.answer(f"⚠️ {PROOF_DOWNLOAD_FAILED} {RETRY_SUFFIX}")
            return
        if len(content) > MAX_UPLOAD_BYTES:
            await message.answer(f"⚠️ {PROOF_TOO_BIG}\n{PROOF_PROMPT}")
            return
        try:
            uploaded = await api.upload_file(telegram_id, PROOF_PURPOSE, proof.filename, content, proof.content_type)
            task = await api.deliver_task(telegram_id, task_id, [uploaded["id"]])
        except ApiError as exc:
            if _retryable(exc):
                await message.answer(f"⚠️ {esc(exc.detail)}\n{RETRY_SUFFIX}")
                return
            finished = True
            await state.finish()
            await message.answer(f"⚠️ {esc(exc.detail)}", reply_markup=main_menu(role))
            await refresh_task(data["chat_id"], data["message_id"], telegram_id, task_id, role)
            return
        finished = True
        await state.finish()
        await show_task(data["chat_id"], data["message_id"], task, role)
        await message.answer(
            PROOF_DONE.format(code=esc(task.get("code", "")), status=esc(task.get("status_display", ""))),
            reply_markup=main_menu(role),
        )
    finally:
        # Xato bo‘lsa (yoki kutilmagan istisno) — foydalanuvchi qayta rasm yuborishi mumkin bo‘lsin.
        if not finished and await state.get_state() == DeliveryProof.uploading.state:
            await state.set_state(DeliveryProof.photo.state)


@dp.message_handler(state=DeliveryProof.uploading, content_types=types.ContentType.ANY, chat_type=PRIVATE)
@rate_limit(0, "delivery_proof")
async def delivery_proof_busy(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    if message.media_group_id and message.media_group_id == data.get("media_group_id"):
        return  # shu albomning qolgan rasmlari
    await message.answer(PROOF_BUSY)


def _same_album(message: types.Message) -> bool:
    group = message.media_group_id
    return bool(group) and _recent_media_groups.get(message.from_user.id) == group


@dp.message_handler(
    _same_album, state=None, content_types=[types.ContentType.PHOTO, types.ContentType.DOCUMENT], chat_type=PRIVATE
)
@rate_limit(0, "delivery_proof")
async def delivery_album_rest(message: types.Message) -> None:
    """Dalil yuborilgan albomning qolgan rasmlari — jim o‘tkazib yuboriladi (menyu chiqmaydi)."""


# ---------------------------------------------------------------- owner issue (text step)


@dp.message_handler(state=DeliveryIssue.note, content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def delivery_issue(message: types.Message, state: FSMContext) -> None:
    text = (message.text or "").strip() if message.content_type == types.ContentType.TEXT else ""
    if not text or message.is_command():
        await message.answer(ISSUE_PROMPT)
        return
    if not ISSUE_MIN <= len(text) <= ISSUE_MAX:
        await message.answer(f"⚠️ {ISSUE_LENGTH}\n{ISSUE_PROMPT}")
        return

    await state.set_state(DeliveryIssue.sending.state)
    data = await state.get_data()
    telegram_id = message.from_user.id
    role = data.get("role") or ""
    task_id = int(data["task_id"])
    finished = False
    try:
        try:
            task = await api.confirm_task(telegram_id, task_id, received_ok=False, issue_note=text)
        except ApiError as exc:
            if _retryable(exc):
                await message.answer(f"⚠️ {esc(exc.detail)}\n{RETRY_SUFFIX}")
                return
            finished = True
            await state.finish()
            await message.answer(f"⚠️ {esc(exc.detail)}", reply_markup=main_menu(role))
            await refresh_task(data["chat_id"], data["message_id"], telegram_id, task_id, role)
            return
        finished = True
        await state.finish()
        await show_task(data["chat_id"], data["message_id"], task, role)
        await message.answer(ISSUE_DONE.format(code=esc(task.get("code", ""))), reply_markup=main_menu(role))
    finally:
        if not finished and await state.get_state() == DeliveryIssue.sending.state:
            await state.set_state(DeliveryIssue.note.state)


@dp.message_handler(state=DeliveryIssue.sending, content_types=types.ContentType.ANY, chat_type=PRIVATE)
async def delivery_issue_busy(message: types.Message) -> None:
    await message.answer(ISSUE_BUSY)
