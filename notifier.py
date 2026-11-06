"""Background loop that delivers the backend's notification queue to Telegram (ARCHITECTURE_V2 §5, §7).

Every ``interval`` seconds: GET bot/notifications/pending, send each text (HTML) with a Web App button
to its ``button_path``, then POST bot/notifications/{id}/result {ok, error}.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
from aiogram import Bot
from aiogram.utils.exceptions import NetworkError, RestartingTelegram, RetryAfter, TelegramAPIError

import keyboards as kb
from api import ApiError, BotApi

log = logging.getLogger(__name__)

BUTTON_TEXT = "📂 Ochish"


class TelegramDown(Exception):
    """No connection to Telegram: stop this pass, keep the rest PENDING, back off."""


class Notifier:
    def __init__(
        self,
        bot: Bot,
        api: BotApi,
        *,
        interval: float = 5.0,
        limit: int = 50,
        max_attempts: int = 5,
        max_backoff: float = 60.0,
    ) -> None:
        self.bot = bot
        self.api = api
        self.interval = interval
        self.limit = limit
        self.max_attempts = max_attempts
        self.max_backoff = max_backoff
        # Sent (or refused) by Telegram but the result did not reach the backend: never re-send, only re-report.
        self._unreported: dict[int, tuple[bool, Optional[str]]] = {}
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run())
            log.info("Notifier started")

    async def stop(self, timeout: float = 15.0) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=timeout)
        except asyncio.TimeoutError:
            pass
        self._task = None
        log.info("Notifier stopped")

    async def _sleep(self, seconds: float) -> bool:
        """Waits ``seconds``; returns True at once when a stop was requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _run(self) -> None:
        delay = self.interval
        while not self._stop.is_set():
            try:
                await self.process_once()
                delay = self.interval
            except (ApiError, TelegramDown) as exc:
                delay = min(max(delay * 2, self.interval), self.max_backoff)
                log.warning("Notifier: %s; next try in %.0f s", exc, delay)
            except Exception:  # the loop must never die
                log.exception("Notifier: unexpected error")
                delay = min(max(delay * 2, self.interval), self.max_backoff)
            if await self._sleep(delay):
                break

    # --------------------------------------------------------------- one pass

    async def process_once(self) -> int:
        """Delivers one batch; returns how many results were reported.

        Raises ApiError (backend down) or TelegramDown so the loop backs off.
        """
        for nid, (ok, error) in list(self._unreported.items()):
            await self._report(nid, ok, error)

        reported = 0
        for item in await self.api.pending_notifications(limit=self.limit):
            if self._stop.is_set():
                break
            nid = int(item["id"])
            if nid in self._unreported:
                continue
            ok, error = await self.deliver(item)
            await self._report(nid, ok, error)
            reported += 1
        return reported

    async def deliver(self, item: dict) -> tuple[bool, Optional[str]]:
        """Sends one notification. Returns (ok, error); raises TelegramDown on network failure."""
        chat_id = item.get("chat_id") or item.get("telegram_id")
        if not chat_id:
            return False, "telegram_id yo‘q"
        markup = kb.webapp_button(BUTTON_TEXT, item.get("button_path") or "/")
        error = "RetryAfter"
        for _ in range(self.max_attempts):
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=item.get("text") or "",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=markup,
                )
                return True, None
            except RetryAfter as exc:
                error = f"RetryAfter: {exc.timeout} s"
                log.warning("Telegram flood limit: waiting %s s (notification #%s)", exc.timeout, item["id"])
                if await self._sleep(float(exc.timeout)):
                    raise TelegramDown("stopping during RetryAfter")  # leave it PENDING
            except (NetworkError, RestartingTelegram, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise TelegramDown(f"Telegram unreachable: {type(exc).__name__}") from exc
            except TelegramAPIError as exc:  # BotBlocked, ChatNotFound, UserDeactivated, BadRequest ...
                log.info("Notification #%s not delivered: %s", item["id"], exc)
                return False, f"{type(exc).__name__}: {exc}"
        return False, error

    async def _report(self, nid: int, ok: bool, error: Optional[str]) -> None:
        self._unreported[nid] = (ok, error)
        try:
            await self.api.report_notification(nid, ok, error)
        except ApiError as exc:
            if exc.temporary:
                raise  # keep it in _unreported and back off
            log.warning("Result of notification #%s was refused: %s", nid, exc)
        self._unreported.pop(nid, None)
