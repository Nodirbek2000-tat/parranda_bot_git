import support  # noqa: F401  (must be first)

import unittest
from unittest import mock

from aiogram.utils.exceptions import BotBlocked, ChatNotFound, NetworkError, RetryAfter

import config
from api import ApiError, Unavailable
from notifier import Notifier, TelegramDown
from support import WEBAPP, markup_urls


def item(nid: int = 1, chat_id: int = 555, path: str = "/cases/3") -> dict:
    return {"id": nid, "chat_id": chat_id, "text": f"🐔 <b>NNP — YANGI VAZIFA</b> #{nid}", "button_path": path}


class NotifierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.MagicMock()
        self.bot.send_message = mock.AsyncMock()
        self.api = mock.MagicMock()
        self.api.pending_notifications = mock.AsyncMock(return_value=[item()])
        self.api.report_notification = mock.AsyncMock(return_value={})
        self.notifier = Notifier(self.bot, self.api)
        self.notifier._sleep = mock.AsyncMock(return_value=False)  # no real waiting

    async def test_success_sends_html_with_webapp_button_and_reports_ok(self) -> None:
        self.assertEqual(await self.notifier.process_once(), 1)
        self.api.pending_notifications.assert_awaited_once_with(limit=50)
        kwargs = self.bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 555)
        self.assertEqual(kwargs["parse_mode"], "HTML")
        self.assertIn("YANGI VAZIFA", kwargs["text"])
        self.assertEqual(markup_urls(kwargs["reply_markup"]), [f"{WEBAPP}/cases/3"])
        self.api.report_notification.assert_awaited_once_with(1, True, None)

    async def test_telegram_id_key_and_empty_path(self) -> None:
        self.api.pending_notifications.return_value = [{"id": 2, "telegram_id": 777, "text": "x", "button_path": ""}]
        await self.notifier.process_once()
        kwargs = self.bot.send_message.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 777)
        self.assertEqual(markup_urls(kwargs["reply_markup"]), [f"{WEBAPP}/"])

    async def test_bot_blocked_reports_failure(self) -> None:
        self.bot.send_message.side_effect = BotBlocked("Forbidden: bot was blocked by the user")
        await self.notifier.process_once()
        nid, ok, error = self.api.report_notification.await_args.args
        self.assertEqual((nid, ok), (1, False))
        self.assertIn("BotBlocked", error)

    async def test_chat_not_found_reports_failure_and_continues(self) -> None:
        self.api.pending_notifications.return_value = [item(1), item(2)]
        self.bot.send_message.side_effect = [ChatNotFound("Bad Request: chat not found"), None]
        self.assertEqual(await self.notifier.process_once(), 2)
        calls = [c.args for c in self.api.report_notification.await_args_list]
        self.assertEqual(calls[0][:2], (1, False))
        self.assertIn("ChatNotFound", calls[0][2])
        self.assertEqual(calls[1], (2, True, None))

    async def test_retry_after_waits_then_sends(self) -> None:
        self.bot.send_message.side_effect = [RetryAfter(3), None]
        await self.notifier.process_once()
        self.notifier._sleep.assert_awaited_once_with(3.0)
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.api.report_notification.assert_awaited_once_with(1, True, None)

    async def test_retry_after_gives_up_after_max_attempts(self) -> None:
        self.bot.send_message.side_effect = RetryAfter(1)
        await self.notifier.process_once()
        self.assertEqual(self.bot.send_message.await_count, 5)
        nid, ok, error = self.api.report_notification.await_args.args
        self.assertEqual((nid, ok), (1, False))
        self.assertIn("RetryAfter", error)

    async def test_network_error_keeps_pending_and_raises(self) -> None:
        self.bot.send_message.side_effect = NetworkError("Aiohttp client throws an error")
        with self.assertRaises(TelegramDown):
            await self.notifier.process_once()
        self.api.report_notification.assert_not_awaited()

    async def test_unreported_result_is_retried_without_resending(self) -> None:
        self.api.report_notification.side_effect = [Unavailable(), {}]
        # Pass 2 flushes the stored result first, so the backend no longer lists #1 as pending.
        self.api.pending_notifications.side_effect = [[item()], []]
        with self.assertRaises(ApiError):
            await self.notifier.process_once()
        self.assertEqual(self.bot.send_message.await_count, 1)

        await self.notifier.process_once()
        self.assertEqual(self.bot.send_message.await_count, 1)  # not sent twice
        self.assertEqual(self.api.report_notification.await_args_list[-1].args, (1, True, None))

    async def test_refused_report_is_dropped(self) -> None:
        self.api.report_notification.side_effect = ApiError(404, "topilmadi")
        await self.notifier.process_once()
        self.assertEqual(self.notifier._unreported, {})

    async def test_no_webapp_button_without_https(self) -> None:
        with mock.patch.object(config, "WEBAPP_URL", "http://localhost:3000"):
            await self.notifier.process_once()
        self.assertIsNone(self.bot.send_message.await_args.kwargs["reply_markup"])
        self.api.report_notification.assert_awaited_once_with(1, True, None)

    async def test_loop_backs_off_when_backend_is_down(self) -> None:
        self.api.pending_notifications.side_effect = Unavailable()
        delays = []

        async def fake_sleep(seconds: float) -> bool:
            delays.append(seconds)
            return len(delays) >= 5

        self.notifier._sleep = fake_sleep
        await self.notifier._run()
        self.assertEqual(delays, [10.0, 20.0, 40.0, 60.0, 60.0])

    async def test_loop_uses_interval_when_healthy(self) -> None:
        delays = []

        async def fake_sleep(seconds: float) -> bool:
            delays.append(seconds)
            return len(delays) >= 2

        self.notifier._sleep = fake_sleep
        await self.notifier._run()
        self.assertEqual(delays, [5.0, 5.0])


if __name__ == "__main__":
    unittest.main()
