import support  # noqa: F401  (must be first)

import unittest
from unittest import mock

from aiogram import Bot, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext

import config
import handlers
import keyboards as kb
import loader
import texts
from api import ApiError, NotFound, Unavailable
from support import TG_ID, WEBAPP, make_message, markup_urls, user


def fake_api(**overrides) -> mock.MagicMock:
    api = mock.MagicMock()
    api.me = mock.AsyncMock(return_value=user())
    api.link = mock.AsyncMock(return_value=user())
    api.unlink = mock.AsyncMock(return_value={})
    api.tasks = mock.AsyncMock(return_value=[])
    for name, value in overrides.items():
        setattr(api, name, value)
    return api


class HandlerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.api = fake_api()
        patcher = mock.patch.object(handlers, "api", self.api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = FSMContext(MemoryStorage(), chat=TG_ID, user=TG_ID)

    def answers(self, message) -> list:
        return [c.args[0] if c.args else c.kwargs.get("text") for c in message.answer.await_args_list]


class StartAndLinkTests(HandlerTestCase):
    async def test_start_linked_shows_menu(self) -> None:
        message = make_message("/start")
        await handlers.cmd_start(message, self.state)
        self.assertIsNone(await self.state.get_state())
        text = self.answers(message)[0]
        self.assertIn("Ali Valiyev", text)
        markup = message.answer.await_args.kwargs["reply_markup"]
        self.assertIsInstance(markup, types.ReplyKeyboardMarkup)
        labels = [b.text for row in markup.keyboard for b in row]
        self.assertEqual(labels, [kb.BTN_TASKS, kb.BTN_PLATFORM, kb.BTN_PROFILE, kb.BTN_HELP, kb.BTN_LOGOUT])

    async def test_start_unlinked_asks_login(self) -> None:
        self.api.me.side_effect = NotFound(404, "topilmadi")
        message = make_message("/start")
        await handlers.cmd_start(message, self.state)
        self.assertEqual(await self.state.get_state(), handlers.Login.username.state)
        self.assertEqual(self.answers(message), [texts.ASK_LOGIN])

    async def test_full_link_flow_deletes_password(self) -> None:
        await self.state.set_state(handlers.Login.username)
        await handlers.login_username(make_message("inspektor1"), self.state)
        self.assertEqual(await self.state.get_state(), handlers.Login.password.state)

        password_msg = make_message("s3cret pass")
        await handlers.login_password(password_msg, self.state)

        password_msg.delete.assert_awaited_once()
        self.api.link.assert_awaited_once_with(TG_ID, "inspektor1", "s3cret pass")
        self.assertIsNone(await self.state.get_state())
        self.assertEqual(await self.state.get_data(), {})  # the login is not kept
        reply = self.answers(password_msg)[0]
        self.assertIn("Tizimga muvaffaqiyatli kirdingiz", reply)
        self.assertNotIn("s3cret", reply)
        self.assertIsInstance(password_msg.answer.await_args.kwargs["reply_markup"], types.ReplyKeyboardMarkup)

    async def test_bad_credentials_ask_login_again(self) -> None:
        self.api.link.side_effect = ApiError(400, "Login yoki parol noto‘g‘ri.")
        await self.state.set_state(handlers.Login.password)
        await self.state.update_data(username="inspektor1")
        message = make_message("wrong")
        await handlers.login_password(message, self.state)
        message.delete.assert_awaited_once()
        self.assertEqual(await self.state.get_state(), handlers.Login.username.state)
        self.assertIn("Login yoki parol noto‘g‘ri", self.answers(message)[0])

    async def test_backend_down_finishes_login(self) -> None:
        self.api.link.side_effect = Unavailable()
        await self.state.set_state(handlers.Login.password)
        await self.state.update_data(username="inspektor1")
        message = make_message("pw")
        await handlers.login_password(message, self.state)
        message.delete.assert_awaited_once()
        self.assertIsNone(await self.state.get_state())
        self.assertIn("/start", self.answers(message)[0])

    async def test_invalid_username_stays(self) -> None:
        await self.state.set_state(handlers.Login.username)
        message = make_message("two words")
        await handlers.login_username(message, self.state)
        self.assertEqual(await self.state.get_state(), handlers.Login.username.state)

    async def test_cancel_during_login(self) -> None:
        self.api.me.side_effect = NotFound(404, "x")
        await self.state.set_state(handlers.Login.password)
        message = make_message("/cancel")
        await handlers.cmd_cancel(message, self.state)
        self.assertIsNone(await self.state.get_state())
        self.assertIn("bekor qilindi", self.answers(message)[0])


class MenuTests(HandlerTestCase):
    async def test_tasks_empty(self) -> None:
        message = make_message(kb.BTN_TASKS)
        await handlers.menu_tasks(message)
        self.api.tasks.assert_awaited_once_with(TG_ID)
        self.assertEqual(self.answers(message), [texts.NO_TASKS])

    async def test_tasks_list_has_webapp_buttons(self) -> None:
        self.api.tasks.return_value = [
            {"id": 5, "code": "XN-0005", "name": "Navbahor 12-uy", "stage_number": 4, "stage_title": "Qurilish",
             "stage_status": "ACTIVE", "due_at": "2026-11-10T09:00:00+05:00", "is_overdue": True},
            {"id": 6, "code": "XN-0006", "name": "Bog‘ 3",
             "stage": {"number": 8, "title": "Veterinar ko‘rigi", "status": "SUBMITTED", "due_at": "2026-11-12"}},
        ]
        message = make_message(kb.BTN_TASKS)
        await handlers.menu_tasks(message)
        calls = message.answer.await_args_list
        self.assertEqual(len(calls), 3)
        self.assertIn("2 ta", calls[0].args[0])

        first = calls[1].args[0]
        self.assertIn("<b>XN-0005</b> — Navbahor 12-uy", first)
        self.assertIn("Bosqich: 4. Qurilish", first)
        self.assertIn("Muddat: 10.11.2026 09:00", first)
        self.assertIn("muddati o‘tgan", first)
        self.assertEqual(markup_urls(calls[1].kwargs["reply_markup"]), [f"{WEBAPP}/cases/5"])

        second = calls[2].args[0]
        self.assertIn("Bosqich: 8. Veterinar ko‘rigi", second)
        self.assertIn("tasdiqlash kutilmoqda", second)
        self.assertNotIn("muddati o‘tgan", second)
        self.assertEqual(markup_urls(calls[2].kwargs["reply_markup"]), [f"{WEBAPP}/cases/6"])

    async def test_tasks_are_capped(self) -> None:
        self.api.tasks.return_value = [{"id": i, "code": f"XN-{i:04d}"} for i in range(1, texts.TASKS_LIMIT + 4)]
        message = make_message(kb.BTN_TASKS)
        await handlers.menu_tasks(message)
        calls = message.answer.await_args_list
        self.assertEqual(len(calls), texts.TASKS_LIMIT + 2)  # header + 20 cases + "yana 3 ta"
        self.assertIn("yana 3 ta", calls[-1].args[0])
        self.assertEqual(markup_urls(calls[-1].kwargs["reply_markup"]), [f"{WEBAPP}/tasks"])

    async def test_tasks_unlinked(self) -> None:
        self.api.tasks.side_effect = NotFound(404, "x")
        message = make_message(kb.BTN_TASKS)
        await handlers.menu_tasks(message)
        self.assertEqual(self.answers(message), [texts.NOT_LINKED])

    async def test_platform_button(self) -> None:
        message = make_message(kb.BTN_PLATFORM)
        await handlers.menu_platform(message)
        self.assertEqual(markup_urls(message.answer.await_args.kwargs["reply_markup"]), [f"{WEBAPP}/"])

    async def test_profile(self) -> None:
        message = make_message(kb.BTN_PROFILE)
        await handlers.menu_profile(message)
        self.api.me.assert_awaited_once_with(TG_ID)
        text = self.answers(message)[0]
        for part in ("Ali Valiyev", "<code>inspektor1</code>", "Rol: Inspektor", "+998901234567"):
            self.assertIn(part, text)

    async def test_profile_unlinked(self) -> None:
        self.api.me.side_effect = NotFound(404, "x")
        message = make_message(kb.BTN_PROFILE)
        await handlers.menu_profile(message)
        self.assertEqual(self.answers(message), [texts.NOT_LINKED])

    async def test_help(self) -> None:
        message = make_message(kb.BTN_HELP)
        await handlers.cmd_help(message)
        self.assertEqual(self.answers(message), [texts.HELP])

    async def test_logout_confirm_and_yes(self) -> None:
        message = make_message(kb.BTN_LOGOUT)
        await handlers.menu_logout(message)
        markup = message.answer.await_args.kwargs["reply_markup"]
        self.assertEqual([b.callback_data for b in markup.inline_keyboard[0]], [kb.LOGOUT_YES, kb.LOGOUT_NO])
        self.api.unlink.assert_not_awaited()

        call = mock.MagicMock(data=kb.LOGOUT_YES, from_user=mock.MagicMock(id=TG_ID))
        call.answer = mock.AsyncMock()
        call.message = make_message()
        call.message.edit_text = mock.AsyncMock()
        await handlers.logout_answer(call)
        self.api.unlink.assert_awaited_once_with(TG_ID)
        self.assertEqual(self.answers(call.message), [texts.LOGOUT_DONE])

    async def test_logout_no(self) -> None:
        call = mock.MagicMock(data=kb.LOGOUT_NO, from_user=mock.MagicMock(id=TG_ID))
        call.answer = mock.AsyncMock()
        call.message = make_message()
        call.message.edit_text = mock.AsyncMock()
        await handlers.logout_answer(call)
        self.api.unlink.assert_not_awaited()
        call.message.edit_text.assert_awaited_once_with(texts.LOGOUT_CANCELLED)


class NoHttpsWebAppTests(HandlerTestCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(config, "WEBAPP_URL", "http://localhost:3000")
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_no_buttons_anywhere(self) -> None:
        self.assertIsNone(kb.webapp_button("x", "/cases/1"))

        self.api.tasks.return_value = [{"id": 5, "code": "XN-0005"}]
        message = make_message(kb.BTN_TASKS)
        await handlers.menu_tasks(message)
        self.assertIn(texts.WEBAPP_OFF, message.answer.await_args_list[0].args[0])
        self.assertIsNone(message.answer.await_args_list[1].kwargs["reply_markup"])

        message = make_message(kb.BTN_PLATFORM)
        await handlers.menu_platform(message)
        self.assertEqual(self.answers(message), [texts.WEBAPP_OFF])


class DispatcherRoutingTests(HandlerTestCase):
    """Goes through the real Dispatcher: filters, registration order, private-only."""

    def setUp(self) -> None:
        super().setUp()
        self.send = mock.AsyncMock()
        patcher = mock.patch.object(loader.bot, "send_message", self.send)
        patcher.start()
        self.addCleanup(patcher.stop)
        Bot.set_current(loader.bot)

    def update(self, text: str, chat_type: str = "private") -> types.Update:
        chat_id = TG_ID if chat_type == "private" else -100123
        message = {
            "message_id": 1, "date": 1700000000, "text": text,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": TG_ID, "is_bot": False, "first_name": "Ali"},
        }
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        return types.Update.to_object({"update_id": 1, "message": message})

    async def test_private_help_and_menu_button(self) -> None:
        await loader.dp.process_update(self.update("/help"))
        self.assertEqual(self.send.await_args.kwargs.get("text") or self.send.await_args.args[1], texts.HELP)
        await loader.dp.process_update(self.update(kb.BTN_PROFILE))
        self.api.me.assert_awaited_with(TG_ID)

    async def test_group_chat_is_ignored(self) -> None:
        await loader.dp.process_update(self.update("/start", chat_type="group"))
        await loader.dp.process_update(self.update(kb.BTN_TASKS, chat_type="supergroup"))
        self.send.assert_not_awaited()
        self.api.me.assert_not_awaited()
        self.api.tasks.assert_not_awaited()

    async def test_backend_error_is_reported_to_user(self) -> None:
        self.api.me.side_effect = Unavailable()
        await loader.dp.process_update(self.update(kb.BTN_PROFILE))
        sent = self.send.await_args.kwargs.get("text") or self.send.await_args.args[1]
        self.assertIn("Server bilan aloqa yo‘q", sent)


if __name__ == "__main__":
    unittest.main()
