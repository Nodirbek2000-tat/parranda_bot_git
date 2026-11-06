"""Shared test setup: fake env (never the real .env tokens) and the project root on sys.path.

Import this module first in every test file.
"""
import logging
import os
import sys
from pathlib import Path
from unittest import mock

# Set unconditionally: python-dotenv never overrides existing variables, so the real .env is ignored.
os.environ.update({
    "BOT_TOKEN": "123456789:TEST_fake_token_not_real",
    "BOT_API_TOKEN": "test-bot-api-token",
    "API_URL": "http://backend.invalid/api",
    "WEBAPP_URL": "https://app.example.test",
    "ADMINS": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)

from aiogram import types  # noqa: E402

WEBAPP = "https://app.example.test"
TG_ID = 555


def make_message(text: str = "", user_id: int = TG_ID) -> mock.MagicMock:
    """A Message stand-in: answer/delete are AsyncMocks, nothing reaches Telegram."""
    message = mock.MagicMock(spec=types.Message)
    message.text = text
    message.from_user = mock.MagicMock(id=user_id)
    message.chat = mock.MagicMock(id=user_id, type="private")
    message.is_command.return_value = text.startswith("/")
    message.answer = mock.AsyncMock()
    message.delete = mock.AsyncMock()
    return message


def markup_urls(markup) -> list:
    """Web App URLs of an inline keyboard (empty list for None)."""
    if markup is None:
        return []
    return [b.web_app.url for row in markup.inline_keyboard for b in row if b.web_app]


def user(**extra) -> dict:
    data = {"id": 7, "username": "inspektor1", "full_name": "Ali Valiyev", "role": "INSPECTOR",
            "role_display": "Inspektor", "phone": "+998901234567", "must_change_password": False}
    data.update(extra)
    return data
