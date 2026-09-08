#!/usr/bin/env python3
"""Aggregate sessions.jsonl and life.jsonl into the numbers /review reasons over.

Pure aggregation — it computes, it does not interpret. The /review skill reads
this output and writes the conclusions into PROFILE.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/New_York")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  ! skipping malformed line in {path.name}")
    return out


def since(rows: list[dict], days: int) -> list[dict]:
    cutoff = datetime.now(TZ) - timedelta(days=days)
    kept = []
    for r in rows:
        try:
            if datetime.fromisoformat(r["ts"]) >= cutoff:
                kept.append(r)
        except (KeyError, ValueError):
            continue
    return kept


def bar(n: int, width: int = 20) -> str:
    return "█" * min(n, width)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=7)
    args = p.parse_args()

    sessions = since(read_jsonl(AGENT / "log" / "sessions.jsonl"), args.days)
    life = since(read_jsonl(AGENT / "log" / "life.jsonl"), args.days)

    print(f"\n=== Last {args.days} days ===")
    print(f"sessions: {len(sessions)}   life events: {len(life)}")

    if not sessions:
        print("\nNo session data yet. Nothing to learn from — this is expected")
        print("until /checkout has been running for a couple of weeks.")
    else:
        # --- time per project vs budget ---
        by_project: dict[str, list[dict]] = defaultdict(list)
        for s in sessions:
            by_project[s["project"]].append(s)

        print("\n--- Time by project ---")
        for proj, rows in sorted(by_project.items(),
                                 key=lambda kv: -sum(r.get("actual_minutes") or 0 for r in kv[1])):
            mins = sum(r.get("actual_minutes") or 0 for r in rows)
            spans = [r["actual_minutes"] for r in rows if r.get("actual_minutes")]
            avg = f", {statistics.median(spans):.0f} min median" if spans else ""
            print(f"  {proj:<18} {mins/60:>5.1f}h  ({len(rows)} sessions{avg})")

        # --- when the work actually happens ---
        # Sessions carry a real span now, so this counts every hour a session was
        # running rather than the single hour it was logged in. That is the signal
        # the planner wants: which hours you genuinely work, not when you check out.
        print("\n--- Hours worked by day × hour ---")
        cell: dict[tuple[int, int], int] = defaultdict(int)
        for s in sessions:
            start = s.get("started_at")
            mins = s.get("actual_minutes")
            if not start or not mins:
                continue
            t = datetime.fromisoformat(start)
            for step in range(0, mins, 60):
                at = t + timedelta(minutes=step)
                cell[(at.weekday(), at.hour)] += min(60, mins - step)
        if not cell:
            print("  (no sessions with recorded times yet)")
        else:
            peak = max(cell.values())
            for (dow, hour), mins in sorted(cell.items()):
                print(f"  {DAYS[dow]} {hour:02d}:00  {bar(round(mins / peak * 6))} "
                      f"({mins} min)")
            best = max(cell.items(), key=lambda kv: kv[1])
            print(f"  → densest hour: {DAYS[best[0][0]]} {best[0][1]:02d}:00")

        # --- planned vs actual drift ---
        drift = [(s["project"], s["actual_minutes"] - s["planned_minutes"])
                 for s in sessions
                 if s.get("planned_minutes") and s.get("actual_minutes")]
        if drift:
            print("\n--- Planned vs actual (minutes over/under) ---")
            per: dict[str, list[int]] = defaultdict(list)
            for proj, d in drift:
                per[proj].append(d)
            for proj, ds in sorted(per.items()):
                m = statistics.median(ds)
                print(f"  {proj:<18} {m:+.0f} min median  (n={len(ds)})")

        # --- unplanned work ---
        unplanned = [s for s in sessions if not s.get("planned_block_id")]
        if unplanned:
            print(f"\n--- Unplanned sessions: {len(unplanned)}/{len(sessions)} ---")
            print("  (work happening outside the plan — candidate slots to plan into)")
            for s in unplanned[-8:]:
                # started_at when we have it: the hour you began is the schedulable
                # one; ts is only when you happened to write the session down.
                t = datetime.fromisoformat(s.get("started_at") or s["ts"])
                mins = s.get("actual_minutes")
                print(f"    {DAYS[t.weekday()]} {t:%H:%M}  {s['project']}"
                      f"{f' · {mins} min' if mins else ''}")

        # --- blockers ---
        blocked = [(s["project"], b) for s in sessions for b in s.get("blockers", [])]
        if blocked:
            print("\n--- Open blockers reported ---")
            for proj, b in blocked:
                print(f"  {proj}: {b}")

    # --- habits ---
    print("\n--- Habits ---")
    counts: dict[str, int] = defaultdict(int)
    for e in life:
        counts[e["kind"]] += 1
    for kind, target in (("gym", 4), ("cardio", 2)):
        n = counts.get(kind, 0)
        status = "on track" if n >= target else f"{target - n} short"
        print(f"  {kind:<8} {n}/{target}  {bar(n * 3)}  {status}")
    for kind in ("meal", "social"):
        if counts.get(kind):
            print(f"  {kind:<8} {counts[kind]}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
