"""Unit tests for caller daily-sales disposition column mapping (no live API / DB writes)."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from caller_sales import sales_disp_counts


def test_sales_disp_counts_aliases():
    counts = sales_disp_counts({
        "Interested / Follow up": 5,
        "Interested": 2,
        "Registered": 3,
        "Deposite": 1,
        "Deposit": 1,
        "Call Back / Busy": 4,
    })
    assert counts["interested"] == 7
    assert counts["registered"] == 3
    assert counts["deposite"] == 2


def test_sales_disp_counts_case_insensitive():
    counts = sales_disp_counts({"interested": 1, "REGISTERED": 2, "deposite": 3})
    assert counts == {"interested": 1, "registered": 2, "deposite": 3}


def test_sales_disp_counts_empty():
    assert sales_disp_counts({}) == {"interested": 0, "registered": 0, "deposite": 0}


def test_conversion_ratio_formula():
    deposite = 1
    calls = 3267
    ratio = round((deposite / calls * 100) if calls else 0, 1)
    assert ratio == 0.0
    assert round((2 / 10 * 100) if 10 else 0, 1) == 20.0
    assert round((0 / 0 * 100) if 0 else 0, 1) == 0
