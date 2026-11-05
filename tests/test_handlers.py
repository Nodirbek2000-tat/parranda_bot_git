"""Handlerlarning dispatcher orqali tekshiruvi: Telegram so'rovlari ushlab olinadi, backend — soxta server.

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import asyncio
import contextvars
import itertools
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from datetime import date
from typing import Any
from unittest import mock

from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Haqiqiy .env talab qilinmasin: soxta qiymatlar (polling ishga tushirilmaydi).
os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ["BOT_API_TOKEN"] = "test-bot-api-token"
os.environ["WEBAPP_URL"] = "https://app.example.test"

from aiogram import Bot, Dispatcher, types  # noqa: E402

import app  # noqa: E402,F401 — barcha handlerlarni ro'yxatdan o'tkazadi
from data import config  # noqa: E402
from loader import api, bot, dp  # noqa: E402
from tests.test_bot import ADMIN_TG, OWNER_TG, WAREHOUSE_TG, FakeBackend  # noqa: E402

NEW_TG = 555
_ids = itertools.count(1)


def message_update(user_id: int, text: str | None = None, **extra: Any) -> types.Update:
    message: dict[str, Any] = {
        "message_id": next(_ids),
        "date": 1762230000,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        **extra,
    }
    if text is not None:
        message["text"] = text
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return types.Update(update_id=next(_ids), message=message)


class HandlerTestCase(unittest.IsolatedAsyncioTestCase):
    """Umumiy muhit: soxta backend + ushlab olingan Telegram so'rovlari (testlarsiz baza sinf)."""

    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)
        # Testda throttling o'chiriladi (har bir test bir xil handlerlarni tez chaqiradi).
        dp.middleware.applications.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    async def asyncSetUp(self) -> None:
        self.assertTrue(config.WEBAPP_ENABLED)
        self.backend = FakeBackend()
        self.server = TestServer(self.backend.app)
        await self.server.start_server()
        api._base_url = str(self.server.make_url("/api"))
        dp.storage.data.clear()

        self.calls: list[tuple[str, dict[str, Any]]] = []

        async def fake_request(method: str, data: dict[str, Any] | None = None, files: Any = None, **_: Any) -> Any:
            self.calls.append((method, dict(data or {})))
            if method in ("deleteMessage", "answerCallbackQuery"):
                return True
            return {
                "message_id": next(_ids), "date": 1762230000,
                "chat": {"id": (data or {}).get("chat_id", 0), "type": "private"},
                "text": (data or {}).get("text", ""),
            }

        self._patch = mock.patch.object(bot, "request", side_effect=fake_request)
        self._patch.start()

    async def asyncTearDown(self) -> None:
        self._patch.stop()
        await api.close()
        await self.server.close()

    async def feed(self, update: types.Update) -> None:
        self.calls.clear()
        # Polling har bir update ni alohida vazifada (yangi kontekstda) ishlaydi — shuni takrorlaymiz,
        # aks holda aiogram StateFilter ning kontekstdagi keshi oldingi update holatini qaytaradi.
        async def run() -> None:
            Bot.set_current(bot)
            Dispatcher.set_current(dp)
            await dp.process_update(update)

        await asyncio.get_running_loop().create_task(run(), context=contextvars.Context())

    def sent(self) -> list[dict[str, Any]]:
        return [data for method, data in self.calls if method == "sendMessage"]

    def texts(self) -> str:
        return "\n".join(str(d.get("text", "")) for d in self.sent())



class HandlerTests(HandlerTestCase):

    async def test_start_linked_owner_shows_menu_and_platform_button(self) -> None:
        await self.feed(message_update(OWNER_TG, "/start"))
        sent = self.sent()
        self.assertEqual(len(sent), 2)
        self.assertIn("Bobur Aliyev", sent[0]["text"])
        self.assertIn("Xonadon egasi", sent[0]["text"])
        keyboard = str(sent[0]["reply_markup"])
        self.assertIn("request_location", keyboard)
        self.assertIn("👤 Profil", keyboard)
        self.assertIn("web_app", str(sent[1]["reply_markup"]))
        self.assertIn("https://app.example.test", str(sent[1]["reply_markup"]))

    async def test_admin_menu_has_no_location_button(self) -> None:
        await self.feed(message_update(ADMIN_TG, "/menu"))
        self.assertNotIn("request_location", str(self.sent()[0]["reply_markup"]))

    async def test_login_flow_deletes_password_and_links(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        self.assertIn("login", self.texts())

        await self.feed(message_update(NEW_TG, "aliyev"))
        self.assertIn("parol", self.texts())

        await self.feed(message_update(NEW_TG, "wrong"))
        self.assertIn("deleteMessage", [m for m, _ in self.calls])
        self.assertIn("Login yoki parol noto‘g‘ri", self.texts())

        await self.feed(message_update(NEW_TG, "aliyev"))
        await self.feed(message_update(NEW_TG, "correct-pass"))
        self.assertIn("deleteMessage", [m for m, _ in self.calls])
        self.assertIn("muvaffaqiyatli", self.texts())
        self.assertIn(NEW_TG, self.backend.users)
        self.assertNotIn("correct-pass", self.texts())

    async def test_cancel_aborts_login(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        await self.feed(message_update(NEW_TG, "/cancel"))
        self.assertIn("bekor qilindi", self.texts())
        await self.feed(message_update(NEW_TG, "salom"))
        self.assertIn("/start", self.texts())  # fallback: tizimga kirmagan

    async def test_profile_escapes_html(self) -> None:
        self.backend.users[OWNER_TG]["full_name"] = "<b>Ali</b> & Co"
        await self.feed(message_update(OWNER_TG, "👤 Profil"))
        text = self.texts()
        self.assertIn("&lt;b&gt;Ali&lt;/b&gt; &amp; Co", text)
        self.assertIn("XN-0003", text)

    async def test_location_owner_and_admin(self) -> None:
        location = {"location": {"latitude": 39.6541234, "longitude": 66.9591234}}
        await self.feed(message_update(OWNER_TG, **location))
        self.assertIn("39.654123, 66.959123", self.texts())

        await self.feed(message_update(ADMIN_TG, **location))
        self.assertIn("faqat xonadon egasi", self.texts())

    async def test_fallback_does_not_echo(self) -> None:
        await self.feed(message_update(OWNER_TG, "qandaydir matn"))
        self.assertNotIn("qandaydir matn", self.texts())
        self.assertIn("menyu", self.texts())

    async def test_logout_confirmation(self) -> None:
        await self.feed(message_update(OWNER_TG, "/logout"))
        self.assertIn("logout:yes", str(self.sent()[0]["reply_markup"]))

        callback = types.Update(update_id=next(_ids), callback_query={
            "id": "cb1", "chat_instance": "x", "data": "logout:yes",
            "from": {"id": OWNER_TG, "is_bot": False, "first_name": "Test"},
            "message": {"message_id": 10, "date": 1762230000, "text": "?",
                        "chat": {"id": OWNER_TG, "type": "private"}},
        })
        await self.feed(callback)
        self.assertNotIn(OWNER_TG, self.backend.users)
        self.assertIn("editMessageText", [m for m, _ in self.calls])

    async def test_password_starting_with_slash_is_deleted_and_used(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        await self.feed(message_update(NEW_TG, "aliyev"))
        with mock.patch.object(api, "link", wraps=api.link) as link:
            await self.feed(message_update(NEW_TG, "/Secr3t-pass"))
        self.assertIn("deleteMessage", [m for m, _ in self.calls])
        link.assert_awaited_once_with(NEW_TG, "aliyev", "/Secr3t-pass")
        self.assertNotIn("Secr3t", self.texts())

    async def test_navigation_command_during_password_is_deleted_not_sent(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        await self.feed(message_update(NEW_TG, "aliyev"))
        with mock.patch.object(api, "link", wraps=api.link) as link:
            await self.feed(message_update(NEW_TG, "/menu"))
        link.assert_not_awaited()
        self.assertIn("deleteMessage", [m for m, _ in self.calls])
        self.assertIn("davom etmoqda", self.texts())

    async def test_password_handler_is_never_throttled(self) -> None:
        from handlers.users.login import login_password

        self.assertEqual(getattr(login_password, "throttling_rate_limit", None), 0)

    async def test_unexpected_error_replies_and_never_logs_password(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        await self.feed(message_update(NEW_TG, "aliyev"))
        logging.disable(logging.NOTSET)
        try:
            with mock.patch.object(api, "link", side_effect=RuntimeError("boom")), \
                    self.assertLogs(level="DEBUG") as logs:
                await self.feed(message_update(NEW_TG, "TopSecret123"))
        finally:
            logging.disable(logging.CRITICAL)
        self.assertNotIn("TopSecret123", "\n".join(logs.output))
        self.assertIn("Serverda xatolik", self.texts())

    async def test_api_error_is_answered_once(self) -> None:
        await self.server.close()
        await self.feed(message_update(OWNER_TG, "/menu"))
        self.assertEqual(len(self.sent()), 1)

    async def test_blocked_owner_location_shows_backend_reason(self) -> None:
        self.backend.users[OWNER_TG]["is_active"] = False
        await self.feed(message_update(OWNER_TG, location={"latitude": 39.65, "longitude": 66.95}))
        self.assertIn("bloklangan", self.texts())
        self.assertNotIn("faqat xonadon egasi", self.texts())

    async def test_logout_from_uneditable_message_still_completes(self) -> None:
        from aiogram.utils.exceptions import MessageCantBeEdited

        original = bot.request.side_effect

        async def request(method: str, data: dict[str, Any] | None = None, *a: Any, **kw: Any) -> Any:
            if method == "editMessageText":
                self.calls.append((method, dict(data or {})))
                raise MessageCantBeEdited("Bad Request: message can't be edited")
            return await original(method, data, *a, **kw)

        bot.request.side_effect = request
        callback = types.Update(update_id=next(_ids), callback_query={
            "id": "cb2", "chat_instance": "x", "data": "logout:yes",
            "from": {"id": OWNER_TG, "is_bot": False, "first_name": "Test"},
            "message": {"message_id": 11, "date": 1762230000, "text": "?",
                        "chat": {"id": OWNER_TG, "type": "private"}},
        })
        await self.feed(callback)
        methods = [m for m, _ in self.calls]
        self.assertNotIn(OWNER_TG, self.backend.users)
        self.assertIn("answerCallbackQuery", methods)
        self.assertIn("/start", self.texts())

    async def test_backend_unavailable_message(self) -> None:
        await self.server.close()
        await self.feed(message_update(OWNER_TG, "/menu"))
        self.assertIn("Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.", self.texts())


# docs/API_CONTRACT_V2.md 5.2 dagi namunaviy matnlar (5.1 namunaviy javoblari uchun) — aynan shunday bo'lishi kerak.
OWNER_REPORT_TEXT = """📊 <b>NNP — XONADON HISOBOTI</b>

Xonadon: Navbahor 12-uy (XN-0003)
Sana: 04.11.2026

Parranda soni: 497 dona
Bugungi hisobot: ✅ topshirilgan
Bugun tuxum: 410 dona
Bugun yem: 55.5 kg
Bugun nobud: 3 dona

<b>Oxirgi 7 kun</b> (29.10.2026 – 04.11.2026)
Tuxum: 2 800 dona
Tuxumdorlik: 81.2%
Yem: 380 kg
Nobud: 5 dona
Hisobotlar: 6 / 7"""

STAFF_REPORT_TEXT = """📊 <b>NNP — BUGUNGI HOLAT</b>

Sana: 04.11.2026

Hisobot topshirgan xonadonlar: 8 / 10 (80.0%)
Tuxum: 2 100 dona
Tuxumdorlik: 80.4%
Yem sarfi: 310.5 kg
Nobud: 4 dona
  xonadonlarda: 3 · markazda: 1
Jami parranda: 6 900 dona
  xonadonlarda: 5 400 · markazda: 1 500
Kam qolgan mahsulotlar: 1 ta"""


class ReportsTests(HandlerTestCase):
    """``/reports`` va «📊 Hisobot» (docs/API_CONTRACT_V2.md 5.2)."""

    def summary_requests(self) -> list[str]:
        return [p for p in self.backend.paths if p.endswith("/summary")]

    @staticmethod
    def webapp_url(sent: dict[str, Any]) -> str | None:
        markup = sent.get("reply_markup")
        data = json.loads(markup) if isinstance(markup, str) else markup
        if not isinstance(data, dict) or "inline_keyboard" not in data:
            return None
        return data["inline_keyboard"][0][0]["web_app"]["url"]

    async def test_owner_report_matches_contract_and_opens_my(self) -> None:
        await self.feed(message_update(OWNER_TG, "/reports"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["text"], OWNER_REPORT_TEXT)
        self.assertEqual(self.webapp_url(sent[0]), "https://app.example.test/my")
        self.assertIn("🔎 Web App orqali ko‘rish", str(sent[0]["reply_markup"]))
        self.assertEqual(self.summary_requests(), [f"/api/bot/users/{OWNER_TG}/summary"])

    async def test_admin_report_matches_contract_and_opens_stats(self) -> None:
        await self.feed(message_update(ADMIN_TG, "/reports"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["text"], STAFF_REPORT_TEXT)
        self.assertEqual(self.webapp_url(sent[0]), "https://app.example.test/stats")

    async def test_warehouse_uses_staff_report_via_button(self) -> None:
        await self.feed(message_update(WAREHOUSE_TG, "📊 Hisobot"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["text"], STAFF_REPORT_TEXT)
        self.assertEqual(self.webapp_url(sent[0]), "https://app.example.test/stats")

    async def test_owner_button_gives_same_report(self) -> None:
        await self.feed(message_update(OWNER_TG, "📊 Hisobot"))
        self.assertEqual(self.texts(), OWNER_REPORT_TEXT)

    async def test_owner_not_submitted_and_null_rate_show_dash(self) -> None:
        summary = self.backend.summaries[OWNER_TG]
        summary["today"] = {"report_submitted": False, "eggs": None, "feed_kg": None, "deaths": 0}
        summary["last_7d"].update(reports=0, reported=0, eggs=0, feed_kg=0, deaths=0, laying_rate_pct=None)
        await self.feed(message_update(OWNER_TG, "/reports"))
        text = self.texts()
        self.assertIn("Bugungi hisobot: ❌ topshirilmagan", text)
        self.assertIn("Bugun tuxum: —\n", text)
        self.assertIn("Bugun yem: —\n", text)
        self.assertIn("Bugun nobud: 0 dona", text)
        self.assertIn("Tuxumdorlik: —\n", text)
        self.assertIn("Yem: 0 kg", text)
        self.assertIn("Hisobotlar: 0 / 7", text)
        self.assertNotIn("None", text)

    async def test_staff_null_ratios_and_large_numbers(self) -> None:
        self.backend.summaries[ADMIN_TG]["today"].update(
            households_active=0, households_expected=0, households_reported=0, report_discipline_pct=None,
            laying_rate_pct=None, eggs=1234567, feed_kg=12500.25, birds_total=1500,
            birds_in_households=0, low_stock_count=0,
        )
        await self.feed(message_update(ADMIN_TG, "/reports"))
        text = self.texts()
        self.assertIn("Hisobot topshirgan xonadonlar: 0 / 0 (—)", text)
        self.assertIn("Tuxum: 1 234 567 dona", text)
        self.assertIn("Tuxumdorlik: —\n", text)
        self.assertIn("Yem sarfi: 12 500.25 kg", text)
        self.assertIn("  xonadonlarda: 0 · markazda: 1 500", text)
        self.assertIn("Kam qolgan mahsulotlar: 0 ta", text)
        self.assertNotIn("None", text)

    async def test_owner_counts_only_expected_days(self) -> None:
        """«Hisobotlar» = kutilgan kunlardan kiritilgani / kutilgan (raw ``reports`` emas): 7 / 3 emas, 3 / 3."""
        self.backend.summaries[OWNER_TG]["last_7d"].update(reports=7, reported=3, expected=3)
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertIn("Hisobotlar: 3 / 3", self.texts())

    async def test_staff_old_backend_without_new_keys(self) -> None:
        today = self.backend.summaries[ADMIN_TG]["today"]
        del today["households_expected"], today["deaths_center"]
        await self.feed(message_update(ADMIN_TG, "/reports"))
        text = self.texts()
        self.assertIn("Hisobot topshirgan xonadonlar: 8 / 11 (80.0%)", text)
        self.assertIn("Nobud: 3 dona\n", text)
        self.assertNotIn("markazda: 1\n", text)

    async def test_percent_always_has_one_decimal(self) -> None:
        self.backend.summaries[ADMIN_TG]["today"].update(report_discipline_pct=100, laying_rate_pct=80.0)
        await self.feed(message_update(ADMIN_TG, "/reports"))
        text = self.texts()
        self.assertIn("8 / 10 (100.0%)", text)
        self.assertIn("Tuxumdorlik: 80.0%", text)

    async def test_meat_lines_only_when_reported(self) -> None:
        from handlers.users.reports import owner_report_text, staff_report_text

        owner = {"household": {"name": "Uy", "code": "XN-0001"}, "date": "2026-11-05", "bird_count": 10,
                 "today": {"report_submitted": True, "eggs": 0, "feed_kg": 5, "meat_kg": 62.5, "deaths": 0},
                 "last_7d": {"date_from": "2026-10-30", "date_to": "2026-11-05", "eggs": 0, "feed_kg": 30,
                             "meat_kg": 120, "deaths": 0, "reported": 7, "expected": 7}}
        text = owner_report_text(owner)
        self.assertIn("Bugun go‘sht: 62,5 kg", text.replace("62.5", "62,5"))
        self.assertIn("Go‘sht: 120 kg", text)
        owner["today"]["meat_kg"] = None
        owner["last_7d"]["meat_kg"] = 0
        self.assertNotIn("go‘sht", owner_report_text(owner).lower())
        self.assertIn("Go‘sht: 7 kg", staff_report_text({"date": "2026-11-05", "today": {"meat_kg": 7}}))
        self.assertNotIn("Go‘sht", staff_report_text({"date": "2026-11-05", "today": {"meat_kg": 0.0}}))

    async def test_owner_report_escapes_household_values(self) -> None:
        self.backend.summaries[OWNER_TG]["household"] = {"id": 3, "code": "XN-0003", "name": "<b>Uy</b> & bog‘"}
        await self.feed(message_update(OWNER_TG, "/reports"))
        text = self.texts()
        self.assertIn("Xonadon: &lt;b&gt;Uy&lt;/b&gt; &amp; bog‘ (XN-0003)", text)
        self.assertNotIn("<b>Uy</b>", text)

    async def test_missing_date_falls_back_to_local_today(self) -> None:
        del self.backend.summaries[ADMIN_TG]["date"]
        with mock.patch("handlers.users.reports.local_today", return_value=date(2026, 1, 2)):
            await self.feed(message_update(ADMIN_TG, "/reports"))
        self.assertIn("Sana: 02.01.2026", self.texts())

    async def test_no_webapp_button_without_https(self) -> None:
        with mock.patch.object(config, "WEBAPP_ENABLED", False):
            await self.feed(message_update(ADMIN_TG, "/reports"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["text"], STAFF_REPORT_TEXT)
        self.assertIsNone(self.webapp_url(sent[0]))
        self.assertNotIn("web_app", str(sent[0]["reply_markup"]))
        self.assertIn("📊 Hisobot", str(sent[0]["reply_markup"]))  # rolga mos reply menyu

    async def test_not_linked_user_is_sent_to_start(self) -> None:
        await self.feed(message_update(NEW_TG, "/reports"))
        self.assertIn("/start", self.texts())
        self.assertEqual(self.summary_requests(), [])

    async def test_blocked_user_does_not_request_summary(self) -> None:
        self.backend.users[OWNER_TG]["is_active"] = False
        await self.feed(message_update(OWNER_TG, "📊 Hisobot"))
        self.assertIn("bloklangan", self.texts())
        self.assertEqual(self.summary_requests(), [])

    async def test_temp_password_user_is_sent_to_change_password(self) -> None:
        self.backend.users[OWNER_TG]["must_change_password"] = True
        await self.feed(message_update(OWNER_TG, "📊 Hisobot"))
        self.assertIn("vaqtinchalik parol", self.texts())
        self.assertEqual(self.summary_requests(), [])
        # Profile and menu stay available (they show the same warning).
        await self.feed(message_update(OWNER_TG, "/profile"))
        self.assertIn("vaqtinchalik parolingizni almashtiring", self.texts())

    async def test_summary_404_shows_not_linked_text(self) -> None:
        self.backend.summary_error = (404, {"detail": "Foydalanuvchi topilmadi"})
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("Siz hali tizimga kirmagansiz", self.texts())
        self.assertIn("/start", self.texts())

    async def test_summary_403_shows_backend_detail_escaped(self) -> None:
        detail = "Sizga xonadon biriktirilmagan. Administratorga murojaat qiling."
        self.backend.summary_error = (403, {"detail": detail})
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.texts(), f"⚠️ {detail}")

        self.backend.summary_error = (403, {"detail": "<x> & y"})
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertEqual(self.texts(), "⚠️ &lt;x&gt; &amp; y")

    async def test_summary_unavailable_and_server_error(self) -> None:
        self.backend.summary_error = (503, "Service Unavailable")
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.texts(), "Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.")

        self.backend.summary_error = (500, "<h1>Server Error</h1>")
        await self.feed(message_update(ADMIN_TG, "/reports"))
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("Serverda xatolik", self.texts())

    async def test_unexpected_summary_payload_is_server_error(self) -> None:
        self.backend.summaries[ADMIN_TG] = ["not", "an", "object"]
        await self.feed(message_update(ADMIN_TG, "/reports"))
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("Serverda xatolik", self.texts())

    async def test_backend_down_message(self) -> None:
        await self.server.close()
        await self.feed(message_update(OWNER_TG, "/reports"))
        self.assertEqual(self.texts(), "Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.")

    async def test_reports_command_during_password_is_not_used_as_password(self) -> None:
        await self.feed(message_update(NEW_TG, "/start"))
        await self.feed(message_update(NEW_TG, "aliyev"))
        with mock.patch.object(api, "link", wraps=api.link) as link:
            await self.feed(message_update(NEW_TG, "/reports"))
        link.assert_not_awaited()
        self.assertIn("deleteMessage", [m for m, _ in self.calls])
        self.assertIn("davom etmoqda", self.texts())
        self.assertEqual(self.summary_requests(), [])

    async def test_menu_has_reports_button_for_every_role(self) -> None:
        for telegram_id in (OWNER_TG, ADMIN_TG, WAREHOUSE_TG):
            with self.subTest(telegram_id=telegram_id):
                await self.feed(message_update(telegram_id, "/menu"))
                self.assertIn("📊 Hisobot", str(self.sent()[0]["reply_markup"]))

    async def test_settings_command_points_to_web_app(self) -> None:
        await self.feed(message_update(OWNER_TG, "/settings"))
        self.assertIn("Bildirishnoma sozlamalari", self.texts())
        await self.feed(message_update(OWNER_TG, "/help"))
        self.assertIn("/settings — bildirishnoma sozlamalari", self.texts())

    async def test_help_and_command_list_include_reports(self) -> None:
        from utils.set_bot_commands import COMMANDS

        self.assertIn("reports", [c.command for c in COMMANDS])
        self.assertEqual(
            next(c.description for c in COMMANDS if c.command == "reports"), "Hisobot va statistika"
        )
        await self.feed(message_update(OWNER_TG, "/help"))
        self.assertIn("/reports — hisobot va statistika", self.texts())


if __name__ == "__main__":
    unittest.main(verbosity=2)
