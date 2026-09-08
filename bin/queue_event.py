#!/usr/bin/env python3
"""Queue an intended calendar event while the Google Calendar MCP is deferred.

Every write the system wants to make lands here instead. When the MCP is
reconnected, `--list` the pending rows, create the ones still relevant, and mark
them flushed. See .agent/CALENDAR.md.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
QUEUE = AGENT / "pending_calendar.jsonl"
TZ = ZoneInfo("America/New_York")

# "block" is intended work (future); "done" is work that already happened and is
# being written to the calendar as a record. They flush to the same calendar but
# read differently, so the title carries the distinction — see cmd_add.
KINDS = ["block", "done", "deadline", "meal", "social", "other"]


def load() -> list[dict]:
    if not QUEUE.exists():
        return []
    return [json.loads(line) for line in QUEUE.read_text().splitlines() if line.strip()]


def cmd_list(pending_only: bool) -> int:
    rows = load()
    if pending_only:
        rows = [r for r in rows if r.get("status") == "pending"]
    if not rows:
        print("queue is empty")
        return 0
    for r in rows:
        start = datetime.fromisoformat(r["start"])
        flag = "" if r["status"] == "pending" else f"  [{r['status']}]"
        print(f"{r['id'][:8]}  {start:%a %m/%d %H:%M}  {r['minutes']:>3}m  "
              f"{r['kind']:<8} {r['summary']}{flag}")
        if r.get("first_action"):
            print(f"          ↳ {r['first_action']}")
    return 0


def cmd_flush(event_id: str, gcal_id: str) -> int:
    rows = load()
    hit = False
    for r in rows:
        if r["id"].startswith(event_id):
            r["status"] = "flushed"
            r["gcal_event_id"] = gcal_id
            hit = True
    if not hit:
        print(f"no queued event matching {event_id!r}")
        return 1
    QUEUE.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"marked {event_id} flushed → {gcal_id}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=TZ)

    # A completed session is evidence, not a plan: it has no cold start to carry,
    # so --first-action is not required for it.
    if args.kind == "block" and not args.first_action:
        print("error: a work block requires --first-action. A block that says "
              "only 'work on X' is a defect — the cold start is the bottleneck.")
        return 1

    # --end wins over --minutes: a logged session knows exactly when it stopped,
    # where a planned block only knows how long it is meant to run.
    if args.end:
        end = datetime.fromisoformat(args.end)
        if end.tzinfo is None:
            end = end.replace(tzinfo=TZ)
        if end <= start:
            print("error: --end must be after --start")
            return 1
        minutes = round((end - start).total_seconds() / 60)
    else:
        minutes = args.minutes
        end = start + timedelta(minutes=minutes)

    record = {
        "id": uuid.uuid4().hex,
        "queued_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "status": "pending",
        "kind": args.kind,
        "summary": args.summary,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "minutes": minutes,
        "commitment": args.commitment,
        "first_action": args.first_action,
        "notes": args.notes,
        "gcal_event_id": None,
    }

    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"queued: {start:%a %m/%d %H:%M}-{end:%H:%M} · {minutes}m · {args.summary}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list", action="store_true", help="Show pending queued events.")
    p.add_argument("--all", action="store_true", help="With --list, include flushed.")
    p.add_argument("--flush", metavar="ID", help="Mark a queued event flushed.")
    p.add_argument("--gcal-id", default="", help="Resulting calendar event id, with --flush.")

    p.add_argument("--summary")
    p.add_argument("--start", help="ISO datetime.")
    p.add_argument("--minutes", type=int, default=50)
    p.add_argument("--end", help="ISO datetime. Overrides --minutes; use for logged work.")
    p.add_argument("--kind", choices=KINDS, default="block")
    p.add_argument("--commitment", default=None, help="Project id from commitments.yaml.")
    p.add_argument("--first-action", default=None,
                   help="Required for blocks. The concrete opener.")
    p.add_argument("--notes", default="")
    args = p.parse_args()

    if args.list:
        return cmd_list(pending_only=not args.all)
    if args.flush:
        return cmd_flush(args.flush, args.gcal_id)
    if not (args.summary and args.start):
        p.error("--summary and --start are required to queue an event")
    return cmd_add(args)


if __name__ == "__main__":
    raise SystemExit(main())
