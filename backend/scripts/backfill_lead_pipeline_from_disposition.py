#!/usr/bin/env python3
"""Backfill lead.pipeline_stage from disposition default_pipeline_stage.

Default is dry-run (read-only). Pass --apply to write.

  cd backend && source .venv/bin/activate
  python scripts/backfill_lead_pipeline_from_disposition.py
  python scripts/backfill_lead_pipeline_from_disposition.py --apply

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
        description="Align lead pipeline_stage with disposition master mapping",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates (default is dry-run)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Sample mismatch rows to print in dry-run",
    )
    args = parser.parse_args()

    from disposition_pipeline import (
        apply_lead_pipeline_from_disposition,
        collect_lead_pipeline_mismatches,
        ensure_disposition_pipeline_links,
    )

    ensure = await ensure_disposition_pipeline_links()
    print(f"Disposition links ensured: {ensure}")

    report = await collect_lead_pipeline_mismatches(limit_samples=args.samples)
    print(f"Mismatched leads: {report['total']}")
    for key, n in sorted(report["buckets"].items(), key=lambda x: -x[1]):
        print(f"  {key}: {n}")
    if report["samples"]:
        print("Samples:")
        for s in report["samples"]:
            print(
                f"  {s['id']} {s.get('name')!r} "
                f"{s['disposition']}: {s['from']} -> {s['to']}"
            )

    if not args.apply:
        print("Dry-run only. Re-run with --apply to update leads.")
        return 0

    result = await apply_lead_pipeline_from_disposition()
    print(f"Applied: updated={result['updated']}")
    for name, n in sorted(result.get("by_disposition", {}).items(), key=lambda x: -x[1]):
        print(f"  {name}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
