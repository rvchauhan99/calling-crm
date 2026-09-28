#!/usr/bin/env python3
"""Relink lead/call disposition_id from stored disposition_name.

Default is dry-run (read-only). Pass --apply to write (same path as API boot
ensure_disposition_id_relink).

  cd backend && source .venv/bin/activate
  python scripts/relink_lead_disposition_ids.py
  python scripts/relink_lead_disposition_ids.py --apply

Do not --apply against Atlas/production without explicit approval.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/...` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set lead/call disposition_id from the current master matching stored name",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates via ensure_disposition_id_relink (default is dry-run)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Sample mismatch rows to print in dry-run",
    )
    args = parser.parse_args()

    from disposition_id_relink import (
        collect_disposition_id_mismatches,
        ensure_disposition_id_relink,
    )

    report = await collect_disposition_id_mismatches(limit_samples=args.samples)
    print(
        f"Relink candidates: {report['updated']} "
        f"(leads={report['leads']} calls={report['calls']})"
    )
    for name, n in sorted(report["by_disposition"].items(), key=lambda x: -x[1]):
        print(f"  {name}: {n}")
    if report["unmatched"]:
        print(f"Unmatched names (left unchanged): {report['unmatched_count']}")
        for name, n in sorted(report["unmatched"].items(), key=lambda x: -x[1]):
            print(f"  {name!r}: {n}")
    if report["samples"]:
        print("Samples:")
        for s in report["samples"]:
            print(
                f"  {s['lead_id']} {s.get('name')!r} "
                f"{s['stored_name']!r}: {s['old_id']} -> {s['new_id']}"
            )

    if not args.apply:
        print("Dry-run only. Re-run with --apply to update leads and calls.")
        return 0

    result = await ensure_disposition_id_relink()
    print(f"Applied: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
