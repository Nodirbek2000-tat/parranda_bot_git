"""V3 scaffold: LOGISTICS / VET menyulari, /tasks, /notifications, buyruqlar ro'yxati, L/V hisobotlari.

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from aiohttp import web

from tests import test_handlers
from tests.test_bot import ADMIN_TG, OWNER_TG, WAREHOUSE_TG, FakeBackend, make_user
from tests.test_handlers import HandlerTestCase, message_update

LOGISTICS_TG = 666
VET_TG = 777


class V3Backend(FakeBackend):
    """FakeBackend + L/V foydalanuvchilar va ``bot/users/{tid}/notifications``."""

    def __init__(self) -> None:
        super().__init__()
        self.users[LOGISTICS_TG] = make_user(9, "logist", "LOGISTICS", None)
        self.users[VET_TG] = make_user(11, "vet", "VET", None)
        self.summaries[LOGISTICS_TG] = {
            "role": "LOGISTICS", "date": "2026-11-04", "generated_at": "2026-11-04T18:20:05+05:00",
            "today": {"my_active": 2, "my_in_transit": 1, "new_unassigned": 1, "overdue": 1,
                      "delivered_today": 3, "awaiting_confirmation": 1},
        }
        self.summaries[VET_TG] = {
            "role": "VET", "date": "2026-11-04", "generated_at": "2026-11-04T18:20:05+05:00",
            "today": {"visits_today": 2, "visits_overdue": 1, "vaccinations_due_7d": 4,
                      "vaccinations_overdue": 2, "open_diseases": 1, "new_requests": 2},
        }
        self.inbox: dict[int, list[dict[str, Any]]] = {
            OWNER_TG: [
                {"id": 2, "title": "NNP — BUYURTMA TASDIQLANDI", "body": "Buyurtma: BY-000005",
                 "button_path": "/my/orders/5", "created_at": "2026-11-04T13:20:00+00:00", "read_at": None},
                {"id": 1, "title": "NNP — <PARRANDA> TARQATILDI", "body": "", "button_path": "/my",
                 "created_at": "2026-11-03T05:00:00+05:00", "read_at": "2026-11-03T06:00:00+05:00"},
            ],
        }
        self.inbox_limits: list[str] = []
        self.app.router.add_get("/api/bot/users/{telegram_id}/notifications", self.notifications_inbox)

    async def notifications_inbox(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id not in self.users:
            return web.json_response({"detail": "Foydalanuvchi topilmadi"}, status=404)
        self.inbox_limits.append(request.query.get("limit", ""))
        return web.json_response(self.inbox.get(telegram_id, []))


class V3HandlerTestCase(HandlerTestCase):
    async def asyncSetUp(self) -> None:
        with mock.patch.object(test_handlers, "FakeBackend", V3Backend):
            await super().asyncSetUp()


class RoleMenuTests(V3HandlerTestCase):
    async def test_role_keyboards(self) -> None:
        expected = {
            OWNER_TG: ["📍 Lokatsiyani yuborish", "📋 Topshiriqlar", "🔔 Bildirishnomalar"],
            LOGISTICS_TG: ["📋 Topshiriqlarim", "🔔 Bildirishnomalar"],
            VET_TG: ["📋 Bugungi ishlar", "🔔 Bildirishnomalar"],
            ADMIN_TG: ["📋 Topshiriqlar", "🔔 Bildirishnomalar"],
            WAREHOUSE_TG: ["📋 Topshiriqlar", "🔔 Bildirishnomalar"],
        }
        for telegram_id, buttons in expected.items():
            with self.subTest(telegram_id=telegram_id):
                await self.feed(message_update(telegram_id, "/menu"))
                markup = str(self.sent()[0]["reply_markup"])
                for button in [*buttons, "📊 Hisobot", "👤 Profil", "ℹ️ Yordam"]:
                    self.assertIn(button, markup)
                if telegram_id != OWNER_TG:
                    self.assertNotIn("Lokatsiya", markup)

    async def test_profile_shows_new_role_names(self) -> None:
        await self.feed(message_update(LOGISTICS_TG, "/profile"))
        self.assertIn("Rol: Logistika xodimi", self.texts())
        await self.feed(message_update(VET_TG, "/profile"))
        self.assertIn("Rol: Veterinar", self.texts())

    async def test_command_list_and_help(self) -> None:
        from utils.set_bot_commands import COMMANDS

        commands = [c.command for c in COMMANDS]
        self.assertEqual(
            commands,
            ["start", "menu", "profile", "tasks", "notifications", "reports", "settings", "help", "cancel", "logout"],
        )
        self.assertEqual(next(c.description for c in COMMANDS if c.command == "tasks"), "Mening topshiriqlarim")
        await self.feed(message_update(VET_TG, "/help"))
        self.assertIn("/tasks — mening topshiriqlarim", self.texts())
        self.assertIn("/notifications — oxirgi bildirishnomalar", self.texts())


class TasksPlaceholderTests(V3HandlerTestCase):
    async def test_tasks_opens_role_section_in_webapp(self) -> None:
        cases = [
            (LOGISTICS_TG, "📋 Topshiriqlarim", "https://app.example.test/logistics"),
            (VET_TG, "📋 Bugungi ishlar", "https://app.example.test/vet"),
            (OWNER_TG, "📋 Topshiriqlar", "https://app.example.test/my/orders"),
            (ADMIN_TG, "/tasks", "https://app.example.test/dashboard"),
        ]
        for telegram_id, text, url in cases:
            with self.subTest(telegram_id=telegram_id):
                await self.feed(message_update(telegram_id, text))
                sent = self.sent()
                self.assertEqual(len(sent), 1)
                self.assertIn("Mening topshiriqlarim", sent[0]["text"])
                self.assertIn(url, str(sent[0]["reply_markup"]))

    async def test_unlinked_user_is_sent_to_start(self) -> None:
        await self.feed(message_update(999, "/tasks"))
        self.assertIn("/start", self.texts())


class NotificationsTests(V3HandlerTestCase):
    async def test_inbox_format(self) -> None:
        await self.feed(message_update(OWNER_TG, "🔔 Bildirishnomalar"))
        text = self.sent()[0]["text"]
        self.assertEqual(
            text,
            "🔔 <b>Bildirishnomalar</b>\n\n"
            "🆕 04.11.2026 18:20 — NNP — BUYURTMA TASDIQLANDI\n"
            "• 03.11.2026 05:00 — NNP — &lt;PARRANDA&gt; TARQATILDI",
        )
        self.assertEqual(self.backend.inbox_limits, ["10"])
        self.assertIn("https://app.example.test/", str(self.sent()[0]["reply_markup"]))

    async def test_empty_inbox(self) -> None:
        await self.feed(message_update(VET_TG, "/notifications"))
        self.assertIn("Hozircha bildirishnoma yo‘q.", self.texts())


class V3ReportsTests(V3HandlerTestCase):
    async def test_logistics_report(self) -> None:
        await self.feed(message_update(LOGISTICS_TG, "/reports"))
        self.assertEqual(
            self.sent()[0]["text"],
            "📊 <b>NNP — LOGISTIKA HOLATI</b>\nSana: 04.11.2026\nMening faol topshiriqlarim: 2\n  yo‘lda: 1\n"
            "Biriktirilmagan yangi: 1\nMuddati o‘tgan: 1\nBugun yetkazildi: 3\nTasdiq kutilmoqda: 1",
        )
        self.assertIn("https://app.example.test/logistics", str(self.sent()[0]["reply_markup"]))

    async def test_vet_report(self) -> None:
        await self.feed(message_update(VET_TG, "📊 Hisobot"))
        text = self.sent()[0]["text"]
        self.assertTrue(text.startswith("📊 <b>NNP — VETERINARIYA HOLATI</b>\nSana: 04.11.2026\n"))
        self.assertIn("7 kun ichida emlash: 4", text)
        self.assertIn("Yangi murojaatlar: 2", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
