"""Shared equal / round-robin auto-assign planning for leads and sheet sync."""
from typing import Dict, List, Optional


def compute_round_robin_counts(slots_by_agent: List[int], cap: int) -> List[int]:
    """Distribute up to `cap` leads across agents with remaining slots via round-robin.

    Returns planned counts (same length as slots_by_agent). Counts among agents that
    still had capacity at the end differ by at most 1.
    """
    n = len(slots_by_agent)
    counts = [0] * n
    if n == 0 or cap <= 0:
        return counts
    remaining = list(slots_by_agent)
    assigned = 0
    while assigned < cap:
        progressed = False
        for i in range(n):
            if assigned >= cap:
                break
            if remaining[i] <= 0:
                continue
            counts[i] += 1
            remaining[i] -= 1
            assigned += 1
            progressed = True
        if not progressed:
            break
    return counts


def sort_agents(agents: List[dict]) -> List[dict]:
    return sorted(agents, key=lambda a: ((a.get("name") or "").lower(), a.get("id") or ""))


def plan_equal_assignments(
    agents: List[dict],
    assigned_today_map: Dict[str, int],
    cap: int,
) -> List[dict]:
    """Return by_agent rows with equal round-robin `assigned` counts.

    Includes every agent with slots_available > 0 (even if planned assigned is 0),
    so the UI can reallocate. Agents with zero slots and zero assigned are omitted.
    """
    sorted_agents = sort_agents(agents)
    eligible: List[dict] = []
    slots_list: List[int] = []
    for agent in sorted_agents:
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = assigned_today_map.get(agent["id"], 0)
        slots = max(0, quota - assigned_today)
        if slots > 0:
            eligible.append(agent)
            slots_list.append(slots)

    counts = compute_round_robin_counts(slots_list, cap)
    planned = {eligible[i]["id"]: counts[i] for i in range(len(eligible))}

    rows = []
    for agent in sorted_agents:
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = assigned_today_map.get(agent["id"], 0)
        slots = max(0, quota - assigned_today)
        assigned = int(planned.get(agent["id"], 0))
        if slots <= 0 and assigned <= 0:
            continue
        rows.append({
            "agent_id": agent["id"],
            "agent_name": agent["name"],
            "assigned": assigned,
            "quota": quota,
            "assigned_today_before": assigned_today,
            "slots_available": slots,
        })
    return rows


def build_by_agent_from_allocations(
    agents: List[dict],
    assigned_today_map: Dict[str, int],
    allocation_counts: Dict[str, int],
) -> List[dict]:
    """Build by_agent rows for explicit per-agent allocation counts."""
    sorted_agents = sort_agents(agents)
    by_id = {a["id"]: a for a in sorted_agents}
    rows = []
    # Preserve deterministic agent order; include any allocated agent even if slots 0 (validation should prevent)
    seen = set()
    for agent in sorted_agents:
        aid = agent["id"]
        count = int(allocation_counts.get(aid, 0))
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = assigned_today_map.get(aid, 0)
        slots = max(0, quota - assigned_today)
        if slots <= 0 and count <= 0:
            continue
        rows.append({
            "agent_id": aid,
            "agent_name": agent["name"],
            "assigned": count,
            "quota": quota,
            "assigned_today_before": assigned_today,
            "slots_available": slots,
        })
        seen.add(aid)
    for aid, count in allocation_counts.items():
        if aid in seen or count <= 0:
            continue
        agent = by_id.get(aid)
        if not agent:
            continue
        quota = agent.get("daily_quota", 0) or 0
        assigned_today = assigned_today_map.get(aid, 0)
        slots = max(0, quota - assigned_today)
        rows.append({
            "agent_id": aid,
            "agent_name": agent["name"],
            "assigned": int(count),
            "quota": quota,
            "assigned_today_before": assigned_today,
            "slots_available": slots,
        })
    return rows
