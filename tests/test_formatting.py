"""``utils/formatting.py`` uchun testlar (sonlar, foizlar, sanalar, ``—``).

Ishga tushirish (parranda_bot papkasidan):
    venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.formatting import (  # noqa: E402
    EMPTY,
    TASHKENT_TZ,
    fmt_date,
    fmt_fixed,
    fmt_number,
    fmt_percent,
    fmt_quantity,
    parse_date,
)


class FormattingTests(unittest.TestCase):
    def test_numbers_use_space_thousands_separator(self) -> None:
        cases = {
            0: "0", 7: "7", 999: "999", 1000: "1 000", 2800: "2 800", 1234567: "1 234 567",
            310.5: "310.5", 380.0: "380", 55.25: "55.25", Decimal("1500.500"): "1 500.5",
            "6900": "6 900", "1250.75": "1 250.75", -1500: "-1 500", 0.1: "0.1",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(fmt_number(value), expected)

    def test_missing_or_invalid_numbers_are_dash(self) -> None:
        for value in (None, "", "abc", True, False, float("nan"), float("inf"), [], {}):
            with self.subTest(value=value):
                self.assertEqual(fmt_number(value), EMPTY)
                self.assertEqual(fmt_percent(value), EMPTY)

    def test_percent_has_exactly_one_decimal_half_up(self) -> None:
        cases = {
            81.2: "81.2%", 80: "80.0%", 100.0: "100.0%", 0: "0.0%", 72.727: "72.7%",
            Decimal("72.75"): "72.8%", Decimal("66.65"): "66.7%", "0.05": "0.1%", 0.04: "0.0%",
            Decimal("-0.04"): "0.0%", -2.35: "-2.4%", 1234.5: "1 234.5%",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(fmt_percent(value), expected)

    def test_fixed_decimals_half_up(self) -> None:
        """FCR: doim 2 xona kasr (``ROUND_HALF_UP``), ``None`` -> ``—``."""
        cases = {1.8: "1.80", 2: "2.00", 2.005: "2.01", Decimal("1.814"): "1.81", 1234.5: "1 234.50",
                 Decimal("-0.001"): "0.00", "0.125": "0.13"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(fmt_fixed(value, 2), expected)
        self.assertEqual(fmt_fixed(None, 2), EMPTY)
        self.assertEqual(fmt_fixed(True, 2), EMPTY)
        self.assertEqual(fmt_fixed(7.6, 0), "8")

    def test_quantity_drops_unit_for_missing_value(self) -> None:
        self.assertEqual(fmt_quantity(2800, "dona"), "2 800 dona")
        self.assertEqual(fmt_quantity(55.5, "kg"), "55.5 kg")
        self.assertEqual(fmt_quantity(0, "ta"), "0 ta")
        self.assertEqual(fmt_quantity(None, "kg"), EMPTY)

    def test_dates(self) -> None:
        self.assertEqual(fmt_date("2026-11-04"), "04.11.2026")
        self.assertEqual(fmt_date("2026-11-04T18:20:05+05:00"), "04.11.2026")
        self.assertEqual(fmt_date(date(2026, 1, 9)), "09.01.2026")
        self.assertEqual(fmt_date(datetime(2026, 10, 29, 23, 59, tzinfo=TASHKENT_TZ)), "29.10.2026")
        for value in (None, "", "04.11.2026", "2026-13-01", 20261104):
            with self.subTest(value=value):
                self.assertEqual(fmt_date(value), EMPTY)
                self.assertIsNone(parse_date(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
