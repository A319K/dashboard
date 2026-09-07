#!/usr/bin/env python3
"""Stop hook: remind you to /checkout when a work session ends unlogged.

Reads the hook payload on stdin, maps the session's cwd to a project id from
commitments.yaml, and emits a systemMessage only when that project has no
sessions.jsonl entry in the last few hours.

Deliberately quiet: it stays silent unless the session was plausibly real work
in a tracked project. A reminder that fires on every trivial question gets
ignored, and then the whole capture layer dies with it.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home()
# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/New_York")
QUIET_HOURS = 3  # don't re-remind if this project checked out recently


def emit(message: str | None) -> None:
    if message:
        print(json.dumps({"systemMessage": message}))
    sys.exit(0)


def project_dirs() -> list[tuple[str, str]]:
    """(id, dir) pairs from commitments.yaml, without a yaml dependency."""
    path = AGENT / "commitments.yaml"
    if not path.exists():
        return []
    pairs: list[tuple[str, str]] = []
    current: str | None = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            current = s.split(":", 1)[1].strip()
        elif s.startswith("dir:") and current:
            pairs.append((current, s.split(":", 1)[1].strip()))
            current = None
    return pairs


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()

    docs = (HOME / "Documents").resolve()
    if docs not in cwd.parents and cwd != docs:
        emit(None)

    # Which tracked project is this? Longest matching dir wins (nested paths).
    match: tuple[str, Path] | None = None
    for pid, rel in project_dirs():
        pdir = (HOME / "Documents" / rel).resolve()
        if pdir == cwd or pdir in cwd.parents:
            if match is None or len(str(pdir)) > len(str(match[1])):
                match = (pid, pdir)
    if match is None:
        emit(None)

    pid = match[0]

    log = AGENT / "log" / "sessions.jsonl"
    cutoff = datetime.now(TZ) - timedelta(hours=QUIET_HOURS)
    if log.exists():
        for line in log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("project") == pid and \
                        datetime.fromisoformat(row["ts"]) >= cutoff:
                    emit(None)  # already checked out recently
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    emit(f"No checkout logged for '{pid}' yet — run /checkout to report back "
         f"to the master agent, or ignore if this wasn't a work session.")


if __name__ == "__main__":
    main()
