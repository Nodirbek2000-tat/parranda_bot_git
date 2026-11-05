"""V3 logistika: ``/tasks`` ro‘yxatlari, inline tugmalar, dalil rasmi (FSM) va egasining tasdig‘i (API_CONTRACT_V3 §14).

Soxta backend kontraktdagi bot endpointlarini holat mashinasi bilan taqlid qiladi; Telegram so‘rovlari ushlab olinadi.

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import io
import itertools
import json
import logging
import unittest
from typing import Any, Optional
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestServer
from aiogram import types
from aiogram.utils.exceptions import FileIsTooBig

from tests import test_handlers
from tests.test_bot import ADMIN_TG, OWNER_TG, TOKEN, WAREHOUSE_TG
from tests.test_handlers import HandlerTestCase, message_update
from tests.test_v3_menus import LOGISTICS_TG, V3Backend
from handlers.users.task_actions import download_file as ORIGINAL_DOWNLOAD
from utils.api import ApiError, BotApiClient, Forbidden
from utils.logistics_tasks import (
    callback_data,
    find_task,
    parse_callback,
    task_markup,
    task_text,
)

OTHER_LOGISTICS_TG = 668
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.4\n" + b"\x00" * 16
_ids = itertools.count(10_000)

STATUS_DISPLAY = {
    "NEW": "Yangi", "ASSIGNED": "Biriktirildi", "ACCEPTED": "Ishga olindi", "IN_TRANSIT": "Yo‘lda",
    "DELIVERED": "Yetkazildi", "CONFIRMED": "Tasdiqlandi", "CANCELLED": "Bekor qilindi",
}
#: amal -> (ruxsat etilgan holat, yangi holat, rollar)
TRANSITIONS = {
    "accept": ("ASSIGNED", "ACCEPTED", ("LOGISTICS", "ADMIN")),
    "start": ("ACCEPTED", "IN_TRANSIT", ("LOGISTICS", "ADMIN")),
    "deliver": ("IN_TRANSIT", "DELIVERED", ("LOGISTICS", "ADMIN")),
    "confirm": ("DELIVERED", "CONFIRMED", ("OWNER", "ADMIN")),
}
HOUSEHOLD = {"id": 3, "code": "XN-0003", "name": "Navbahor 12-uy"}


def make_task(task_id: int, status: str, **extra: Any) -> dict[str, Any]:
    task = {
        "id": task_id, "code": f"LG-{task_id:06d}", "status": status, "household": dict(HOUSEHOLD),
        "address": "Samarqand viloyati, Navobod tumani, Navbahor MFY, 12-uy", "planned_date": "2026-11-06",
        "is_overdue": False, "order": None, "items_text": "Yem PK-1 — 150 kg", "vehicle_text": "", "driver_text": "",
        "worker": LOGISTICS_TG,
    }
    task.update(extra)
    return task


def callback_update(user_id: int, data: str, message_id: int = 900, chat_type: str = "private") -> types.Update:
    return types.Update(update_id=next(_ids), callback_query={
        "id": str(next(_ids)), "chat_instance": "ci", "data": data,
        "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        "message": {
            "message_id": message_id, "date": 1762230000, "text": "eski matn",
            "chat": {"id": user_id, "type": chat_type},
            "from": {"id": 1, "is_bot": True, "first_name": "NNP"},
        },
    })


def photo_message(user_id: int, *, group: Optional[str] = None, big_last: bool = True) -> types.Update:
    sizes = [
        {"file_id": "small", "file_unique_id": "u1", "width": 90, "height": 90, "file_size": 1_000},
        {"file_id": "large", "file_unique_id": "u2", "width": 1280, "height": 960, "file_size": 250_000},
    ]
    if big_last:
        sizes.append({"file_id": "huge", "file_unique_id": "u3", "width": 4000, "height": 3000,
                      "file_size": 11 * 1024 * 1024})
    extra: dict[str, Any] = {"photo": sizes}
    if group:
        extra["media_group_id"] = group
    return message_update(user_id, None, **extra)


def document_message(user_id: int, mime: str, name: str, size: int = 5_000) -> types.Update:
    return message_update(user_id, None, document={
        "file_id": f"doc-{name}", "file_unique_id": f"ud-{name}", "file_name": name, "mime_type": mime,
        "file_size": size,
    })


class LogisticsBackend(V3Backend):
    """V3Backend + ``bot/users/{tid}/tasks``, ``bot/tasks/{id}/<amal>`` va ``bot/files`` (holat mashinasi bilan)."""

    def __init__(self) -> None:
        super().__init__()
        from tests.test_bot import make_user

        self.users[OTHER_LOGISTICS_TG] = make_user(10, "logist2", "LOGISTICS", None)
        self.tasks: dict[int, dict[str, Any]] = {
            12: make_task(12, "ASSIGNED", vehicle_text="01 A 123 BC, Isuzu NPR", driver_text="Sardor Rahimov"),
            13: make_task(13, "IN_TRANSIT", planned_date="2026-11-01", is_overdue=True),
            14: make_task(14, "DELIVERED", order={"id": 5, "code": "BY-000005"}),
            15: make_task(15, "NEW", worker=None),
        }
        self.open_orders = [{"id": 5, "code": "BY-000005", "status": "IN_DELIVERY", "status_display": "Yetkazilmoqda"}]
        self.upcoming_vet = [{"id": 4, "code": "VT-000004", "purpose": "Rejali ko‘rik", "planned_date": "2026-11-07"}]
        self.action_calls: list[tuple[str, int, dict[str, Any]]] = []
        self.uploads: list[dict[str, Any]] = []
        self.forced: dict[str, tuple[int, Any]] = {}  # amal yoki "upload" -> (status, body)
        self.tasks_down = False
        self.app.router.add_get("/api/bot/users/{telegram_id}/tasks", self.get_tasks)
        self.app.router.add_post("/api/bot/tasks/{id}/{action}", self.task_action)
        self.app.router.add_post("/api/bot/files", self.upload)

    # -- helpers

    def role(self, telegram_id: int) -> Optional[str]:
        user = self.users.get(telegram_id)
        return user["role"] if user else None

    def allowed(self, task: dict[str, Any], telegram_id: int) -> list[str]:
        role = self.role(telegram_id)
        result = []
        for action, (status, _, roles) in TRANSITIONS.items():
            if task["status"] != status or role not in roles:
                continue
            if role == "LOGISTICS" and task.get("worker") not in (None, telegram_id):
                continue
            if role == "LOGISTICS" and task.get("worker") is None and action != "accept":
                continue
            result.append(action)
        return result

    def short(self, task: dict[str, Any], telegram_id: int) -> dict[str, Any]:
        data = {k: v for k, v in task.items() if k != "worker"}
        data["status_display"] = STATUS_DISPLAY[task["status"]]
        data["allowed_actions"] = self.allowed(task, telegram_id)
        return data

    # -- endpoints

    async def get_tasks(self, request: web.Request) -> web.Response:
        if self.tasks_down:
            return web.Response(status=503, text="down")
        telegram_id = int(request.match_info["telegram_id"])
        role = self.role(telegram_id)
        if role is None:
            return web.json_response({"detail": "Foydalanuvchi topilmadi"}, status=404)
        rows = sorted(self.tasks.values(), key=lambda t: t["id"])
        if role == "LOGISTICS":
            active = [t for t in rows if t["status"] in ("ASSIGNED", "ACCEPTED", "IN_TRANSIT")
                      and t.get("worker") == telegram_id or t["status"] == "NEW"]
            return web.json_response({"role": role, "tasks": [self.short(t, telegram_id) for t in active][:10]})
        if role == "OWNER":
            return web.json_response({
                "role": role,
                "deliveries_to_confirm": [self.short(t, telegram_id) for t in rows if t["status"] == "DELIVERED"],
                "in_transit": [self.short(t, telegram_id) for t in rows if t["status"] == "IN_TRANSIT"],
                "open_orders": self.open_orders, "upcoming_vet": self.upcoming_vet,
            })
        if role == "WAREHOUSE":
            return web.json_response({
                "role": role,
                "to_load": [self.short(t, telegram_id) for t in rows if t["status"] in ("ASSIGNED", "ACCEPTED")],
                "low_stock_count": 2, "expiring_lots": 1,
            })
        if role == "ADMIN":
            return web.json_response({
                "role": role, "orders_new_count": 1, "vet_overdue": 0,
                "orders_new": [{"id": 5, "code": "BY-000005", "household": HOUSEHOLD, "items_text": "Yem PK-1 — 150 kg",
                                "created_at": "2026-11-04T10:00:00+05:00"}],
                "deliveries": {"in_transit": 1, "delivered": 1, "overdue": 1},
            })
        return web.json_response({"role": role, "visits_today": [], "new_requests": 0})

    async def task_action(self, request: web.Request) -> web.Response:
        action = request.match_info["action"]
        task_id = int(request.match_info["id"])
        body = await request.json()
        self.action_calls.append((action, task_id, body))
        if action in self.forced:
            status, payload = self.forced[action]
            return web.json_response(payload, status=status)
        telegram_id = int(body["telegram_id"])
        role = self.role(telegram_id)
        task = self.tasks.get(task_id)
        if role is None:
            return web.json_response({"detail": "Foydalanuvchi topilmadi"}, status=404)
        if task is None or (role == "OWNER" and task["household"]["id"] != 3):
            return web.json_response({"detail": "Topshiriq topilmadi."}, status=404)
        status_from, status_to, roles = TRANSITIONS[action]
        if role not in roles:
            return web.json_response({"detail": "Sizda bu amal uchun ruxsat yo‘q."}, status=403)
        if role == "LOGISTICS" and task.get("worker") not in (None, telegram_id):
            return web.json_response({"detail": "Bu topshiriq boshqa xodimga biriktirilgan."}, status=403)
        if task["status"] != status_from:
            detail = f"Topshiriq holati: {STATUS_DISPLAY[task['status']]}. Bu amalni bajarib bo‘lmaydi."
            return web.json_response({"detail": detail}, status=409)
        if action == "deliver":
            mine = {u["id"] for u in self.uploads if u["telegram_id"] == telegram_id and not u["bound"]}
            ids = body.get("file_ids") or []
            if not ids or not set(ids) <= mine:
                return web.json_response(
                    {"file_ids": ["Yetkazib berish dalilini (foto yoki imzo) biriktiring."]}, status=400)
            for upload in self.uploads:
                if upload["id"] in ids:
                    upload["bound"] = True
        if action == "confirm" and body.get("received_ok") is False and len(body.get("issue_note", "").strip()) < 3:
            return web.json_response({"issue_note": ["Muammoni qisqacha yozing."]}, status=400)
        task["status"] = status_to
        if action == "accept":
            task["worker"] = telegram_id
        return web.json_response(self.short(task, telegram_id))

    async def upload(self, request: web.Request) -> web.Response:
        form = await request.post()
        file = form["file"]
        content = file.file.read()
        file.file.close()
        record = {
            "id": next(_ids), "telegram_id": int(form["telegram_id"]), "purpose": form["purpose"],
            "filename": file.filename, "content_type": file.content_type, "content": content, "bound": False,
        }
        if "upload" in self.forced:
            status, payload = self.forced.pop("upload")
            return web.json_response(payload, status=status)
        self.uploads.append(record)
        return web.json_response({
            "id": record["id"], "name": file.filename, "content_type": file.content_type, "size": len(content),
            "purpose": form["purpose"], "url": f"/api/files/{record['id']}", "created_at": "2026-11-04T12:00:00+05:00",
        }, status=201)


# ====================================================================== pure functions


class CallbackDataTests(unittest.TestCase):
    def test_valid_round_trip(self) -> None:
        for code in ("acc", "go", "dlv", "cnf", "iss"):
            data = callback_data(code, 12)
            self.assertEqual(parse_callback(data), (code, 12))
            self.assertLessEqual(len(data.encode()), 64)
        self.assertEqual(parse_callback(f"t:acc:{2**63 - 1}"), ("acc", 2**63 - 1))

    def test_rejects_everything_else(self) -> None:
        for data in (None, "", "t:acc:", "t:acc:0", "t:acc:012", "t:acc:-1", "t:acc:1.5", "t:del:1", "x:acc:1",
                     "t:acc:1:2", " t:acc:1", "t:acc:1 ", "t:acc:１２", f"t:acc:{2**63}", "t:acc:" + "9" * 19,
                     "t:ACC:1", "t:acc:12\n"):
            with self.subTest(data=data):
                self.assertIsNone(parse_callback(data))


class TaskTextTests(unittest.TestCase):
    def test_contract_example(self) -> None:
        task = make_task(12, "ASSIGNED", status_display="Biriktirildi")
        self.assertEqual(
            task_text(task),
            "🚚 <b>LG-000012</b> — Biriktirildi\n"
            "Xonadon: Navbahor 12-uy (XN-0003)\n"
            "Manzil: Samarqand viloyati, Navobod tumani, Navbahor MFY, 12-uy\n"
            "Yuk: Yem PK-1 — 150 kg\n"
            "Reja: 06.11.2026",
        )

    def test_escaping_vehicle_driver_and_overdue(self) -> None:
        task = make_task(13, "IN_TRANSIT", status_display="Yo‘lda", is_overdue=True, planned_date="2026-11-01",
                         household={"id": 3, "code": "XN-0003", "name": "<b>Uy</b> & bog‘"},
                         vehicle_text="01 A 123 BC, Isuzu", driver_text="Sardor <Rahimov>", items_text="A & B")
        text = task_text(task)
        self.assertIn("Xonadon: &lt;b&gt;Uy&lt;/b&gt; &amp; bog‘ (XN-0003)", text)
        self.assertIn("Yuk: A &amp; B", text)
        self.assertIn("Transport: 01 A 123 BC, Isuzu", text)
        self.assertIn("Haydovchi: Sardor &lt;Rahimov&gt;", text)
        self.assertIn("Reja: 01.11.2026 ⚠️ muddati o‘tgan", text)
        no_date = task_text(make_task(1, "NEW", status_display="Yangi", planned_date=None))
        self.assertNotIn("Reja", no_date)

    def test_markup_follows_allowed_actions_and_webapp_paths(self) -> None:
        web = "https://app.example.test"
        staff = task_markup({"id": 12, "allowed_actions": ["assign", "accept", "cancel"]}, "LOGISTICS", web)
        rows = staff.inline_keyboard
        self.assertEqual([b.callback_data for b in rows[0]], ["t:acc:12"])
        self.assertEqual(rows[0][0].text, "✅ Qabul qilish")
        self.assertEqual(rows[-1][0].web_app.url, f"{web}/logistics/12")
        self.assertEqual(len(rows), 2)  # assign/cancel — faqat Web App’da

        owner = task_markup({"id": 14, "order": {"id": 5}, "allowed_actions": ["confirm"]}, "OWNER", web)
        self.assertEqual([b.callback_data for b in owner.inline_keyboard[0]], ["t:cnf:14", "t:iss:14"])
        self.assertEqual(owner.inline_keyboard[1][0].web_app.url, f"{web}/my/orders/5")
        no_order = task_markup({"id": 14, "order": None, "allowed_actions": []}, "OWNER", web)
        self.assertEqual(no_order.inline_keyboard[0][0].web_app.url, f"{web}/my/deliveries")

        self.assertIsNone(task_markup({"id": 1, "allowed_actions": []}, "LOGISTICS", ""))
        only_actions = task_markup({"id": 13, "allowed_actions": ["deliver"]}, "LOGISTICS", "")
        self.assertEqual(only_actions.inline_keyboard[0][0].text, "📦 Yetkazdim (foto bilan)")
        self.assertEqual(len(only_actions.inline_keyboard), 1)
        stripped = task_markup({"id": 13, "allowed_actions": ["deliver"]}, "LOGISTICS", web, with_actions=False)
        self.assertEqual(len(stripped.inline_keyboard), 1)

    def test_find_task_searches_every_list(self) -> None:
        payload = {"tasks": [{"id": 1}], "deliveries_to_confirm": [{"id": 2}], "in_transit": [{"id": 3}],
                   "to_load": [{"id": 4}]}
        for task_id in (1, 2, 3, 4):
            self.assertEqual(find_task(payload, task_id), {"id": task_id})
        self.assertIsNone(find_task(payload, 5))


# ====================================================================== handlers


class LogisticsHandlerTestCase(HandlerTestCase):
    async def asyncSetUp(self) -> None:
        with mock.patch.object(test_handlers, "FakeBackend", LogisticsBackend):
            await super().asyncSetUp()
        from handlers.users import task_actions

        self.task_actions = task_actions
        task_actions._recent_media_groups.clear()
        self.download = mock.AsyncMock(return_value=JPEG)
        patcher = mock.patch.object(task_actions, "download_file", self.download)
        patcher.start()
        self.addCleanup(patcher.stop)

    def method_calls(self, method: str) -> list[dict[str, Any]]:
        return [data for name, data in self.calls if name == method]

    def answers(self) -> list[dict[str, Any]]:
        return self.method_calls("answerCallbackQuery")

    def edits(self) -> list[dict[str, Any]]:
        return self.method_calls("editMessageText")

    async def state(self, user_id: int) -> Optional[str]:
        return await test_handlers.dp.storage.get_state(chat=user_id, user=user_id)


class TasksListTests(LogisticsHandlerTestCase):
    async def test_logistics_gets_one_message_per_task_with_its_buttons(self) -> None:
        await self.feed(message_update(LOGISTICS_TG, "📋 Topshiriqlarim"))
        sent = self.sent()
        self.assertEqual(len(sent), 4)  # sarlavha + 12, 13, 15
        self.assertIn("📋 <b>Mening topshiriqlarim</b>", sent[0]["text"])
        self.assertIn("Faol: <b>3</b> · yo‘lda: <b>1</b> · biriktirilmagan: <b>1</b> · muddati o‘tgan: <b>1</b>",
                      sent[0]["text"])
        self.assertIn("https://app.example.test/logistics", str(sent[0]["reply_markup"]))
        self.assertTrue(sent[1]["text"].startswith("🚚 <b>LG-000012</b> — Biriktirildi"))
        self.assertIn("Transport: 01 A 123 BC, Isuzu NPR", sent[1]["text"])
        self.assertIn("t:acc:12", str(sent[1]["reply_markup"]))
        self.assertIn("https://app.example.test/logistics/12", str(sent[1]["reply_markup"]))
        self.assertIn("t:dlv:13", str(sent[2]["reply_markup"]))
        self.assertIn("⚠️ muddati o‘tgan", sent[2]["text"])
        # Biriktirilmagan NEW: qabul qilishdan oldin Web App’da biriktirish kerak — amal tugmasi yo‘q.
        self.assertTrue(sent[3]["text"].startswith("🚚 <b>LG-000015</b> — Yangi"))
        self.assertNotIn("callback_data", str(sent[3]["reply_markup"]))

    async def test_logistics_list_is_capped_at_ten(self) -> None:
        for task_id in range(100, 112):
            self.backend.tasks[task_id] = make_task(task_id, "ASSIGNED")
        await self.feed(message_update(LOGISTICS_TG, "/tasks"))
        self.assertEqual(len(self.sent()), 11)
        self.assertIn("Birinchi 10 tasi ko‘rsatilgan", self.sent()[0]["text"])

    async def test_logistics_without_tasks(self) -> None:
        self.backend.tasks.clear()
        await self.feed(message_update(LOGISTICS_TG, "/tasks"))
        self.assertEqual(len(self.sent()), 1)
        self.assertIn("Hozircha faol topshiriq yo‘q ✅", self.sent()[0]["text"])

    async def test_owner_header_and_delivery_messages(self) -> None:
        await self.feed(message_update(OWNER_TG, "📋 Topshiriqlar"))
        sent = self.sent()
        self.assertEqual(len(sent), 3)  # sarlavha + tasdiq kutayotgan 14 + yo‘ldagi 13
        header = sent[0]["text"]
        self.assertIn("Tasdiqlash kutilmoqda: <b>1</b> · Yo‘lda: <b>1</b>", header)
        self.assertIn("• <b>BY-000005</b> — Yetkazilmoqda", header)
        self.assertIn("• <b>VT-000004</b> — Rejali ko‘rik · 07.11.2026", header)
        self.assertIn("https://app.example.test/my/orders", str(sent[0]["reply_markup"]))
        self.assertIn("LG-000014", sent[1]["text"])
        markup = str(sent[1]["reply_markup"])
        self.assertIn("t:cnf:14", markup)
        self.assertIn("t:iss:14", markup)
        self.assertIn("https://app.example.test/my/orders/5", markup)
        self.assertNotIn("t:", str(sent[2]["reply_markup"]).replace("https:", ""))  # yo‘ldagi: faqat Web App
        self.assertIn("https://app.example.test/my/deliveries", str(sent[2]["reply_markup"]))

    async def test_warehouse_summary(self) -> None:
        await self.feed(message_update(WAREHOUSE_TG, "/tasks"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        text = sent[0]["text"]
        self.assertIn("🚚 <b>Yuklash kutilmoqda</b> (1)", text)
        self.assertIn("<b>LG-000012</b> — Navbahor 12-uy (XN-0003) · Yem PK-1 — 150 kg · 06.11.2026 · Biriktirildi",
                      text)
        self.assertIn("📉 Kam qolgan mahsulotlar: <b>2</b>", text)
        self.assertIn("⏳ Muddati yaqin partiyalar: <b>1</b>", text)
        markup = str(sent[0]["reply_markup"])
        self.assertIn("https://app.example.test/warehouse", markup)
        self.assertIn("https://app.example.test/logistics", markup)
        self.assertNotIn("callback_data", markup)

    async def test_admin_summary_links_pending_orders(self) -> None:
        await self.feed(message_update(ADMIN_TG, "/tasks"))
        markup = str(self.sent()[0]["reply_markup"])
        self.assertIn("https://app.example.test/orders/5", markup)
        self.assertIn("BY-000005", markup)
        self.assertIn("https://app.example.test/logistics", markup)

    async def test_backend_down_falls_back_to_webapp(self) -> None:
        self.backend.tasks_down = True
        await self.feed(message_update(LOGISTICS_TG, "/tasks"))
        sent = self.sent()
        self.assertEqual(len(sent), 1)
        self.assertIn("https://app.example.test/logistics", str(sent[0]["reply_markup"]))

    async def test_without_webapp_no_webapp_buttons(self) -> None:
        with mock.patch.object(test_handlers.config, "WEBAPP_ENABLED", False):
            await self.feed(message_update(LOGISTICS_TG, "/tasks"))
        sent = self.sent()
        self.assertIn("Platforma havolasi hali sozlanmagan", sent[0]["text"])
        self.assertNotIn("web_app", str(sent[1]["reply_markup"]))
        self.assertIn("t:acc:12", str(sent[1]["reply_markup"]))


class TaskButtonTests(LogisticsHandlerTestCase):
    async def test_accept_then_start_edit_the_message(self) -> None:
        await self.feed(callback_update(LOGISTICS_TG, "t:acc:12"))
        self.assertEqual(self.backend.action_calls, [("accept", 12, {"telegram_id": LOGISTICS_TG})])
        edit = self.edits()[0]
        self.assertEqual((edit["chat_id"], edit["message_id"]), (LOGISTICS_TG, 900))
        self.assertTrue(edit["text"].startswith("🚚 <b>LG-000012</b> — Ishga olindi"))
        self.assertIn("t:go:12", str(edit["reply_markup"]))
        self.assertNotIn("t:acc:12", str(edit["reply_markup"]))
        self.assertEqual(self.answers()[0]["text"], "Bajarildi ✅")

        await self.feed(callback_update(LOGISTICS_TG, "t:go:12"))
        self.assertEqual(self.backend.tasks[12]["status"], "IN_TRANSIT")
        self.assertIn("— Yo‘lda", self.edits()[0]["text"])
        self.assertIn("t:dlv:12", str(self.edits()[0]["reply_markup"]))

    async def test_conflict_shows_detail_and_refreshes_from_tasks(self) -> None:
        self.backend.tasks[12]["status"] = "ACCEPTED"
        await self.feed(callback_update(LOGISTICS_TG, "t:acc:12"))
        answer = self.answers()[0]
        self.assertEqual(answer["text"], "Topshiriq holati: Ishga olindi. Bu amalni bajarib bo‘lmaydi.")
        self.assertTrue(answer["show_alert"])
        self.assertIn("— Ishga olindi", self.edits()[0]["text"])
        self.assertIn("t:go:12", str(self.edits()[0]["reply_markup"]))

    async def test_conflict_for_task_gone_from_list_strips_action_buttons(self) -> None:
        self.backend.tasks[13]["status"] = "DELIVERED"
        await self.feed(callback_update(LOGISTICS_TG, "t:go:13"))
        self.assertIn("Yetkazildi", self.answers()[0]["text"])
        markups = self.method_calls("editMessageReplyMarkup")
        self.assertEqual(len(markups), 1)
        self.assertNotIn("callback_data", str(markups[0]["reply_markup"]))
        self.assertIn("https://app.example.test/logistics/13", str(markups[0]["reply_markup"]))

    async def test_other_worker_gets_forbidden_detail(self) -> None:
        await self.feed(callback_update(OTHER_LOGISTICS_TG, "t:acc:12"))
        self.assertEqual(self.answers()[0]["text"], "Bu topshiriq boshqa xodimga biriktirilgan.")
        self.assertEqual(self.backend.tasks[12]["status"], "ASSIGNED")

    async def test_invalid_or_foreign_callbacks_never_reach_the_backend(self) -> None:
        for data in ("t:acc:abc", "t:del:12", "t:acc:0", "t:acc:12:1", "t:" + "1" * 70):
            with self.subTest(data=data):
                await self.feed(callback_update(LOGISTICS_TG, data))
                self.assertIn("eskirgan yoki noto‘g‘ri", self.answers()[0]["text"])
        await self.feed(callback_update(LOGISTICS_TG, "t:acc:12", chat_type="group"))
        self.assertIn("eskirgan yoki noto‘g‘ri", self.answers()[0]["text"])
        self.assertEqual(self.backend.action_calls, [])

    async def test_unlinked_user(self) -> None:
        await self.feed(callback_update(999, "t:acc:12"))
        self.assertIn("/start", self.answers()[0]["text"])
        self.assertEqual(self.backend.action_calls, [])

    async def test_backend_down_answers_with_alert(self) -> None:
        self.backend.forced["accept"] = (503, {"detail": "x"})
        await self.feed(callback_update(LOGISTICS_TG, "t:acc:12"))
        answer = self.answers()[0]
        self.assertEqual(answer["text"], "Server bilan aloqa yo‘q, birozdan keyin urinib ko‘ring.")
        self.assertTrue(answer["show_alert"])
        self.assertEqual(self.edits(), [])

    async def test_owner_confirms_receipt(self) -> None:
        await self.feed(callback_update(OWNER_TG, "t:cnf:14"))
        self.assertEqual(self.backend.action_calls,
                         [("confirm", 14, {"telegram_id": OWNER_TG, "received_ok": True, "issue_note": ""})])
        edit = self.edits()[0]
        self.assertIn("— Tasdiqlandi", edit["text"])
        self.assertNotIn("callback_data", str(edit["reply_markup"]))
        self.assertIn("https://app.example.test/my/orders/5", str(edit["reply_markup"]))
        self.assertEqual(self.answers()[0]["text"], "Bajarildi ✅")

    async def test_logistics_cannot_confirm(self) -> None:
        await self.feed(callback_update(LOGISTICS_TG, "t:cnf:14"))
        self.assertEqual(self.answers()[0]["text"], "Sizda bu amal uchun ruxsat yo‘q.")
        self.assertEqual(self.backend.tasks[14]["status"], "DELIVERED")


class DeliveryProofTests(LogisticsHandlerTestCase):
    async def open_step(self, task_id: int = 13) -> None:
        await self.feed(callback_update(LOGISTICS_TG, f"t:dlv:{task_id}", message_id=901))

    async def test_full_photo_flow(self) -> None:
        await self.open_step()
        self.assertIn("Yetkazib berish dalili: mahsulot yoki imzo rasmini yuboring (bekor qilish: /cancel)",
                      self.texts())
        self.assertIn("<b>LG-000013</b>", self.texts())
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")
        self.assertEqual(self.backend.action_calls, [])

        await self.feed(message_update(LOGISTICS_TG, "salom"))
        self.assertIn("Yetkazib berish dalili", self.texts())
        await self.feed(message_update(LOGISTICS_TG, "/tasks"))
        self.assertIn("Yetkazib berish dalili", self.texts())
        await self.feed(message_update(LOGISTICS_TG, None, location={"latitude": 39.6, "longitude": 66.9}))
        self.assertIn("Yetkazib berish dalili", self.texts())
        self.assertEqual(self.backend.uploads, [])

        await self.feed(photo_message(LOGISTICS_TG))
        self.download.assert_awaited_once_with("large")  # eng kattasi, lekin ≤ 10 MB
        upload = self.backend.uploads[0]
        self.assertEqual((upload["telegram_id"], upload["purpose"], upload["content_type"], upload["content"]),
                         (LOGISTICS_TG, "DELIVERY_PROOF", "image/jpeg", JPEG))
        self.assertTrue(upload["filename"].endswith(".jpg"))
        self.assertEqual(self.backend.action_calls,
                         [("deliver", 13, {"telegram_id": LOGISTICS_TG, "file_ids": [upload["id"]], "note": ""})])
        self.assertEqual(self.backend.tasks[13]["status"], "DELIVERED")
        edit = self.edits()[0]
        self.assertEqual(edit["message_id"], 901)
        self.assertIn("— Yetkazildi", edit["text"])
        self.assertNotIn("callback_data", str(edit["reply_markup"]))
        self.assertIn("✅ <b>LG-000013</b> — Yetkazildi. Xonadon egasining tasdig‘i kutilmoqda.", self.texts())
        self.assertIsNone(await self.state(LOGISTICS_TG))

    async def test_pdf_and_image_documents_are_accepted(self) -> None:
        await self.open_step()
        self.download.return_value = PDF
        await self.feed(document_message(LOGISTICS_TG, "application/pdf", "imzo.pdf"))
        upload = self.backend.uploads[0]
        self.assertEqual((upload["filename"], upload["content_type"]), ("imzo.pdf", "application/pdf"))
        self.assertEqual(self.backend.tasks[13]["status"], "DELIVERED")

    async def test_document_without_proper_extension_gets_one(self) -> None:
        await self.open_step()
        await self.feed(document_message(LOGISTICS_TG, "image/png", "skan"))
        self.assertRegex(self.backend.uploads[0]["filename"], r"^dalil_\d+\.png$")

    async def test_wrong_type_or_too_big_files_are_refused_locally(self) -> None:
        await self.open_step()
        await self.feed(document_message(LOGISTICS_TG, "video/mp4", "kino.mp4"))
        self.assertIn("Faqat JPG, PNG, WEBP rasm yoki PDF fayl yuborish mumkin.", self.texts())
        await self.feed(document_message(LOGISTICS_TG, "image/jpeg", "katta.jpg", size=11 * 1024 * 1024))
        self.assertIn("Fayl hajmi 10 MB dan oshmasligi kerak.", self.texts())
        self.download.return_value = b"\xff" * (10 * 1024 * 1024 + 1)  # hajmi oldindan noma’lum bo‘lsa ham
        await self.feed(photo_message(LOGISTICS_TG, big_last=False))
        self.assertIn("Fayl hajmi 10 MB dan oshmasligi kerak.", self.texts())
        self.assertEqual(self.backend.uploads, [])
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")

    async def test_rejected_file_keeps_the_step_open(self) -> None:
        await self.open_step()
        self.backend.forced["upload"] = (400, {"file": ["Faqat JPG, PNG, WEBP yoki PDF fayl yuklash mumkin."]})
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertIn("⚠️ Faqat JPG, PNG, WEBP yoki PDF fayl yuklash mumkin.\nQayta urinib ko‘ring yoki /cancel.",
                      self.texts())
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")
        self.assertEqual(self.backend.action_calls, [])
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertEqual(self.backend.tasks[13]["status"], "DELIVERED")
        self.assertIsNone(await self.state(LOGISTICS_TG))

    async def test_backend_down_and_telegram_errors_keep_the_step_open(self) -> None:
        await self.open_step()
        self.backend.forced["upload"] = (503, "down")
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertIn("Server bilan aloqa yo‘q", self.texts())
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")
        self.download.side_effect = FileIsTooBig("File is too big")
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertIn("Faylni Telegramdan olib bo‘lmadi.", self.texts())
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")
        self.download.side_effect = RuntimeError("kutilmagan")
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertEqual(await self.state(LOGISTICS_TG), "DeliveryProof:photo")  # yopilib qolmaydi

    async def test_conflict_on_deliver_ends_the_step(self) -> None:
        await self.open_step()
        self.backend.tasks[13]["status"] = "CANCELLED"
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertIn("⚠️ Topshiriq holati: Bekor qilindi. Bu amalni bajarib bo‘lmaydi.", self.texts())
        self.assertIsNone(await self.state(LOGISTICS_TG))
        markups = self.method_calls("editMessageReplyMarkup")
        self.assertEqual(markups[0]["message_id"], 901)
        self.assertNotIn("callback_data", str(markups[0]["reply_markup"]))

    async def test_deliver_not_allowed_now_does_not_open_the_step(self) -> None:
        await self.feed(callback_update(LOGISTICS_TG, "t:dlv:12"))  # ASSIGNED: avval qabul qilish kerak
        self.assertEqual(self.answers()[0]["text"], "Topshiriq holati: Biriktirildi. Bu amalni bajarib bo‘lmaydi.")
        self.assertIsNone(await self.state(LOGISTICS_TG))
        self.assertIn("t:acc:12", str(self.edits()[0]["reply_markup"]))

    async def test_album_uploads_once_and_rest_is_silent(self) -> None:
        await self.open_step()
        await self.feed(photo_message(LOGISTICS_TG, group="album-1"))
        self.assertEqual(len(self.backend.uploads), 1)
        await self.feed(photo_message(LOGISTICS_TG, group="album-1"))
        self.assertEqual(self.calls, [])  # na yuklash, na menyu
        await self.feed(photo_message(LOGISTICS_TG, group="album-2"))
        self.assertIn("Iltimos, quyidagi menyudan foydalaning.", self.texts())
        self.assertEqual(len(self.backend.uploads), 1)

    async def test_second_message_while_uploading(self) -> None:
        await self.open_step()
        storage = test_handlers.dp.storage
        await storage.set_state(chat=LOGISTICS_TG, user=LOGISTICS_TG, state="DeliveryProof:uploading")
        await storage.update_data(chat=LOGISTICS_TG, user=LOGISTICS_TG, data={"media_group_id": "g1"})
        await self.feed(photo_message(LOGISTICS_TG, group="g1"))
        self.assertEqual(self.calls, [])
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertIn("⏳ Dalil yuklanmoqda, biroz kuting.", self.texts())
        self.assertEqual(self.backend.uploads, [])

    async def test_cancel_closes_the_step(self) -> None:
        await self.open_step()
        await self.feed(message_update(LOGISTICS_TG, "/cancel"))
        self.assertIn("Amal bekor qilindi.", self.texts())
        self.assertIsNone(await self.state(LOGISTICS_TG))
        await self.feed(photo_message(LOGISTICS_TG))
        self.assertEqual(self.backend.uploads, [])

    async def test_download_file_reads_from_telegram(self) -> None:
        async def fake_download(file_id: str, destination: io.BytesIO, **_: Any) -> io.BytesIO:
            destination.write(JPEG)
            return destination

        with mock.patch.object(test_handlers.bot, "download_file_by_id", side_effect=fake_download) as patched:
            self.assertEqual(await ORIGINAL_DOWNLOAD("file-1"), JPEG)
        patched.assert_awaited_once()
        self.assertEqual(patched.await_args.args[0], "file-1")


class OwnerIssueTests(LogisticsHandlerTestCase):
    async def test_issue_flow(self) -> None:
        await self.feed(callback_update(OWNER_TG, "t:iss:14", message_id=902))
        self.assertIn("Muammoni qisqacha yozing (3–1000 belgi). Bekor qilish: /cancel", self.texts())
        self.assertEqual(await self.state(OWNER_TG), "DeliveryIssue:note")

        await self.feed(message_update(OWNER_TG, "ok"))
        self.assertIn("Muammo matni 3 dan 1000 belgigacha bo‘lishi kerak.", self.texts())
        await self.feed(message_update(OWNER_TG, "x" * 1001))
        self.assertIn("Muammo matni 3 dan 1000 belgigacha", self.texts())
        await self.feed(photo_message(OWNER_TG))
        self.assertIn("Muammoni qisqacha yozing", self.texts())
        self.assertEqual(self.backend.action_calls, [])

        await self.feed(message_update(OWNER_TG, "  Qop <yirtilgan>, 5 kg kam  "))
        self.assertEqual(self.backend.action_calls, [
            ("confirm", 14, {"telegram_id": OWNER_TG, "received_ok": False, "issue_note": "Qop <yirtilgan>, 5 kg kam"})
        ])
        self.assertEqual(self.edits()[0]["message_id"], 902)
        self.assertIn("— Tasdiqlandi", self.edits()[0]["text"])
        self.assertIn("⚠️ <b>LG-000014</b> — muammo qayd etildi. Ma’lumot administratorga yuborildi.", self.texts())
        self.assertIsNone(await self.state(OWNER_TG))

    async def test_server_validation_keeps_step_and_conflict_ends_it(self) -> None:
        await self.feed(callback_update(OWNER_TG, "t:iss:14"))
        self.backend.forced["confirm"] = (400, {"issue_note": ["Muammoni qisqacha yozing."]})
        await self.feed(message_update(OWNER_TG, "abc"))
        self.assertIn("⚠️ Muammoni qisqacha yozing.\nQayta urinib ko‘ring yoki /cancel.", self.texts())
        self.assertEqual(await self.state(OWNER_TG), "DeliveryIssue:note")
        self.backend.forced["confirm"] = (409, {"detail": "Topshiriq holati: Tasdiqlandi. Bu amalni bajarib bo‘lmaydi."})
        await self.feed(message_update(OWNER_TG, "abcd"))
        self.assertIn("Topshiriq holati: Tasdiqlandi.", self.texts())
        self.assertIsNone(await self.state(OWNER_TG))

    async def test_confirm_button_closes_an_open_issue_step_for_the_same_task(self) -> None:
        await self.feed(callback_update(OWNER_TG, "t:iss:14"))
        await self.feed(callback_update(OWNER_TG, "t:cnf:14"))
        self.assertIsNone(await self.state(OWNER_TG))
        self.assertEqual(self.backend.tasks[14]["status"], "CONFIRMED")

    async def test_issue_on_confirmed_task_is_refused(self) -> None:
        self.backend.tasks[14]["status"] = "CONFIRMED"
        await self.feed(callback_update(OWNER_TG, "t:iss:14"))
        self.assertIn("faol ro‘yxatda yo‘q", self.answers()[0]["text"])
        self.assertIsNone(await self.state(OWNER_TG))
        self.assertEqual(self.backend.action_calls, [])
        markups = self.method_calls("editMessageReplyMarkup")
        self.assertNotIn("callback_data", str(markups[0]["reply_markup"]))
        self.assertIn("https://app.example.test/my/deliveries", str(markups[0]["reply_markup"]))

    async def test_step_opens_when_the_list_is_cut_and_the_server_decides(self) -> None:
        # 10 ta tasdiq kutayotgan: 14-topshiriq ro‘yxatdan tashqarida qolishi mumkin — bosqich ochiladi.
        for task_id in range(200, 210):
            self.backend.tasks[task_id] = make_task(task_id, "DELIVERED")
        self.backend.tasks[14]["status"] = "CONFIRMED"
        await self.feed(callback_update(OWNER_TG, "t:iss:14"))
        self.assertEqual(await self.state(OWNER_TG), "DeliveryIssue:note")
        await self.feed(message_update(OWNER_TG, "Qop yirtilgan"))
        self.assertIn("Topshiriq holati: Tasdiqlandi.", self.texts())
        self.assertIsNone(await self.state(OWNER_TG))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls) -> None:
        logging.disable(logging.NOTSET)

    async def asyncSetUp(self) -> None:
        self.backend = LogisticsBackend()
        self.server = TestServer(self.backend.app)
        await self.server.start_server()
        self.client = BotApiClient(str(self.server.make_url("/api")), TOKEN)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.close()

    async def test_upload_is_multipart_and_actions_are_json(self) -> None:
        uploaded = await self.client.upload_file(LOGISTICS_TG, "DELIVERY_PROOF", "d.jpg", JPEG, "image/jpeg")
        self.assertEqual(uploaded["url"], f"/api/files/{uploaded['id']}")
        record = self.backend.uploads[0]
        self.assertEqual((record["filename"], record["content_type"], record["content"]), ("d.jpg", "image/jpeg", JPEG))
        await self.client.accept_task(LOGISTICS_TG, 12)
        await self.client.start_task(LOGISTICS_TG, 12)
        task = await self.client.deliver_task(LOGISTICS_TG, 12, [uploaded["id"]], note="eshik oldida")
        self.assertEqual(task["status"], "DELIVERED")
        self.assertEqual(self.backend.action_calls[-1][2],
                         {"telegram_id": LOGISTICS_TG, "file_ids": [uploaded["id"]], "note": "eshik oldida"})
        self.assertEqual(json.dumps(self.backend.paths[-1]), json.dumps("/api/bot/tasks/12/deliver"))

    async def test_errors_keep_server_detail(self) -> None:
        with self.assertRaises(Forbidden) as caught:
            await self.client.confirm_task(LOGISTICS_TG, 14, received_ok=True)
        self.assertEqual(caught.exception.detail, "Sizda bu amal uchun ruxsat yo‘q.")
        self.backend.forced["start"] = (200, {"unexpected": True})
        with self.assertRaises(ApiError):
            await self.client.start_task(LOGISTICS_TG, 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
