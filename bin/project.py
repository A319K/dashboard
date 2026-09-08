#!/usr/bin/env python3
"""Add, archive, and restore commitments in .agent/commitments.yaml.

commitments.yaml is hand-written and heavily commented — the section headers and
the trailing notes on individual fields carry real information. So this edits the
file as text rather than parsing and re-emitting it: a new commitment is appended
to the end of the list, and archiving inserts one line into an existing entry.
Nothing else in the file is touched, and every comment survives.

Usage:
  project.py list [--all]
  project.py add ee301 --name "EE 301" --lane coursework --dir fall_2026/ee301
  project.py archive trading_bot
  project.py restore trading_bot
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentlib as A  # noqa: E402

YAML = A.AGENT / "commitments.yaml"
PROJECTS = A.AGENT / "projects"

# The lanes the dashboard has a colour for. A lane outside this set would render
# grey, so it is rejected rather than silently losing its pigment.
LANES = ["coursework", "research", "business", "side", "software", "work"]
PRIORITIES = ["high", "medium", "low"]
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def num(x: float) -> str:
    """Write 2, not 2.0 — the file's other budgets are plain integers."""
    return str(int(x)) if float(x).is_integer() else str(x)


# ------------------------------------------------------- locating things

def lines() -> list[str]:
    return YAML.read_text().split("\n")


def _skip_back(rows: list[str], j: int, floor: int) -> int:
    """Walk an index back over blank and comment lines."""
    while j > floor and (not rows[j - 1].strip() or rows[j - 1].lstrip().startswith("#")):
        j -= 1
    return j


def commitments_end(rows: list[str]) -> int:
    """Index just past the last commitment entry.

    Not end-of-file: `habits:` follows the list, and the comment introducing it
    belongs to habits, so the insert point backs up over trailing comments.
    """
    try:
        start = next(i for i, l in enumerate(rows) if l.rstrip() == "commitments:")
    except StopIteration:
        raise SystemExit("commitments.yaml has no `commitments:` list")
    j = start + 1
    while j < len(rows) and not re.match(r"^[A-Za-z_][\w-]*:", rows[j]):
        j += 1
    return _skip_back(rows, j, start + 1)


def find_entry(rows: list[str], pid: str) -> tuple[int, int] | None:
    """(start, end) line indices of one `- id: <pid>` entry, end exclusive."""
    pat = re.compile(rf"^  - id:\s*{re.escape(pid)}\s*(#.*)?$")
    start = next((i for i, l in enumerate(rows) if pat.match(l)), None)
    if start is None:
        return None
    j = start + 1
    while j < len(rows):
        row = rows[j]
        if not row.strip() or row.lstrip().startswith("#"):
            j += 1
            continue
        if not row.startswith("    "):        # dedent: next entry or next key
            break
        j += 1
    return start, _skip_back(rows, j, start + 1)


# ------------------------------------------------------------- commands

def cmd_list(args) -> int:
    for c in A.commitments().get("commitments", []):
        if c.get("archived") and not args.all:
            continue
        flag = "  (archived)" if c.get("archived") else ""
        print(f"{c['id']:<18} {c.get('lane',''):<11} "
              f"{c.get('hours_min',0)}-{c.get('hours_max',0)}h/wk{flag}")
    return 0


def cmd_add(args) -> int:
    pid = args.id.strip()
    if not ID_RE.match(pid):
        print(f"{pid!r} is not a usable id — lowercase letters, digits, - and _",
              file=sys.stderr)
        return 1
    if any(c.get("id") == pid for c in A.commitments().get("commitments", [])):
        print(f"{pid!r} already exists — use `archive` or edit commitments.yaml",
              file=sys.stderr)
        return 1
    if args.lane not in LANES:
        print(f"unknown lane {args.lane!r} — one of {', '.join(LANES)}", file=sys.stderr)
        return 1
    if args.hours_min > args.hours_max:
        print("hours-min is above hours-max", file=sys.stderr)
        return 1

    name = args.name.strip() or pid
    block = [
        "",
        f"  - id: {pid}",
        f"    name: {name}",
    ]
    if args.dir:
        block.append(f"    dir: {args.dir.strip().rstrip('/')}")
    block += [
        f"    lane: {args.lane}",
        f"    hours_min: {num(args.hours_min)}",
        f"    hours_max: {num(args.hours_max)}",
    ]
    if args.flexible:
        block.append("    flexible: true")
    block.append(f"    priority: {args.priority}")

    rows = lines()
    at = commitments_end(rows)
    YAML.write_text("\n".join(rows[:at] + block + rows[at:]))

    made = write_state_file(pid, name, args)
    print(f"added {pid}" + (f" · created projects/{pid}.md" if made else ""))
    return 0


def write_state_file(pid: str, name: str, args) -> bool:
    """Seed projects/<pid>.md so /checkout has something to update."""
    path = PROJECTS / f"{pid}.md"
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
id: {pid}
lane: {args.lane}
dir: {args.dir or ''}
budget: {num(args.hours_min)}-{num(args.hours_max)} h/week
last_touched: null
last_session: null
---

# {name}

**What:** (one line — what this project actually is)

**Status:** Just created. Nothing logged yet.

**Next step:** (the first concrete action — a block will carry this verbatim,
so make it something you could start without thinking)

**Blockers:** none
""")
    return True


def cmd_archive(args) -> int:
    rows = lines()
    span = find_entry(rows, args.id)
    if not span:
        print(f"no commitment called {args.id!r}", file=sys.stderr)
        return 1
    start, end = span
    if any(r.strip() == "archived: true" for r in rows[start:end]):
        print(f"{args.id} is already archived")
        return 0
    rows.insert(start + 1, "    archived: true")
    YAML.write_text("\n".join(rows))
    print(f"archived {args.id} — its history and log entries are untouched")
    return 0


def cmd_restore(args) -> int:
    rows = lines()
    span = find_entry(rows, args.id)
    if not span:
        print(f"no commitment called {args.id!r}", file=sys.stderr)
        return 1
    start, end = span
    keep = [r for i, r in enumerate(rows)
            if not (start <= i < end and r.strip() == "archived: true")]
    if len(keep) == len(rows):
        print(f"{args.id} is not archived")
        return 0
    YAML.write_text("\n".join(keep))
    print(f"restored {args.id}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="the commitments the planner can see")
    ls.add_argument("--all", action="store_true", help="include archived ones")

    ad = sub.add_parser("add", help="append a new commitment")
    ad.add_argument("id")
    ad.add_argument("--name", default="")
    ad.add_argument("--lane", required=True, choices=LANES)
    ad.add_argument("--dir", default="", help="path under ~/Documents, if it has one")
    ad.add_argument("--hours-min", type=float, default=0)
    ad.add_argument("--hours-max", type=float, default=2)
    ad.add_argument("--priority", default="medium", choices=PRIORITIES)
    ad.add_argument("--flexible", action="store_true",
                    help="first to yield in a crowded week")

    ar = sub.add_parser("archive", help="hide from the board without deleting anything")
    ar.add_argument("id")

    rs = sub.add_parser("restore", help="bring an archived commitment back")
    rs.add_argument("id")

    args = p.parse_args()
    return {"list": cmd_list, "add": cmd_add,
            "archive": cmd_archive, "restore": cmd_restore}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
