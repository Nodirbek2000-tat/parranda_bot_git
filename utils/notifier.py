"""Backend navbatidagi bildirishnomalarni Telegramga yetkazuvchi fon jarayoni.

Har ``interval`` soniyada ``GET bot/notifications/pending`` chaqiriladi, har bir xabar
yuboriladi va natija ``POST bot/notifications/{id}/result`` orqali qaytariladi.
Bitta muammoli xabar sikl ishini hech qachon to'xtatmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from enum import Enum
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.exceptions import NetworkError, RestartingTelegram, RetryAfter, TelegramAPIError

from keyboards.inline.webapp import WEBAPP_BUTTON_TEXT, webapp_button_markup
from utils.api import ApiError, BotApiClient, PendingNotification

log = logging.getLogger(__name__)

__all__ = ["Delivery", "NotificationWorker", "WEBAPP_BUTTON_TEXT"]


class Delivery(Enum):
    SENT = "sent"  # yuborildi -> ok=true
    FAILED = "failed"  # Telegram rad etdi -> ok=false
    DEFERRED = "deferred"  # RetryAfter: PENDING holatida qoladi
    TELEGRAM_DOWN = "telegram_down"  # Telegram bilan aloqa yo'q: aylanish to'xtatiladi


_STATUS_SUFFIX = re.compile(r"\[\d{3}\]$")


def is_telegram_server_error(exc: BaseException) -> bool:
    """Telegram'ning o'zi ishlamayapti (HTTP 5xx yoki "restarting"): xabar aybdor emas.

    aiogram 2 5xx javobni ``RestartingTelegram`` yoki **aynan** ``TelegramAPIError(description)`` qilib chiqaradi;
    boshqa (4xx) xatolar esa kichik sinf (``BadRequest``, ``Unauthorized`` …) yoki ``"… [NNN]"`` bilan tugaydi.
    """
    if isinstance(exc, RestartingTelegram):
        return True
    return type(exc) is TelegramAPIError and not _STATUS_SUFFIX.search(str(exc).strip())


class NotificationWorker:
    def __init__(
        self,
        bot: Bot,
        api: BotApiClient,
        webapp_url: str = "",
        *,
        interval: float = 3.0,
        batch_size: int = 20,
        send_delay: float = 0.05,
        max_backoff: float = 60.0,
        reminder_interval: float = 900.0,
    ) -> None:
        self._bot = bot
        self._api = api
        self._webapp_url = webapp_url.rstrip("/")
        self._interval = interval
        self._batch_size = batch_size
        self._send_delay = send_delay
        self._max_backoff = max_backoff
        # Eslatmalar tiki (V3 §14.5): har 15 daqiqada POST bot/reminders/run; qachon ishlashini server hal qiladi.
        self._reminder_interval = reminder_interval
        self._next_reminder_at = 0.0
        # Telegramga yuborilgan (yoki rad etilgan), lekin natijasi backendga yetmagan xabarlar.
        # Ular qayta jo'natilmaydi — faqat natija qayta yuboriladi.
        self._unreported: dict[int, tuple[bool, Optional[str]]] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()
        #: Oxirgi aylanishda Telegram ishlamadi (tarmoq yoki 5xx): sikl kutish vaqtini oshiradi.
        self.telegram_down = False

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="notification-worker")
        log.info("Bildirishnoma yuboruvchi ishga tushdi")

    async def stop(self, timeout: float = 15.0) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            pass  # wait_for vazifani o'zi bekor qiladi
        self._task = None
        log.info("Bildirishnoma yuboruvchi to‘xtatildi")

    async def _sleep(self, seconds: float) -> bool:
        """``seconds`` kutadi; to'xtatish so'ralsa darhol ``True`` qaytaradi."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return False
        return True

    def _next_backoff(self, delay: float) -> float:
        return min(max(delay * 2, self._interval), self._max_backoff)

    async def _run(self) -> None:
        delay = self._interval
        failing = False
        while not self._stop.is_set():
            await self.tick_reminders()
            try:
                await self.process_once()
            except ApiError as exc:
                if not failing:
                    log.warning("Bildirishnomalar navbati bilan ishlab bo‘lmadi: %s", exc)
                failing = True
                delay = self._next_backoff(delay)
            except Exception:  # sikl hech qachon yiqilmasligi kerak
                log.exception("Bildirishnoma siklida kutilmagan xatolik")
                delay = self._next_backoff(delay)
            else:
                if failing:
                    log.info("Backend bilan aloqa tiklandi")
                failing = False
                # Telegram ishlamasa urinishlar sarflanmaydi (xabar PENDING qoladi), lekin har 3 soniyada
                # urilmaslik uchun kutish 3 → 6 → … → max_backoff gacha oshadi.
                delay = self._next_backoff(delay) if self.telegram_down else self._interval
            if await self._sleep(delay):
                break

    # ------------------------------------------------------------ reminders

    async def tick_reminders(self, now: Optional[float] = None) -> Optional[dict]:
        """Har `reminder_interval` soniyada bir marta `POST bot/reminders/run`.

        Xatolik faqat jurnalga yoziladi — tik hech qachon siklni to'xtatmaydi. Natija (yoki `None`) qaytadi.
        """
        if self._reminder_interval <= 0:
            return None
        current = time.monotonic() if now is None else now
        if current < self._next_reminder_at:
            return None
        self._next_reminder_at = current + self._reminder_interval
        try:
            result = await self._api.run_reminders()
        except Exception as exc:  # noqa: BLE001 — eslatma xatosi bildirishnomalarni to'xtatmasin
            log.warning("Eslatmalarni ishga tushirib bo‘lmadi: %s", exc)
            return None
        if result.get("ran"):
            log.info("Kunlik eslatmalar: %s ta xabar navbatga qo‘yildi (%s)", result.get("queued", 0), result.get("date"))
        return result

    # ------------------------------------------------------------- one pass

    async def process_once(self) -> int:
        """Bitta aylanish: navbatni oladi va xabarlarni yuboradi.

        Natijasi aniq bo'lgan (yuborilgan yoki rad etilgan) xabarlar sonini qaytaradi.
        Backend xatoligi (:class:`ApiError`) chaqiruvchiga uzatiladi — sikl kutib turadi.
        """
        await self._flush_unreported()
        items = await self._api.pending_notifications(limit=self._batch_size)
        attempted = 0
        self.telegram_down = False
        for item in items:
            if self._stop.is_set():
                break
            if item["id"] in self._unreported:
                continue
            outcome, error = await self._deliver(item)
            if outcome is Delivery.TELEGRAM_DOWN:
                self.telegram_down = True
                break  # qolganlari keyingi aylanishda
            if outcome is Delivery.DEFERRED:
                continue  # PENDING holatida qoladi
            attempted += 1
            await self._report(item["id"], outcome is Delivery.SENT, error)
            if self._send_delay:
                await asyncio.sleep(self._send_delay)
        return attempted

    def _markup(self, button_path: str) -> Optional[InlineKeyboardMarkup]:
        if not self._webapp_url.startswith("https://") or not button_path:
            return None
        path = button_path if button_path.startswith("/") else f"/{button_path}"
        return webapp_button_markup(WEBAPP_BUTTON_TEXT, f"{self._webapp_url}{path}")

    async def _deliver(self, item: PendingNotification) -> tuple[Delivery, Optional[str]]:
        """Xabarni Telegramga yuboradi va natija turini qaytaradi."""
        try:
            await self._bot.send_message(
                chat_id=item["chat_id"],
                text=item["text"],
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=self._markup(item.get("button_path") or ""),
            )
        except RetryAfter as exc:
            log.warning("Telegram cheklovi: %s soniya kutiladi (xabar #%s)", exc.timeout, item["id"])
            await self._sleep(float(exc.timeout))
            return Delivery.DEFERRED, None
        except (NetworkError, asyncio.TimeoutError) as exc:
            log.warning("Telegram bilan aloqa yo‘q (xabar #%s): %s", item["id"], exc)
            return Delivery.TELEGRAM_DOWN, None
        except TelegramAPIError as exc:
            if is_telegram_server_error(exc):
                # TZ §11.3 "qayta yuborishga harakat qilsin": Telegram 5xx — urinish hisoblanmaydi.
                log.warning("Telegram serveri xatolik qaytardi (xabar #%s): %s", item["id"], exc)
                return Delivery.TELEGRAM_DOWN, None
            log.info("Xabar #%s yuborilmadi: %s", item["id"], exc)
            return Delivery.FAILED, f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 — bitta xabar siklni to'xtatmasin
            log.exception("Xabar #%s yuborishda kutilmagan xatolik", item["id"])
            return Delivery.FAILED, f"{type(exc).__name__}: {exc}"
        return Delivery.SENT, None

    async def _report(self, notification_id: int, ok: bool, error: Optional[str]) -> None:
        """Natijani backendga yuboradi.

        Backend vaqtincha ishlamasa natija eslab qolinadi (xabar qayta jo'natilmaydi)
        va xatolik yuqoriga uzatiladi.
        """
        self._unreported[notification_id] = (ok, error)
        try:
            await self._api.report_notification(notification_id, ok, error)
        except ApiError as exc:
            if exc.status in (0, 429) or exc.status >= 500:
                raise
            log.warning("Xabar #%s natijasi qabul qilinmadi: %s", notification_id, exc)
        self._unreported.pop(notification_id, None)

    async def _flush_unreported(self) -> None:
        for notification_id, (ok, error) in list(self._unreported.items()):
            await self._report(notification_id, ok, error)
