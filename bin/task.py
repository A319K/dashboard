#!/usr/bin/env python3
"""The task table — .agent/tasks.jsonl.

Unlike sessions.jsonl and life.jsonl this is NOT an append-only log. It is a
small mutable table, one JSON object per line, rewritten in place on every
change. JSONL rather than YAML so a checkbox in the dashboard can flip a task
without a hand-written file being re-emitted by a serializer.

A task is a thing you do; a block is when you do it; a session is you having
done it. /plan-week turns open tasks into blocks, and the block carries the
task's first action verbatim — a block that says only "work on X" is a defect.

    task.py add "Vivado lab 2 setup" --project cs440 --est 2h --due 2026-09-12 \
        --first-action "open lab2.pdf and do the constraint file only"
    task.py list --project cs440
    task.py done cs440-vivado-lab-2-setup
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentlib as A  # noqa: E402

TASKS = A.AGENT / "tasks.jsonl"
REMOVED = A.AGENT / "log" / "tasks-removed.jsonl"
TZ = ZoneInfo("America/New_York")
STATUSES = ["open", "scheduled", "done"]


# ---------------------------------------------------------------- storage

def load() -> list[dict]:
    return A.read_jsonl(TASKS)


def save(rows: list[dict]) -> None:
    TASKS.parent.mkdir(parents=True, exist_ok=True)
    TASKS.write_text("".join(json.dumps(r) + "\n" for r in rows))


def find(rows: list[dict], ident: str) -> dict | None:
    """Exact id, then unique prefix. Ambiguous prefixes resolve to nothing."""
    for r in rows:
        if r["id"] == ident:
            return r
    hits = [r for r in rows if r["id"].startswith(ident)]
    return hits[0] if len(hits) == 1 else None


def slug(title: str, project: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{project}-{title.lower()}").strip("-")[:48]
    base = base or f"{project}-task"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


# ---------------------------------------------------------------- parsing

def parse_minutes(raw: str | None) -> int | None:
    """2h, 90m, 1.5h, 45 → minutes."""
    if raw in (None, ""):
        return None
    s = str(raw).strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)?", s)
    if not m:
        raise ValueError(f"can't read {raw!r} as a duration — try 90m, 2h, or 1.5h")
    value = float(m.group(1))
    minutes = value * 60 if (m.group(2) or "m").startswith("h") else value
    if minutes <= 0:
        raise ValueError("a duration has to be positive")
    return int(round(minutes))


def parse_due(raw: str | None) -> str | None:
    """A bare date means end of that day, which is what a due date means."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T23:59:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.isoformat(timespec="seconds")


def known_projects() -> set[str]:
    return set(A.project_meta())


# ---------------------------------------------------------------- commands

def cmd_add(args) -> int:
    projects = known_projects()
    if args.project not in projects:
        print(f"error: {args.project!r} isn't a commitment. Known: "
              + ", ".join(sorted(projects)))
        return 1
    try:
        est = parse_minutes(args.est)
        due = parse_due(args.due)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    rows = load()
    now = datetime.now(TZ).isoformat(timespec="seconds")
    task = {
        "id": slug(args.title, args.project, {r["id"] for r in rows}),
        "project": args.project,
        "title": args.title.strip(),
        "first_action": (args.first_action or "").strip() or None,
        "est_minutes": est,
        "due": due,
        "deadline": args.deadline,
        "status": "open",
        "created": now,
        "done_ts": None,
        "blocks": [],
    }
    rows.append(task)
    save(rows)
    print(json.dumps(task) if args.json else f"added {task['id']}")
    return 0


def cmd_list(args) -> int:
    rows = load()
    if args.project:
        rows = [r for r in rows if r["project"] == args.project]
    if not args.all:
        rows = [r for r in rows if r["status"] != "done"]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no tasks" + (" for " + args.project if args.project else ""))
        return 0
    for r in sorted(rows, key=lambda r: (r["project"], r.get("due") or "9", r["id"])):
        mark = {"done": "[x]", "scheduled": "[»]"}.get(r["status"], "[ ]")
        bits = []
        if r.get("est_minutes"):
            bits.append(f"{r['est_minutes']}m")
        if r.get("due"):
            bits.append("due " + datetime.fromisoformat(r["due"]).strftime("%a %m/%d"))
        tail = f"  ({', '.join(bits)})" if bits else ""
        print(f"{mark} {r['id']:<40} {r['project']:<16} {r['title']}{tail}")
        if r.get("first_action"):
            print(f"      ↳ {r['first_action']}")
    return 0


def cmd_status(args, status: str) -> int:
    rows = load()
    task = find(rows, args.id)
    if not task:
        print(f"no task matching {args.id!r}")
        return 1
    task["status"] = status
    task["done_ts"] = datetime.now(TZ).isoformat(timespec="seconds") if status == "done" else None
    save(rows)
    print(f"{task['id']} → {status}")
    return 0


def cmd_set(args) -> int:
    rows = load()
    task = find(rows, args.id)
    if not task:
        print(f"no task matching {args.id!r}")
        return 1
    try:
        if args.est is not None:
            task["est_minutes"] = parse_minutes(args.est)
        if args.due is not None:
            task["due"] = parse_due(args.due)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    if args.title:
        task["title"] = args.title.strip()
    if args.first_action is not None:
        task["first_action"] = args.first_action.strip() or None
    if args.project:
        if args.project not in known_projects():
            print(f"error: {args.project!r} isn't a commitment")
            return 1
        task["project"] = args.project
    if args.status:
        task["status"] = args.status
        task["done_ts"] = (datetime.now(TZ).isoformat(timespec="seconds")
                           if args.status == "done" else None)
    if args.add_block:
        task.setdefault("blocks", []).append(args.add_block)
        if task["status"] == "open":
            task["status"] = "scheduled"
    save(rows)
    print(json.dumps(task) if args.json else f"updated {task['id']}")
    return 0


def cmd_rm(args) -> int:
    """Delete is recoverable on purpose: this table is the only record of the work."""
    rows = load()
    task = find(rows, args.id)
    if not task:
        print(f"no task matching {args.id!r}")
        return 1
    REMOVED.parent.mkdir(parents=True, exist_ok=True)
    with REMOVED.open("a") as fh:
        fh.write(json.dumps({**task,
                             "removed_at": datetime.now(TZ).isoformat(timespec="seconds")}) + "\n")
    save([r for r in rows if r["id"] != task["id"]])
    print(f"removed {task['id']} — restore with: task.py restore {task['id']}")
    return 0


def cmd_restore(args) -> int:
    gone = A.read_jsonl(REMOVED)
    hit = next((r for r in reversed(gone) if r["id"] == args.id
                or r["id"].startswith(args.id)), None)
    if not hit:
        print(f"nothing removed matching {args.id!r}")
        return 1
    rows = load()
    if any(r["id"] == hit["id"] for r in rows):
        print(f"{hit['id']} is already in the table")
        return 1
    hit.pop("removed_at", None)
    rows.append(hit)
    save(rows)
    print(f"restored {hit['id']}")
    return 0


def cmd_prune(args) -> int:
    """Drop tasks finished more than --days ago. The log keeps the history."""
    cutoff = datetime.now(TZ) - timedelta(days=args.days)
    rows = load()
    keep = [r for r in rows if not (
        r["status"] == "done" and r.get("done_ts")
        and datetime.fromisoformat(r["done_ts"]) < cutoff)]
    save(keep)
    print(f"pruned {len(rows) - len(keep)} finished task(s)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", help="Machine-readable output.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Add a task.")
    a.add_argument("title")
    a.add_argument("--project", required=True, help="Commitment id.")
    a.add_argument("--est", help="Estimate: 90m, 2h, 1.5h.")
    a.add_argument("--due", help="YYYY-MM-DD or an ISO datetime.")
    a.add_argument("--first-action", help="The concrete opener a block will carry.")
    a.add_argument("--deadline", help="Deadline id from deadlines.yaml, if it serves one.")

    l = sub.add_parser("list", help="List tasks. Open ones by default.")
    l.add_argument("--project")
    l.add_argument("--all", action="store_true", help="Include finished tasks.")

    for name, help_text in (("done", "Tick a task off."), ("reopen", "Un-tick a task.")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("id", help="Task id or a unique prefix.")

    s = sub.add_parser("set", help="Change a field on a task.")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--project")
    s.add_argument("--est")
    s.add_argument("--due")
    s.add_argument("--first-action")
    s.add_argument("--status", choices=STATUSES)
    s.add_argument("--add-block", help="Attach a queued block id.")

    s = sub.add_parser("rm", help="Delete a task. Recoverable via `restore`.")
    s.add_argument("id")

    s = sub.add_parser("restore", help="Undo a delete.")
    s.add_argument("id")

    s = sub.add_parser("prune", help="Drop long-finished tasks.")
    s.add_argument("--days", type=int, default=30)

    args = p.parse_args()
    return {
        "add": cmd_add,
        "list": cmd_list,
        "done": lambda a: cmd_status(a, "done"),
        "reopen": lambda a: cmd_status(a, "open"),
        "set": cmd_set,
        "rm": cmd_rm,
        "restore": cmd_restore,
        "prune": cmd_prune,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
