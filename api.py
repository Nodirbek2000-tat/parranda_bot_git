"""Async client for the backend bot API (ARCHITECTURE_V2 §4, header X-Bot-Token)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

log = logging.getLogger(__name__)

UNAVAILABLE_TEXT = "Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring."
SERVER_ERROR_TEXT = "Serverda xatolik yuz berdi. Birozdan keyin urinib ko‘ring."
_DEFAULT_DETAILS = {
    400: "So‘rov ma’lumotlari noto‘g‘ri.",
    401: "Login yoki parol noto‘g‘ri.",
    403: "Bu amal uchun ruxsat yo‘q.",
    404: "Ma’lumot topilmadi.",
    429: "Urinishlar soni juda ko‘p. Birozdan keyin qayta urinib ko‘ring.",
}


class ApiError(Exception):
    """Backend error: HTTP status (0 = no connection) and an Uzbek message safe to show."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail

    @property
    def temporary(self) -> bool:
        """Worth retrying later: no connection, throttled or a server error."""
        return self.status in (0, 429) or self.status >= 500


class NotFound(ApiError):
    """404: the Telegram account is not linked (or the object does not exist)."""


class Unavailable(ApiError):
    def __init__(self) -> None:
        super().__init__(0, UNAVAILABLE_TEXT)


def _detail(payload: Any) -> Optional[str]:
    """First human-readable message from a DRF error body."""
    if isinstance(payload, str):
        return payload or None
    if isinstance(payload, list):
        return next((d for d in map(_detail, payload) if d), None)
    if isinstance(payload, dict):
        for key in ("detail", "non_field_errors"):
            if key in payload and _detail(payload[key]):
                return _detail(payload[key])
        return next((d for d in map(_detail, payload.values()) if d), None)
    return None


def error_for(status: int, payload: Any) -> ApiError:
    if status in (502, 503, 504):
        return Unavailable()
    if status >= 500:
        return ApiError(status, SERVER_ERROR_TEXT)
    detail = _detail(payload) or _DEFAULT_DETAILS.get(status, SERVER_ERROR_TEXT)
    return NotFound(status, detail) if status == 404 else ApiError(status, detail)


def as_list(payload: Any) -> list:
    """Accepts a plain list or a paginated/wrapped one ({"results": [...]} etc.)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "items", "tasks", "notifications"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


class BotApi:
    def __init__(self, base_url: str, token: str, *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={"X-Bot-Token": self._token, "Accept": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        url = f"{self._base_url}/{path.strip('/')}"
        try:
            async with self._get_session().request(method, url, json=json, params=params) as response:
                status = response.status
                try:
                    payload = await response.json(content_type=None)
                except ValueError:
                    payload = None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("API %s %s: no connection (%s)", method, path, type(exc).__name__)
            raise Unavailable() from exc
        if status >= 400:
            log.info("API %s %s -> %s", method, path, status)
            raise error_for(status, payload)
        return payload

    # -- endpoints (ARCHITECTURE_V2 §4, "Bot API")

    async def link(self, telegram_id: int, username: str, password: str) -> dict:
        body = {"telegram_id": int(telegram_id), "username": username, "password": password}
        return await self._request("POST", "bot/link", json=body)

    async def unlink(self, telegram_id: int) -> Any:
        return await self._request("POST", "bot/unlink", json={"telegram_id": int(telegram_id)})

    async def me(self, telegram_id: int) -> dict:
        """The linked user; raises NotFound when the account is not linked."""
        return await self._request("GET", f"bot/me/{int(telegram_id)}")

    async def tasks(self, telegram_id: int) -> list:
        return as_list(await self._request("GET", f"bot/tasks/{int(telegram_id)}"))

    async def pending_notifications(self, limit: int = 50) -> list:
        return as_list(await self._request("GET", "bot/notifications/pending", params={"limit": limit}))

    async def report_notification(self, notification_id: int, ok: bool, error: Optional[str] = None) -> Any:
        body: dict[str, Any] = {"ok": ok}
        if error:
            body["error"] = error[:500]
        return await self._request("POST", f"bot/notifications/{int(notification_id)}/result", json=body)
