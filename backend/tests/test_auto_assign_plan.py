"""Unit tests for equal / round-robin auto-assign planning (no live API)."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from auto_assign import compute_round_robin_counts, plan_equal_assignments, build_by_agent_from_allocations


def test_round_robin_equal_split():
    counts = compute_round_robin_counts([350, 350, 350], 83)
    assert sum(counts) == 83
    assert sorted(counts) == [27, 28, 28]
    assert max(counts) - min(counts) <= 1


def test_round_robin_skips_zero_slots():
    counts = compute_round_robin_counts([0, 10, 10], 5)
    assert counts[0] == 0
    assert sum(counts) == 5
    assert counts[1] + counts[2] == 5
    assert abs(counts[1] - counts[2]) <= 1


def test_round_robin_respects_uneven_remaining():
    # Agent A only has 2 slots; B and C absorb the rest
    counts = compute_round_robin_counts([2, 100, 100], 10)
    assert counts[0] == 2
    assert sum(counts) == 10
    assert counts[1] == 4 and counts[2] == 4


def test_round_robin_empty_or_zero_cap():
    assert compute_round_robin_counts([5, 5], 0) == [0, 0]
    assert compute_round_robin_counts([], 10) == []


def test_plan_equal_assignments_includes_all_with_slots():
    agents = [
        {"id": "b", "name": "Bob", "daily_quota": 500},
        {"id": "a", "name": "Amy", "daily_quota": 500},
        {"id": "c", "name": "Cara", "daily_quota": 500},
    ]
    today_map = {"a": 150, "b": 150, "c": 150}
    rows = plan_equal_assignments(agents, today_map, 83)
    assert len(rows) == 3
    assert [r["agent_name"] for r in rows] == ["Amy", "Bob", "Cara"]
    assigned = [r["assigned"] for r in rows]
    assert sum(assigned) == 83
    assert max(assigned) - min(assigned) <= 1
    assert all(r["slots_available"] == 350 for r in rows)


def test_plan_equal_omits_full_agents():
    agents = [
        {"id": "a", "name": "Amy", "daily_quota": 10},
        {"id": "b", "name": "Bob", "daily_quota": 10},
    ]
    today_map = {"a": 10, "b": 3}
    rows = plan_equal_assignments(agents, today_map, 5)
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "b"
    assert rows[0]["assigned"] == 5


def test_build_by_agent_from_allocations():
    agents = [
        {"id": "a", "name": "Amy", "daily_quota": 50},
        {"id": "b", "name": "Bob", "daily_quota": 50},
    ]
    rows = build_by_agent_from_allocations(agents, {"a": 10, "b": 5}, {"a": 3, "b": 7})
    by_id = {r["agent_id"]: r for r in rows}
    assert by_id["a"]["assigned"] == 3 and by_id["a"]["slots_available"] == 40
    assert by_id["b"]["assigned"] == 7 and by_id["b"]["slots_available"] == 45
