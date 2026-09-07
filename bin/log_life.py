#!/usr/bin/env python3
"""Append a life event (gym, cardio, meal, social, sleep) to .agent/log/life.jsonl.

Deliberately low-friction: you report after the fact, the system records.
Nothing here is ever scheduled in advance.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
LOG = AGENT / "log" / "life.jsonl"
TZ = ZoneInfo("America/New_York")

KINDS = ["gym", "cardio", "meal", "social", "sleep", "other"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("kind", choices=KINDS)
    p.add_argument("--detail", default="", help='e.g. "push day", "3mi run", "dinner with a friend"')
    p.add_argument("--minutes", type=int, default=None)
    p.add_argument("--with", dest="with_", default="", help="Comma-separated people.")
    p.add_argument("--when", default=None, help="ISO timestamp; defaults to now.")
    args = p.parse_args()

    record = {
        "ts": args.when or datetime.now(TZ).isoformat(timespec="seconds"),
        "kind": args.kind,
        "detail": args.detail.strip(),
        "minutes": args.minutes,
        "with": [w.strip() for w in args.with_.split(",") if w.strip()],
    }

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")

    print(f"logged: {record['kind']}"
          + (f" — {record['detail']}" if record["detail"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
