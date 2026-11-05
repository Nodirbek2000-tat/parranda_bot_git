"""Bot API klienti va bildirishnoma yuboruvchi uchun testlar.

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer
from aiogram.utils.exceptions import BotBlocked, ChatNotFound, NetworkError, RetryAfter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.api import (  # noqa: E402
    SERVER_ERROR_MESSAGE,
    UNAVAILABLE_MESSAGE,
    ApiError,
    BotApiClient,
    Forbidden,
    NotFound,
    TooManyRequests,
    Unavailable,
)
from utils.notifier import WEBAPP_BUTTON_TEXT, NotificationWorker  # noqa: E402

logging.disable(logging.CRITICAL)

TOKEN = "test-bot-api-token"
WEBAPP = "https://app.example.test"

OWNER_TG = 111
ADMIN_TG = 222
BLOCKED_USERNAME = "blocked"


WAREHOUSE_TG = 444


def owner_summary() -> dict[str, Any]:
    """docs/API_CONTRACT_V2.md 5.1 dagi OWNER namunasi."""
    return {
        "role": "OWNER", "date": "2026-11-04", "generated_at": "2026-11-04T18:20:05+05:00",
        "household": {"id": 3, "code": "XN-0003", "name": "Navbahor 12-uy"},
        "bird_count": 497,
        "today": {"report_submitted": True, "feed_kg": 55.5, "meat_kg": 62.5, "avg_weight_g": 1850.0, "deaths": 3},
        "last_7d": {"date_from": "2026-10-29", "date_to": "2026-11-04", "days": 7, "reports": 6, "reported": 6, "expected": 7,
                    "feed_kg": 380.0, "meat_kg": 210.5, "fcr": 1.81, "avg_weight_g": 1840.5, "deaths": 5},
    }


def staff_summary(role: str = "ADMIN") -> dict[str, Any]:
    """docs/API_CONTRACT_V2.md 5.1 dagi ADMIN / WAREHOUSE namunasi."""
    return {
        "role": role, "date": "2026-11-04", "generated_at": "2026-11-04T18:20:05+05:00",
        "today": {"households_active": 11, "households_expected": 10, "households_reported": 8,
                  "report_discipline_pct": 80.0, "feed_kg": 310.5, "meat_kg": 172.5, "fcr": 1.8,
                  "deaths": 3, "deaths_center": 1,
                  "birds_in_households": 5400, "birds_in_center": 1500, "birds_total": 6900,
                  "low_stock_count": 1},
    }


def make_user(user_id: int, username: str, role: str, household_id: Optional[int]) -> dict[str, Any]:
    return {
        "id": user_id, "username": username, "first_name": "Bobur", "last_name": "Aliyev",
        "full_name": "Bobur Aliyev", "phone": "+998901234567", "role": role, "is_active": True,
        "must_change_password": False, "telegram_linked": True, "household_id": household_id,
        "date_joined": "2026-11-04T10:00:00+05:00",
    }


class FakeBackend:
    """Kontraktdagi bot endpointlarini taqlid qiluvchi kichik aiohttp ilova."""

    def __init__(self) -> None:
        self.users: dict[int, dict[str, Any]] = {
            OWNER_TG: make_user(7, "aliyev", "OWNER", 3),
            ADMIN_TG: make_user(1, "admin", "ADMIN", None),
            WAREHOUSE_TG: make_user(2, "ombor", "WAREHOUSE", None),
        }
        # telegram_id -> summary javobi; ``summary_error`` = (status, body) bo'lsa xato qaytariladi.
        self.summaries: dict[int, Any] = {
            OWNER_TG: owner_summary(),
            ADMIN_TG: staff_summary("ADMIN"),
            WAREHOUSE_TG: staff_summary("WAREHOUSE"),
        }
        self.summary_error: Optional[tuple[int, Any]] = None
        self.notifications: dict[int, dict[str, Any]] = {}
        self.results: list[tuple[int, dict[str, Any]]] = []
        self.paths: list[str] = []
        self.fail_results_with: Optional[int] = None
        self.pending_paginated = False

        self.app = web.Application(middlewares=[self.check_token])
        self.app.router.add_get("/api/bot/users/{telegram_id}", self.get_user)
        self.app.router.add_get("/api/bot/users/{telegram_id}/summary", self.summary)
        self.app.router.add_post("/api/bot/link", self.link)
        self.app.router.add_post("/api/bot/unlink", self.unlink)
        self.app.router.add_post("/api/bot/location", self.location)
        self.app.router.add_get("/api/bot/notifications/pending", self.pending)
        self.app.router.add_post("/api/bot/notifications/{id}/result", self.result)
        self.app.router.add_get("/api/bot/boom", self.boom)
        self.app.router.add_get("/api/bot/down", self.down)

    def add_notification(self, notification_id: int, chat_id: int, button_path: str = "") -> None:
        self.notifications[notification_id] = {
            "id": notification_id, "chat_id": chat_id, "text": f"<b>NNP</b> #{notification_id}",
            "button_path": button_path, "status": "PENDING", "attempts": 0,
        }

    @web.middleware
    async def check_token(self, request: web.Request, handler: Any) -> web.StreamResponse:
        self.paths.append(request.path)
        if request.headers.get("X-Bot-Token") != TOKEN:
            return web.json_response({"detail": "Bot token noto‘g‘ri"}, status=403)
        return await handler(request)

    async def get_user(self, request: web.Request) -> web.Response:
        user = self.users.get(int(request.match_info["telegram_id"]))
        if user is None:
            return web.json_response({"detail": "Topilmadi."}, status=404)
        return web.json_response(user)

    async def summary(self, request: web.Request) -> web.Response:
        if self.summary_error is not None:
            status, body = self.summary_error
            if isinstance(body, str):
                return web.Response(status=status, text=body)
            return web.json_response(body, status=status)
        telegram_id = int(request.match_info["telegram_id"])
        user = self.users.get(telegram_id)
        if user is None:
            return web.json_response({"detail": "Foydalanuvchi topilmadi"}, status=404)
        if not user["is_active"]:
            return web.json_response(
                {"detail": "Hisobingiz bloklangan. Administratorga murojaat qiling."}, status=403
            )
        return web.json_response(self.summaries[telegram_id])

    async def link(self, request: web.Request) -> web.Response:
        body = await request.json()
        if body["username"] == BLOCKED_USERNAME:
            return web.json_response(
                {"detail": "Hisobingiz bloklangan. Administratorga murojaat qiling."}, status=403
            )
        if body["username"] != "aliyev" or body["password"] != "correct-pass":
            return web.json_response({"detail": "Login yoki parol noto‘g‘ri"}, status=400)
        user = make_user(7, "aliyev", "OWNER", 3)
        self.users[int(body["telegram_id"])] = user
        return web.json_response(user)

    async def unlink(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.users.pop(int(body["telegram_id"]), None)
        return web.json_response({"detail": "Telegram uzildi"})

    async def location(self, request: web.Request) -> web.Response:
        body = await request.json()
        user = self.users.get(int(body["telegram_id"]))
        if user is None:
            return web.json_response({"detail": "Topilmadi."}, status=404)
        if not user["is_active"]:
            return web.json_response(
                {"detail": "Hisobingiz bloklangan. Administratorga murojaat qiling."}, status=403
            )
        if user["role"] != "OWNER":
            return web.json_response({"detail": "Lokatsiyani faqat xonadon egasi yubora oladi"}, status=403)
        return web.json_response({"household": {
            "id": 3, "code": "XN-0003", "name": "Navbahor 12-uy",
            "latitude": body["latitude"], "longitude": body["longitude"],
        }})

    async def pending(self, request: web.Request) -> web.Response:
        if self.pending_paginated:
            return web.json_response({"count": 0, "next": None, "previous": None, "results": []})
        limit = int(request.query.get("limit", "20"))
        items = [
            {k: n[k] for k in ("id", "chat_id", "text", "button_path")}
            for n in sorted(self.notifications.values(), key=lambda n: n["id"])
            if n["status"] == "PENDING" and n["attempts"] < 5
        ]
        return web.json_response(items[:limit])

    async def result(self, request: web.Request) -> web.Response:
        if self.fail_results_with is not None:
            return web.json_response({"detail": "xato"}, status=self.fail_results_with)
        notification = self.notifications.get(int(request.match_info["id"]))
        if notification is None:
            return web.json_response({"detail": "Topilmadi."}, status=404)
        body = await request.json()
        self.results.append((notification["id"], body))
        if body["ok"]:
            notification["status"] = "SENT"
        else:
            notification["attempts"] += 1
            notification["status"] = "FAILED" if notification["attempts"] >= 5 else "PENDING"
        return web.json_response({"status": notification["status"]})

    async def boom(self, request: web.Request) -> web.Response:
        return web.Response(status=500, text="<h1>Server Error</h1>", content_type="text/html")

    async def down(self, request: web.Request) -> web.Response:
        return web.Response(status=503, text="Service Unavailable")


class BackendTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.backend = FakeBackend()
        self.server = TestServer(self.backend.app)
        await self.server.start_server()
        self.base_url = str(self.server.make_url("/api"))
        self.api = BotApiClient(self.base_url, TOKEN, timeout=5)

    async def asyncTearDown(self) -> None:
        await self.api.close()
        await self.server.close()


class ApiClientTests(BackendTestCase):
    async def test_get_user_linked(self) -> None:
        user = await self.api.get_user(OWNER_TG)
        self.assertEqual(user["role"], "OWNER")
        self.assertEqual(user["household_id"], 3)
        self.assertEqual(self.backend.paths, [f"/api/bot/users/{OWNER_TG}"])

    async def test_get_user_unknown_raises_not_found(self) -> None:
        with self.assertRaises(NotFound) as ctx:
            await self.api.get_user(999)
        self.assertEqual(ctx.exception.status, 404)

    async def test_wrong_token_raises_forbidden(self) -> None:
        bad = BotApiClient(self.base_url, "wrong")
        try:
            with self.assertRaises(Forbidden) as ctx:
                await bad.get_user(OWNER_TG)
            self.assertEqual(ctx.exception.detail, "Bot token noto‘g‘ri")
        finally:
            await bad.close()

    async def test_link_success_and_bad_credentials(self) -> None:
        user = await self.api.link(333, "aliyev", "correct-pass")
        self.assertEqual(user["username"], "aliyev")

        with self.assertRaises(ApiError) as ctx:
            await self.api.link(333, "aliyev", "wrong")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.detail, "Login yoki parol noto‘g‘ri")
        self.assertNotIsInstance(ctx.exception, (NotFound, Forbidden, Unavailable))

    async def test_link_blocked_user(self) -> None:
        with self.assertRaises(Forbidden) as ctx:
            await self.api.link(333, BLOCKED_USERNAME, "x")
        self.assertIn("bloklangan", ctx.exception.detail)

    async def test_unlink(self) -> None:
        payload = await self.api.unlink(OWNER_TG)
        self.assertEqual(payload["detail"], "Telegram uzildi")
        with self.assertRaises(NotFound):
            await self.api.get_user(OWNER_TG)

    async def test_location_owner_and_forbidden(self) -> None:
        household = await self.api.send_location(OWNER_TG, 39.654, 66.959)
        self.assertEqual(household["code"], "XN-0003")
        self.assertAlmostEqual(household["latitude"], 39.654)

        with self.assertRaises(Forbidden) as ctx:
            await self.api.send_location(ADMIN_TG, 1.0, 2.0)
        self.assertEqual(ctx.exception.detail, "Lokatsiyani faqat xonadon egasi yubora oladi")

        with self.assertRaises(NotFound):
            await self.api.send_location(999, 1.0, 2.0)

    async def test_summary_owner(self) -> None:
        summary = await self.api.get_summary(OWNER_TG)
        self.assertEqual(summary, owner_summary())
        self.assertEqual(self.backend.paths, [f"/api/bot/users/{OWNER_TG}/summary"])

    async def test_summary_staff(self) -> None:
        summary = await self.api.get_summary(WAREHOUSE_TG)
        self.assertEqual(summary["role"], "WAREHOUSE")
        self.assertEqual(summary["today"]["birds_total"], 6900)
        self.assertNotIn("household", summary)

    async def test_summary_not_linked_raises_not_found(self) -> None:
        with self.assertRaises(NotFound) as ctx:
            await self.api.get_summary(999)
        self.assertEqual(ctx.exception.detail, "Foydalanuvchi topilmadi")

    async def test_summary_forbidden_keeps_backend_detail(self) -> None:
        detail = "Sizga xonadon biriktirilmagan. Administratorga murojaat qiling."
        self.backend.summary_error = (403, {"detail": detail})
        with self.assertRaises(Forbidden) as ctx:
            await self.api.get_summary(OWNER_TG)
        self.assertEqual(ctx.exception.detail, detail)

    async def test_summary_wrong_token_raises_forbidden(self) -> None:
        bad = BotApiClient(self.base_url, "wrong")
        try:
            with self.assertRaises(Forbidden):
                await bad.get_summary(OWNER_TG)
        finally:
            await bad.close()

    async def test_summary_rejects_unexpected_payload(self) -> None:
        for body in ([], {"today": {}}, {"role": None}):
            self.backend.summaries[OWNER_TG] = body
            with self.assertRaises(ApiError) as ctx:
                await self.api.get_summary(OWNER_TG)
            self.assertEqual(ctx.exception.status, 200)
            self.assertNotIsInstance(ctx.exception, (NotFound, Forbidden, Unavailable))

    async def test_summary_server_errors(self) -> None:
        self.backend.summary_error = (503, "Service Unavailable")
        with self.assertRaises(Unavailable):
            await self.api.get_summary(OWNER_TG)
        self.backend.summary_error = (500, "<h1>Server Error</h1>")
        with self.assertRaises(ApiError) as ctx:
            await self.api.get_summary(OWNER_TG)
        self.assertEqual(ctx.exception.detail, SERVER_ERROR_MESSAGE)

    async def test_pending_and_result(self) -> None:
        for i in range(1, 4):
            self.backend.add_notification(i, OWNER_TG)
        items = await self.api.pending_notifications(limit=2)
        self.assertEqual([n["id"] for n in items], [1, 2])
        self.assertEqual(set(items[0]), {"id", "chat_id", "text", "button_path"})

        self.assertEqual(await self.api.report_notification(1, True), "SENT")
        self.assertEqual(await self.api.report_notification(2, False, "Forbidden"), "PENDING")
        self.assertEqual(self.backend.results[0], (1, {"ok": True}))
        self.assertEqual(self.backend.results[1], (2, {"ok": False, "error": "Forbidden"}))

    async def test_paths_have_no_trailing_slash(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        await self.api.get_user(OWNER_TG)
        await self.api.link(333, "aliyev", "correct-pass")
        await self.api.send_location(OWNER_TG, 1.0, 2.0)
        await self.api.pending_notifications()
        await self.api.report_notification(1, True)
        await self.api.unlink(333)
        self.assertEqual(len(self.backend.paths), 6)
        for path in self.backend.paths:
            self.assertFalse(path.endswith("/"), path)

    async def test_server_errors(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            await self.api._request("GET", "bot/boom")
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(ctx.exception.detail, SERVER_ERROR_MESSAGE)

        with self.assertRaises(Unavailable):
            await self.api._request("GET", "bot/down")

    async def test_connection_error_raises_unavailable(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        dead = BotApiClient(f"http://127.0.0.1:{port}/api", TOKEN, timeout=2)
        try:
            with self.assertRaises(Unavailable) as ctx:
                await dead.get_user(OWNER_TG)
            self.assertEqual(ctx.exception.status, 0)
            self.assertEqual(ctx.exception.detail, UNAVAILABLE_MESSAGE)
        finally:
            await dead.close()

    async def test_session_is_shared_and_closed(self) -> None:
        await self.api.get_user(OWNER_TG)
        session = self.api._session
        await self.api.get_user(ADMIN_TG)
        self.assertIs(self.api._session, session)
        await self.api.close()
        self.assertTrue(session.closed)
        # Yopilgandan keyin yangi sessiya avtomatik ochiladi.
        await self.api.get_user(OWNER_TG)
        self.assertIsNot(self.api._session, session)


class NotifierTests(BackendTestCase):
    def make_worker(self, bot: mock.AsyncMock, webapp_url: str = WEBAPP) -> NotificationWorker:
        return NotificationWorker(bot=bot, api=self.api, webapp_url=webapp_url, send_delay=0)

    async def test_sent_message_reports_ok(self) -> None:
        self.backend.add_notification(1, OWNER_TG, "/households/3")
        bot = mock.AsyncMock()
        worker = self.make_worker(bot)

        self.assertEqual(await worker.process_once(), 1)

        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], OWNER_TG)
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertTrue(kwargs["disable_web_page_preview"])
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.text, WEBAPP_BUTTON_TEXT)
        self.assertEqual(button.web_app.url, f"{WEBAPP}/households/3")
        self.assertEqual(self.backend.results, [(1, {"ok": True})])
        self.assertEqual(self.backend.notifications[1]["status"], "SENT")

    async def test_no_button_without_https_or_path(self) -> None:
        self.backend.add_notification(1, OWNER_TG, "/my")
        self.backend.add_notification(2, OWNER_TG, "")
        bot = mock.AsyncMock()

        await self.make_worker(bot, webapp_url="http://localhost:3000").process_once()
        await self.make_worker(bot).process_once()  # 2-xabar: button_path bo'sh

        self.assertIsNone(bot.send_message.await_args_list[0].kwargs["reply_markup"])
        self.assertIsNone(bot.send_message.await_args_list[1].kwargs["reply_markup"])

    async def test_telegram_error_reports_failure_and_continues(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        self.backend.add_notification(2, ADMIN_TG)
        self.backend.add_notification(3, 444)
        bot = mock.AsyncMock()
        bot.send_message.side_effect = [
            BotBlocked("Forbidden: bot was blocked by the user"),
            None,
            ChatNotFound("Bad Request: chat not found"),
        ]

        self.assertEqual(await self.make_worker(bot).process_once(), 3)

        results = dict(self.backend.results)
        self.assertEqual(results[2], {"ok": True})
        self.assertFalse(results[1]["ok"])
        self.assertIn("BotBlocked", results[1]["error"])
        self.assertFalse(results[3]["ok"])
        self.assertIn("ChatNotFound", results[3]["error"])
        self.assertEqual(self.backend.notifications[1]["status"], "PENDING")
        self.assertEqual(self.backend.notifications[1]["attempts"], 1)

    async def test_unexpected_exception_reports_failure(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        bot = mock.AsyncMock()
        bot.send_message.side_effect = ValueError("buzilgan matn")

        await self.make_worker(bot).process_once()

        self.assertEqual(self.backend.results[0][1]["ok"], False)
        self.assertIn("buzilgan matn", self.backend.results[0][1]["error"])

    async def test_retry_after_leaves_message_pending(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        self.backend.add_notification(2, ADMIN_TG)
        bot = mock.AsyncMock()
        bot.send_message.side_effect = [RetryAfter(7), None]
        worker = self.make_worker(bot)

        with mock.patch.object(worker, "_sleep", mock.AsyncMock(return_value=False)) as sleep:
            self.assertEqual(await worker.process_once(), 1)

        sleep.assert_awaited_once_with(7.0)
        self.assertEqual(self.backend.results, [(2, {"ok": True})])
        self.assertEqual(self.backend.notifications[1]["status"], "PENDING")
        self.assertEqual(self.backend.notifications[1]["attempts"], 0)

    async def test_telegram_network_error_stops_pass_without_reporting(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        self.backend.add_notification(2, ADMIN_TG)
        bot = mock.AsyncMock()
        bot.send_message.side_effect = NetworkError("Aiohttp client throws an error")

        self.assertEqual(await self.make_worker(bot).process_once(), 0)

        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(self.backend.results, [])

    async def test_telegram_5xx_keeps_message_pending(self) -> None:
        from aiogram.utils.exceptions import RestartingTelegram, TelegramAPIError

        for error in (TelegramAPIError("Internal Server Error"), TelegramAPIError("Bad Gateway"), RestartingTelegram()):
            with self.subTest(error=repr(error)):
                self.backend.results.clear()
                self.backend.add_notification(1, OWNER_TG)
                bot = mock.AsyncMock()
                bot.send_message.side_effect = error
                worker = self.make_worker(bot)
                self.assertEqual(await worker.process_once(), 0)
                self.assertTrue(worker.telegram_down)
                self.assertEqual(self.backend.results, [])  # no attempt is used up
                self.assertEqual(self.backend.notifications[1]["status"], "PENDING")

    async def test_unknown_4xx_is_a_failure_not_an_outage(self) -> None:
        from aiogram.utils.exceptions import TelegramAPIError

        from utils.notifier import is_telegram_server_error

        self.assertFalse(is_telegram_server_error(TelegramAPIError("Payment required [402]")))
        self.assertTrue(is_telegram_server_error(TelegramAPIError("Internal Server Error")))

    async def test_backend_unavailable_on_fetch_raises(self) -> None:
        await self.server.close()
        bot = mock.AsyncMock()
        with self.assertRaises(Unavailable):
            await self.make_worker(bot).process_once()
        bot.send_message.assert_not_awaited()

    async def test_unreported_result_is_retried_without_resending(self) -> None:
        self.backend.add_notification(1, OWNER_TG)
        bot = mock.AsyncMock()
        worker = self.make_worker(bot)

        self.backend.fail_results_with = 503
        with self.assertRaises(Unavailable):
            await worker.process_once()
        self.assertEqual(bot.send_message.await_count, 1)

        self.backend.fail_results_with = None
        await worker.process_once()
        self.assertEqual(bot.send_message.await_count, 1)  # qayta yuborilmadi
        self.assertEqual(self.backend.results, [(1, {"ok": True})])

    async def test_loop_survives_backend_outage_and_stops(self) -> None:
        await self.server.close()
        bot = mock.AsyncMock()
        worker = NotificationWorker(bot=bot, api=self.api, webapp_url=WEBAPP, interval=0.01, max_backoff=0.05)
        worker.start()
        await asyncio.sleep(0.2)
        self.assertIsNotNone(worker._task)
        self.assertFalse(worker._task.done())
        await worker.stop(timeout=2)
        self.assertIsNone(worker._task)

    async def test_pending_rejects_non_array_payload(self) -> None:
        self.backend.pending_paginated = True
        with self.assertRaises(ApiError):
            await self.api.pending_notifications()

    async def test_too_many_requests_maps_to_uzbek_message(self) -> None:
        from utils.api import THROTTLED_MESSAGE, error_for_status

        error = error_for_status(429, {"detail": "Request was throttled."})
        self.assertIsInstance(error, TooManyRequests)
        self.assertEqual(error.detail, THROTTLED_MESSAGE)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[1])
    unittest.main(verbosity=2)
