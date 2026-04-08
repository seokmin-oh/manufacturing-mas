"""compare_results 헬퍼."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import compare_results as cr


def test_status_icon():
    assert cr._status_icon(0.96, 0.95, 0.90) == "+"
    assert cr._status_icon(0.92, 0.95, 0.90) == "!"
    assert cr._status_icon(0.85, 0.95, 0.90) == "x"


def test_status_icon_lower_better():
    assert cr._status_icon(0, 0, 3, higher_is_better=False) == "+"
    assert cr._status_icon(2, 0, 3, higher_is_better=False) == "!"
    assert cr._status_icon(5, 0, 3, higher_is_better=False) == "x"
