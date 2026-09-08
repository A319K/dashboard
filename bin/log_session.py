#!/usr/bin/env python3
"""Append one work-session record to .agent/log/sessions.jsonl.

Called by the /checkout skill. Validates shape so the learning loop in Phase 5
can trust every row it reads.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
LOG = AGENT / "log" / "sessions.jsonl"
TZ = ZoneInfo("America/New_York")

VALID_TOOLS = {"claude-code", "codex", "manual"}


def known_projects() -> set[str]:
    """Project ids from commitments.yaml, read without a yaml dependency."""
    ids: set[str] = set()
    path = AGENT / "commitments.yaml"
    if not path.exists():
        return ids
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            ids.add(stripped.split(":", 1)[1].strip())
    return ids


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", required=True)
    p.add_argument("--tool", default="claude-code", choices=sorted(VALID_TOOLS))
    p.add_argument("--planned-minutes", type=int, default=None)
    p.add_argument("--actual-minutes", type=int, default=None)
    p.add_argument("--started-at", default=None,
                   help="ISO datetime the work actually began. With --ended-at this "
                        "derives actual_minutes, so past work can be logged truthfully.")
    p.add_argument("--ended-at", default=None,
                   help="ISO datetime the work stopped. Defaults to now when "
                        "--started-at is given alone.")
    p.add_argument("--focus", type=int, default=None,
                   help="1-5. 1=scattered, 5=locked in. Powers the learning loop.")
    p.add_argument("--did", required=True, help="What concretely changed.")
    p.add_argument("--next", dest="next_", default="",
                   help="Concrete first action for next time.")
    p.add_argument("--blockers", default="", help="Comma-separated.")
    p.add_argument("--block-id", default=None, help="Calendar event id, if planned.")
    p.add_argument("--ts", default=None, help="ISO timestamp; defaults to now.")
    args = p.parse_args()

    if args.focus is not None and not 1 <= args.focus <= 5:
        p.error("--focus must be between 1 and 5")

    # A session is a span, not a duration hanging off the moment you checked out.
    # `ts` stays the END of the work: every reader downstream (the dashboard week
    # trace especially) reconstructs the start as ts - actual_minutes, so keeping
    # that invariant lets backdated sessions land on the right day for free.
    started = ended = None
    if args.started_at:
        try:
            started = datetime.fromisoformat(args.started_at)
            ended = (datetime.fromisoformat(args.ended_at) if args.ended_at
                     else datetime.now(TZ))
        except ValueError as exc:
            p.error(f"unreadable time: {exc}")
        if started.tzinfo is None:
            started = started.replace(tzinfo=TZ)
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=TZ)
        if ended <= started:
            print("error: the session has to end after it starts.", file=sys.stderr)
            return 1
        span = round((ended - started).total_seconds() / 60)
        if span > 12 * 60:
            print(f"error: {span} minutes is longer than a day of work — check the "
                  "date and times.", file=sys.stderr)
            return 1
        if args.actual_minutes is not None and args.actual_minutes != span:
            print(f"warning: --actual-minutes {args.actual_minutes} disagrees with "
                  f"{started:%H:%M}-{ended:%H:%M} ({span}m); using the times.",
                  file=sys.stderr)
        args.actual_minutes = span
    elif args.ended_at:
        p.error("--ended-at needs --started-at")

    projects = known_projects()
    if projects and args.project not in projects:
        print(f"warning: '{args.project}' is not in commitments.yaml "
              f"(known: {', '.join(sorted(projects))})", file=sys.stderr)

    if args.next_ and args.next_.strip().lower() in {
        "continue", "continue working on it", "keep going", "tbd", "n/a",
    }:
        print("error: --next must name a concrete first action; it becomes the "
              "opening line of a scheduled block.", file=sys.stderr)
        return 1

    record = {
        "ts": (args.ts or (ended.isoformat(timespec="seconds") if ended
                           else datetime.now(TZ).isoformat(timespec="seconds"))),
        "started_at": started.isoformat(timespec="seconds") if started else None,
        "ended_at": ended.isoformat(timespec="seconds") if ended else None,
        "project": args.project,
        "tool": args.tool,
        "planned_block_id": args.block_id,
        "planned_minutes": args.planned_minutes,
        "actual_minutes": args.actual_minutes,
        "focus": args.focus,
        "did": args.did.strip(),
        "next": args.next_.strip(),
        "blockers": [b.strip() for b in args.blockers.split(",") if b.strip()],
    }

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")

    mins = record["actual_minutes"]
    when = (f"{started:%a %m/%d %H:%M}-{ended:%H:%M}" if started
            else f"{mins if mins is not None else '?'} min")
    print(f"logged: {record['project']} · {when}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
