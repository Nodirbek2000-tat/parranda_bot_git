"""BotApi against a tiny local aiohttp server (no real backend, no Telegram)."""
import support  # noqa: F401  (must be first)

import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from api import ApiError, BotApi, NotFound, Unavailable

TOKEN = "test-bot-api-token"


class ApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.seen = []

        @web.middleware
        async def check_token(request, handler):
            self.seen.append((request.method, request.path_qs))
            if request.headers.get("X-Bot-Token") != TOKEN:
                return web.json_response({"detail": "token"}, status=403)
            return await handler(request)

        async def me(request):
            if request.match_info["tid"] == "1":
                return web.json_response({"id": 7, "username": "ali", "role": "INSPECTOR"})
            return web.json_response({"detail": "Foydalanuvchi topilmadi."}, status=404)

        async def link(request):
            body = await request.json()
            if body["password"] != "ok":
                return web.json_response({"non_field_errors": ["Login yoki parol noto‘g‘ri."]}, status=400)
            return web.json_response({"id": 7, "username": body["username"]})

        async def tasks(request):
            return web.json_response({"count": 1, "results": [{"id": 5, "code": "XN-0005"}]})

        async def pending(request):
            return web.json_response([{"id": 1, "chat_id": 1, "text": "x", "button_path": "/cases/1"}])

        async def result(request):
            self.result_body = await request.json()
            return web.json_response({"status": "SENT"})

        async def boom(request):
            return web.json_response({}, status=503)

        app = web.Application(middlewares=[check_token])
        app.router.add_get("/api/bot/me/{tid}", me)
        app.router.add_post("/api/bot/link", link)
        app.router.add_get("/api/bot/tasks/{tid}", tasks)
        app.router.add_get("/api/bot/notifications/pending", pending)
        app.router.add_post("/api/bot/notifications/{id}/result", result)
        app.router.add_post("/api/bot/unlink", boom)
        self.server = TestServer(app)
        await self.server.start_server()
        self.api = BotApi(str(self.server.make_url("/api")), TOKEN, timeout=5)

    async def asyncTearDown(self) -> None:
        await self.api.close()
        await self.server.close()

    async def test_endpoints_and_token_header(self) -> None:
        self.assertEqual((await self.api.me(1))["username"], "ali")
        self.assertEqual((await self.api.link(1, "ali", "ok"))["username"], "ali")
        self.assertEqual(await self.api.tasks(1), [{"id": 5, "code": "XN-0005"}])  # paginated body unwrapped
        self.assertEqual(len(await self.api.pending_notifications(limit=50)), 1)
        await self.api.report_notification(1, False, "BotBlocked: blocked")
        self.assertEqual(self.result_body, {"ok": False, "error": "BotBlocked: blocked"})
        self.assertIn(("GET", "/api/bot/notifications/pending?limit=50"), self.seen)

    async def test_errors(self) -> None:
        with self.assertRaises(NotFound):
            await self.api.me(2)
        with self.assertRaises(ApiError) as ctx:
            await self.api.link(1, "ali", "bad")
        self.assertEqual((ctx.exception.status, ctx.exception.detail), (400, "Login yoki parol noto‘g‘ri."))
        self.assertFalse(ctx.exception.temporary)
        with self.assertRaises(Unavailable):
            await self.api.unlink(1)  # 503

    async def test_wrong_token_is_403(self) -> None:
        api = BotApi(str(self.server.make_url("/api")), "wrong")
        try:
            with self.assertRaises(ApiError) as ctx:
                await api.me(1)
            self.assertEqual(ctx.exception.status, 403)
        finally:
            await api.close()

    async def test_no_connection(self) -> None:
        api = BotApi("http://127.0.0.1:9/api", TOKEN, timeout=2)
        try:
            with self.assertRaises(Unavailable) as ctx:
                await api.me(1)
            self.assertTrue(ctx.exception.temporary)
        finally:
            await api.close()


if __name__ == "__main__":
    unittest.main()
