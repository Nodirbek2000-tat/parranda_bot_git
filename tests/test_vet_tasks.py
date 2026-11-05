"""V3 veterinariya: VET / ADMIN ``/tasks`` xulosasi va eslatmalar tiki (API_CONTRACT_V3 §14.2, §14.5).

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from aiohttp import web

from tests import test_handlers
from tests.test_bot import ADMIN_TG
from tests.test_handlers import HandlerTestCase, message_update
from tests.test_v3_menus import VET_TG, V3Backend
from utils.vet_tasks import admin_tasks_text, vet_tasks_text

HOUSEHOLD = {"id": 3, "code": "XN-0003", "name": "Navbahor <12>-uy"}

VET_PAYLOAD: dict[str, Any] = {
    "role": "VET",
    "date": "2026-11-04",
    "visits_today": [
        {"id": 4, "code": "VT-000004", "household": HOUSEHOLD, "purpose": "Rejali ko‘rik", "planned_date": "2026-11-04",
         "vet": {"id": 11, "full_name": "Dr. Karimova"}, "status": "PLANNED"},
    ],
    "visits_overdue": [
        {"id": 2, "code": "VT-000002", "household": HOUSEHOLD, "purpose": "Qayta ko‘rik", "planned_date": "2026-11-01",
         "vet": None, "status": "PLANNED"},
    ],
    "vaccinations_due": [
        {"id": 8, "code": "EM-000008", "household": HOUSEHOLD, "vaccine_name": "Nyukasl & La Sota",
         "planned_date": "2026-11-05", "birds_planned": 1500, "vet": None},
    ],
    "vaccinations_overdue": [],
    "new_requests": 2,
}

ADMIN_PAYLOAD: dict[str, Any] = {
    "role": "ADMIN",
    "orders_new": [{"id": 5, "code": "BY-000005", "household": HOUSEHOLD, "items_text": "Yem PK-1 — 150 kg",
                    "created_at": "2026-11-04T10:00:00+05:00"}],
    "orders_new_count": 3,
    "deliveries": {"in_transit": 2, "delivered": 1, "overdue": 1},
    "vet_overdue": 3,
}


class VetTasksBackend(V3Backend):
    def __init__(self) -> None:
        super().__init__()
        self.tasks: dict[int, Any] = {VET_TG: VET_PAYLOAD, ADMIN_TG: ADMIN_PAYLOAD}
        self.reminder_calls = 0
        self.reminder_status = 200
        self.app.router.add_get("/api/bot/users/{telegram_id}/tasks", self.get_tasks)
        self.app.router.add_post("/api/bot/reminders/run", self.run_reminders)

    async def get_tasks(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id not in self.tasks:
            return web.json_response({"detail": "Foydalanuvchi topilmadi"}, status=404)
        return web.json_response(self.tasks[telegram_id])

    async def run_reminders(self, request: web.Request) -> web.Response:
        self.reminder_calls += 1
        if self.reminder_status != 200:
            return web.json_response({"detail": "xato"}, status=self.reminder_status)
        return web.json_response({"date": "2026-11-04", "ran": True, "queued": 4})


class FormattingTests(unittest.TestCase):
    def test_vet_text_lists_sections_and_escapes(self) -> None:
        text = vet_tasks_text(VET_PAYLOAD)
        self.assertIn("📋 <b>Mening topshiriqlarim</b>", text)
        self.assertIn("Sana: 04.11.2026", text)
        self.assertIn("🩺 <b>Bugungi tekshiruvlar</b> (1)", text)
        self.assertIn("<b>VT-000004</b> — Navbahor &lt;12&gt;-uy (XN-0003) · Rejali ko‘rik", text)
        self.assertIn("VT-000002", text)
        self.assertIn("01.11.2026 · biriktirilmagan", text)
        self.assertIn("Nyukasl &amp; La Sota", text)
        self.assertIn("1 500 bosh", text)
        self.assertIn("📨 Yangi murojaatlar: <b>2</b>", text)
        self.assertNotIn("Muddati o‘tgan emlashlar", text)

    def test_vet_text_empty_day(self) -> None:
        text = vet_tasks_text({"role": "VET", "date": "2026-11-04", "new_requests": 0})
        self.assertIn("Bugun uchun rejalashtirilgan ish yo‘q", text)

    def test_admin_text(self) -> None:
        text = admin_tasks_text(ADMIN_PAYLOAD)
        self.assertIn("🛒 Yangi buyurtmalar: <b>3</b>", text)
        self.assertIn("<b>BY-000005</b> — Navbahor &lt;12&gt;-uy (XN-0003) · Yem PK-1 — 150 kg", text)
        self.assertIn("yo‘lda 2 · yetkazildi 1 · muddati o‘tgan 1", text)
        self.assertIn("Muddati o‘tgan veterinariya ishlari: <b>3</b>", text)


class VetTasksHandlerTests(HandlerTestCase):
    async def asyncSetUp(self) -> None:
        with mock.patch.object(test_handlers, "FakeBackend", VetTasksBackend):
            await super().asyncSetUp()

    async def test_vet_tasks_summary_with_webapp_buttons(self) -> None:
        await self.feed(message_update(VET_TG, "📋 Bugungi ishlar"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertIn("Bugungi tekshiruvlar", sent[0]["text"])
        markup = str(sent[0]["reply_markup"])
        self.assertIn("https://app.example.test/vet", markup)
        self.assertIn("https://app.example.test/vet/requests", markup)

    async def test_admin_tasks_summary(self) -> None:
        await self.feed(message_update(ADMIN_TG, "/tasks"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertIn("Yangi buyurtmalar", sent[0]["text"])
        markup = str(sent[0]["reply_markup"])
        self.assertIn("https://app.example.test/orders", markup)
        self.assertIn("https://app.example.test/vet", markup)

    async def test_backend_error_falls_back_to_webapp_link(self) -> None:
        self.backend.tasks.pop(VET_TG)
        await self.feed(message_update(VET_TG, "/tasks"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertIn("Veterinariya", sent[0]["text"])
        self.assertIn("https://app.example.test/vet", str(sent[0]["reply_markup"]))


class ReminderTickTests(HandlerTestCase):
    async def asyncSetUp(self) -> None:
        with mock.patch.object(test_handlers, "FakeBackend", VetTasksBackend):
            await super().asyncSetUp()

    async def test_tick_runs_once_per_interval_and_survives_errors(self) -> None:
        from loader import api, bot
        from utils.notifier import NotificationWorker

        worker = NotificationWorker(bot=bot, api=api, reminder_interval=900.0)
        result = await worker.tick_reminders(now=1000.0)
        self.assertEqual(result, {"date": "2026-11-04", "ran": True, "queued": 4})
        self.assertIsNone(await worker.tick_reminders(now=1500.0))  # 15 daqiqa o'tmagan
        self.assertEqual(self.backend.reminder_calls, 1)
        self.backend.reminder_status = 500
        self.assertIsNone(await worker.tick_reminders(now=1901.0))  # xato — faqat jurnal
        self.assertEqual(self.backend.reminder_calls, 2)
        self.backend.reminder_status = 200
        self.assertIsNotNone(await worker.tick_reminders(now=2801.0))
        disabled = NotificationWorker(bot=bot, api=api, reminder_interval=0)
        self.assertIsNone(await disabled.tick_reminders(now=5000.0))
        self.assertEqual(self.backend.reminder_calls, 3)


if __name__ == "__main__":
    unittest.main()
