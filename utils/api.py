"""Backend (Django) ning bot uchun mo'ljallangan endpointlari bilan ishlovchi asinxron klient.

Kontrakt: docs/API_CONTRACT.md, 3-bo'lim, "Bot-only endpoints"; docs/API_CONTRACT_V2.md, 5.1 (summary).
Barcha yo'llar oxirida "/" belgisisiz, har bir so'rovda ``X-Bot-Token`` sarlavhasi yuboriladi.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, TypedDict

import aiohttp

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0

UNAVAILABLE_MESSAGE = "Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring."
SERVER_ERROR_MESSAGE = "Serverda xatolik yuz berdi. Birozdan keyin urinib ko‘ring."
THROTTLED_MESSAGE = "Urinishlar soni juda ko‘p. Birozdan keyin qayta urinib ko‘ring."

_DEFAULT_DETAILS: dict[int, str] = {
    400: "So‘rov ma’lumotlari noto‘g‘ri.",
    403: "Bu amal uchun ruxsat yo‘q.",
    404: "Ma’lumot topilmadi.",
    409: "Amalni bajarib bo‘lmadi: ma’lumotlar ziddiyati.",
}


# ---------------------------------------------------------------- data shapes


class BotUser(TypedDict):
    id: int
    username: str
    first_name: str
    last_name: str
    full_name: str
    phone: str
    role: str
    is_active: bool
    must_change_password: bool
    telegram_linked: bool
    household_id: Optional[int]
    date_joined: str


class LocationHousehold(TypedDict):
    id: int
    code: str
    name: str
    latitude: Optional[float]
    longitude: Optional[float]


class SummaryHousehold(TypedDict):
    id: int
    code: str
    name: str


class OwnerSummaryToday(TypedDict):
    report_submitted: bool
    eggs: Optional[int]
    feed_kg: Optional[float]
    deaths: int


class OwnerSummaryWeek(TypedDict):
    date_from: str
    date_to: str
    days: int
    reports: int
    reported: int
    expected: int
    eggs: int
    feed_kg: float
    deaths: int
    laying_rate_pct: Optional[float]


class StaffSummaryToday(TypedDict):
    households_active: int
    households_expected: int
    households_reported: int
    report_discipline_pct: Optional[float]
    eggs: int
    feed_kg: float
    laying_rate_pct: Optional[float]
    deaths: int
    deaths_center: int
    birds_in_households: int
    birds_in_center: int
    birds_total: int
    low_stock_count: int


class UserSummary(TypedDict, total=False):
    """``GET bot/users/{telegram_id}/summary``. OWNER: ``household``, ``bird_count``, ``today``, ``last_7d``;
    ADMIN / WAREHOUSE: faqat ``today`` (:class:`StaffSummaryToday`)."""

    role: str
    date: str
    generated_at: str
    household: SummaryHousehold
    bird_count: int
    today: Any  # OwnerSummaryToday | StaffSummaryToday
    last_7d: OwnerSummaryWeek


class PendingNotification(TypedDict):
    id: int
    chat_id: int
    text: str
    button_path: str


# ----------------------------------------------------------------- exceptions


class InboxNotification(TypedDict):
    """``GET bot/users/{tid}/notifications`` elementi (API_CONTRACT_V3 §14.1)."""

    id: int
    title: str
    body: str
    button_path: str
    created_at: str
    read_at: Optional[str]


class TaskHousehold(TypedDict):
    id: int
    code: str
    name: str


class LogisticsTaskShort(TypedDict, total=False):
    """``LogisticsTaskShort`` (API_CONTRACT_V3 §14.1): bot ``/tasks`` va task amallari javobi."""

    id: int
    code: str
    status: str
    status_display: str
    household: TaskHousehold
    address: str
    planned_date: Optional[str]
    is_overdue: bool
    order: Optional[dict[str, Any]]
    items_text: str
    vehicle_text: str
    driver_text: str
    allowed_actions: list[str]


class UploadedFile(TypedDict):
    """``POST bot/files`` javobi (V3 §4.2)."""

    id: int
    name: str
    content_type: str
    size: int
    purpose: str
    url: str
    created_at: str


class ApiError(Exception):
    """Backend xatoligi: HTTP status va foydalanuvchiga ko'rsatsa bo'ladigan o'zbekcha matn."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class NotFound(ApiError):
    """404 — foydalanuvchi (yoki obyekt) topilmadi."""


class Forbidden(ApiError):
    """403 — ruxsat yo'q (yoki X-Bot-Token noto'g'ri)."""


class TooManyRequests(ApiError):
    """429 — backend so'rovlarni cheklagan (throttling)."""


class Unavailable(ApiError):
    """Backend bilan aloqa yo'q: ulanish xatosi, timeout yoki 502/503/504."""

    def __init__(self, detail: str = UNAVAILABLE_MESSAGE) -> None:
        super().__init__(0, detail)


def _extract_detail(payload: Any) -> Optional[str]:
    """DRF xato javobidan birinchi odam o'qiy oladigan xabarni ajratib oladi."""
    if isinstance(payload, str):
        return payload or None
    if isinstance(payload, list):
        for item in payload:
            found = _extract_detail(item)
            if found:
                return found
        return None
    if isinstance(payload, dict):
        for key in ("detail", "non_field_errors"):
            if key in payload:
                found = _extract_detail(payload[key])
                if found:
                    return found
        for value in payload.values():
            found = _extract_detail(value)
            if found:
                return found
    return None


def error_for_status(status: int, payload: Any) -> ApiError:
    """HTTP status va javob tanasidan mos istisno obyektini yaratadi."""
    if status in (502, 503, 504):
        return Unavailable()
    if status == 429:
        return TooManyRequests(status, THROTTLED_MESSAGE)
    if status >= 500:
        return ApiError(status, SERVER_ERROR_MESSAGE)
    detail = _extract_detail(payload) or _DEFAULT_DETAILS.get(status, SERVER_ERROR_MESSAGE)
    if status == 404:
        return NotFound(status, detail)
    if status == 403:
        return Forbidden(status, detail)
    return ApiError(status, detail)


# --------------------------------------------------------------------- client


class BotApiClient:
    """Bitta umumiy ``aiohttp.ClientSession`` ishlatadigan yengil klient.

    Sessiya birinchi so'rovda yaratiladi va :meth:`close` orqali yopiladi.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    # -- lifecycle

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

    # -- transport

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.strip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        data: Optional[aiohttp.FormData] = None,
    ) -> Any:
        url = self._url(path)
        try:
            async with self._get_session().request(method, url, json=json, params=params, data=data) as response:
                try:
                    payload: Any = await response.json(content_type=None)
                except ValueError:
                    payload = None
                status = response.status
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("API %s %s: aloqa xatosi: %r", method, url, exc)
            raise Unavailable() from exc

        if status >= 400:
            error = error_for_status(status, payload)
            log.info("API %s %s -> %s", method, url, status)
            raise error
        return payload

    # -- endpoints

    async def get_user(self, telegram_id: int) -> BotUser:
        """``GET bot/users/{telegram_id}`` — bog'langan foydalanuvchi; bo'lmasa :class:`NotFound`."""
        return await self._request("GET", f"bot/users/{int(telegram_id)}")

    async def link(self, telegram_id: int, username: str, password: str) -> BotUser:
        """``POST bot/link`` — login/parol orqali Telegram akkauntni bog'lash."""
        body = {"telegram_id": int(telegram_id), "username": username, "password": password}
        return await self._request("POST", "bot/link", json=body)

    async def unlink(self, telegram_id: int) -> dict[str, Any]:
        """``POST bot/unlink`` — Telegram akkauntni tizimdan uzish."""
        return await self._request("POST", "bot/unlink", json={"telegram_id": int(telegram_id)})

    async def send_location(self, telegram_id: int, latitude: float, longitude: float) -> LocationHousehold:
        """``POST bot/location`` — xonadon koordinatalarini saqlash (faqat OWNER)."""
        body = {"telegram_id": int(telegram_id), "latitude": latitude, "longitude": longitude}
        payload = await self._request("POST", "bot/location", json=body)
        return payload["household"]

    async def get_summary(self, telegram_id: int) -> UserSummary:
        """``GET bot/users/{telegram_id}/summary`` — rolga mos bugungi statistika (keshlanmaydi).

        Xatolar: bog'lanmagan -> :class:`NotFound`; bloklangan yoki xonadonsiz OWNER -> :class:`Forbidden`.
        """
        payload = await self._request("GET", f"bot/users/{int(telegram_id)}/summary")
        if not isinstance(payload, dict) or not isinstance(payload.get("role"), str):
            raise ApiError(200, "Kutilmagan javob: summary obyekt emas yoki «role» yo‘q")
        return payload

    async def get_inbox(self, telegram_id: int, limit: int = 10) -> list[InboxNotification]:
        """``GET bot/users/{telegram_id}/notifications?limit=N`` — oxirgi bildirishnomalar (V3 §14.1)."""
        payload = await self._request(
            "GET", f"bot/users/{int(telegram_id)}/notifications", params={"limit": max(1, min(int(limit), 20))}
        )
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise ApiError(200, "Kutilmagan javob: bildirishnomalar ro‘yxati massiv emas")
        return payload

    async def pending_notifications(self, limit: int = 20) -> list[PendingNotification]:
        """``GET bot/notifications/pending?limit=N`` — yuborilishi kerak bo'lgan xabarlar."""
        payload = await self._request("GET", "bot/notifications/pending", params={"limit": int(limit)})
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise ApiError(200, "Kutilmagan javob: bildirishnomalar ro‘yxati massiv emas")
        return payload

    async def report_notification(self, notification_id: int, ok: bool, error: Optional[str] = None) -> str:
        """``POST bot/notifications/{id}/result`` — yuborish natijasi; yangi statusni qaytaradi."""
        body: dict[str, Any] = {"ok": ok}
        if not ok:
            body["error"] = (error or "Noma’lum xatolik")[:1000]
        payload = await self._request("POST", f"bot/notifications/{int(notification_id)}/result", json=body)
        return str((payload or {}).get("status", ""))

    async def get_tasks(self, telegram_id: int) -> dict[str, Any]:
        """``GET bot/users/{telegram_id}/tasks`` — rolga mos ``/tasks`` ma'lumoti (V3 §14.2)."""
        payload = await self._request("GET", f"bot/users/{int(telegram_id)}/tasks")
        if not isinstance(payload, dict):
            raise ApiError(200, "Kutilmagan javob: topshiriqlar obyekt emas")
        return payload

    # -- logistics task actions (V3 §14.1); the server re-checks role, owner and status every time

    async def _task_action(self, action: str, telegram_id: int, task_id: int, **body: Any) -> LogisticsTaskShort:
        payload = await self._request(
            "POST", f"bot/tasks/{int(task_id)}/{action}", json={"telegram_id": int(telegram_id), **body}
        )
        if not isinstance(payload, dict) or "status" not in payload:
            raise ApiError(200, "Kutilmagan javob: topshiriq obyekt emas")
        return payload

    async def accept_task(self, telegram_id: int, task_id: int) -> LogisticsTaskShort:
        """``POST bot/tasks/{id}/accept`` — ASSIGNED → ACCEPTED."""
        return await self._task_action("accept", telegram_id, task_id)

    async def start_task(self, telegram_id: int, task_id: int) -> LogisticsTaskShort:
        """``POST bot/tasks/{id}/start`` — ACCEPTED → IN_TRANSIT (ombordan chiqim shu paytda)."""
        return await self._task_action("start", telegram_id, task_id)

    async def deliver_task(
        self, telegram_id: int, task_id: int, file_ids: list[int], note: str = ""
    ) -> LogisticsTaskShort:
        """``POST bot/tasks/{id}/deliver`` — IN_TRANSIT → DELIVERED, dalil fayllari bilan."""
        return await self._task_action("deliver", telegram_id, task_id, file_ids=[int(i) for i in file_ids], note=note)

    async def confirm_task(
        self, telegram_id: int, task_id: int, *, received_ok: bool, issue_note: str = ""
    ) -> LogisticsTaskShort:
        """``POST bot/tasks/{id}/confirm`` — DELIVERED → CONFIRMED (``received_ok=False`` — muammo bilan)."""
        return await self._task_action(
            "confirm", telegram_id, task_id, received_ok=bool(received_ok), issue_note=issue_note
        )

    async def upload_file(
        self, telegram_id: int, purpose: str, filename: str, content: bytes, content_type: str
    ) -> UploadedFile:
        """``POST bot/files`` (multipart) — ``201 File``; tekshiruvlar (hajm, tur, rol) backendda (V3 §4.2)."""
        form = aiohttp.FormData()
        form.add_field("telegram_id", str(int(telegram_id)))
        form.add_field("purpose", purpose)
        form.add_field("file", content, filename=filename, content_type=content_type)
        payload = await self._request("POST", "bot/files", data=form)
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
            raise ApiError(200, "Kutilmagan javob: fayl obyekti yo‘q")
        return payload

    async def run_reminders(self) -> dict[str, Any]:
        """``POST bot/reminders/run`` — kunlik eslatmalar; qachon ishlashini server hal qiladi (V3 §14.5)."""
        payload = await self._request("POST", "bot/reminders/run", json={})
        return payload if isinstance(payload, dict) else {}
