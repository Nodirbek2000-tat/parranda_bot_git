"""Sozlamalar: majburiy qiymatlar bo'sh bo'lsa bot darhol tushunarli xato bilan to'xtaydi."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_MANAGED = {"BOT_TOKEN", "BOT_API_TOKEN", "WEBAPP_URL", "ADMINS", "API_URL"}


def load_config(**env: str) -> subprocess.CompletedProcess[str]:
    """``data.config`` ni alohida jarayonda berilgan muhit bilan yuklaydi."""
    clean = {k: v for k, v in os.environ.items() if k not in _MANAGED}
    clean.update(env, PYTHONIOENCODING="utf-8")
    code = "from data import config; print(config.WEBAPP_ENABLED, config.API_URL, config.ADMINS)"
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=clean, capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )


@unittest.skipIf((ROOT / ".env").exists(), ".env mavjud: u muhit qiymatlarini to'ldirib yuboradi")
class ConfigTests(unittest.TestCase):
    def test_missing_bot_api_token_fails_fast(self) -> None:
        result = load_config(BOT_TOKEN="123456:TESTTOKEN", BOT_API_TOKEN="  ")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BOT_API_TOKEN", result.stderr)

    def test_missing_bot_token_fails_fast(self) -> None:
        result = load_config(BOT_TOKEN="", BOT_API_TOKEN="x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BOT_TOKEN", result.stderr)

    def test_defaults_and_https_check(self) -> None:
        result = load_config(BOT_TOKEN="123456:TESTTOKEN", BOT_API_TOKEN="x",
                             WEBAPP_URL="http://localhost:3000/", ADMINS="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["False", "http://127.0.0.1:8000/api", "[]"])

        result = load_config(BOT_TOKEN="123456:TESTTOKEN", BOT_API_TOKEN="x",
                             WEBAPP_URL="https://app.example.test/", ADMINS="1, 2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split()[0], "True")
        self.assertIn("[1, 2]", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
