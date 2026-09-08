#!/usr/bin/env python3
"""Record a workout into .agent/log/life.jsonl, and read back what you lifted.

A workout is an ordinary life event of kind `gym` with two extra fields —
`split` and `exercises`. That keeps one record where there would otherwise be
two: the streak pips count these exactly as they always have, and the training
view reads the detail off the same line.

Usage:
  workout.py next
  workout.py plan push
  workout.py log push --set incline-press:135x8 --set incline-press:135x7 \\
                      --set dips:x12 --minutes 62
  workout.py cardio basketball --minutes 75
  workout.py history --exercise chest-fly
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentlib as A  # noqa: E402

LOG = A.AGENT / "log" / "life.jsonl"

# 135x8, 135.5x8, x12 (bodyweight — reps only)
SET_RE = re.compile(r"^(?P<id>[a-z0-9\-]+):(?P<w>\d+(?:\.\d+)?)?x(?P<r>\d+)$", re.I)


# ------------------------------------------------------------------ reading

def gym_history() -> list[dict]:
    return [e for e in A.life() if e.get("kind") == "gym"]


def last_numbers() -> dict[str, dict]:
    """Exercise id -> the most recent session's sets for it.

    This is the one number that matters at the machine, so it is the one thing
    the reader is built to answer quickly.
    """
    out: dict[str, dict] = {}
    for e in gym_history():                      # oldest first; later wins
        for ex in e.get("exercises") or []:
            if ex.get("id") and ex.get("sets"):
                out[ex["id"]] = {"ts": e.get("ts"), "sets": ex["sets"],
                                 "unit": ex.get("unit", "lb")}
    return out


def top_set(sets: list[dict]) -> tuple[float, int]:
    """Heaviest set, breaking ties on reps. (0, reps) for bodyweight work."""
    best = (0.0, 0)
    for s in sets or []:
        w, r = float(s.get("weight") or 0), int(s.get("reps") or 0)
        if (w, r) > best:
            best = (w, r)
    return best


def volume(exercises: list[dict]) -> float:
    return sum(float(s.get("weight") or 0) * int(s.get("reps") or 0)
               for ex in exercises or [] for s in ex.get("sets") or [])


def describe(split: str, exercises: list[dict]) -> str:
    name = (A.split_meta().get(split) or {}).get("name", split.title())
    n_ex = len([e for e in exercises if e.get("sets")])
    n_set = sum(len(e.get("sets") or []) for e in exercises)
    return (f"{name} · {n_ex} exercise{'' if n_ex == 1 else 's'}"
            f" · {n_set} set{'' if n_set == 1 else 's'}")


# ------------------------------------------------------------------ writing

def append(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def build(split: str, exercises: list[dict], minutes: int | None,
          when: str | None = None, note: str = "") -> dict:
    """Validate and normalise a workout into its stored shape.

    Raises ValueError on anything the templates don't recognise — a typo in an
    exercise id would otherwise start a silent second history for that lift.
    """
    splits, names = A.split_meta(), A.exercise_names()
    if split not in splits:
        raise ValueError(f"unknown split {split!r} — "
                         f"workouts.yaml has {', '.join(splits) or 'none'}")

    clean = []
    for ex in exercises:
        eid = ex.get("id")
        if eid not in names:
            raise ValueError(f"unknown exercise {eid!r} — add it to workouts.yaml first")
        sets = []
        for s in ex.get("sets") or []:
            reps = int(s.get("reps") or 0)
            if reps <= 0:
                continue                     # a set with no reps never happened
            w = s.get("weight")
            sets.append({"weight": round(float(w), 1) if w not in (None, "") else None,
                         "reps": reps})
        if sets:
            clean.append({"id": eid, "name": names[eid],
                          "unit": ex.get("unit") or "lb", "sets": sets})

    if not clean:
        raise ValueError("nothing to log — record at least one set")

    return {
        "ts": when or datetime.now(A.TZ).isoformat(timespec="seconds"),
        "kind": "gym",
        "detail": note.strip() or describe(split, clean),
        "minutes": minutes,
        "with": [],
        "split": split,
        "exercises": clean,
    }


# ------------------------------------------------------------------ commands

def cmd_next(_args) -> int:
    nxt = A.next_split()
    if not nxt:
        print("no rotation in workouts.yaml")
        return 1
    print(nxt)
    return 0


def cmd_plan(args) -> int:
    sp = A.split_meta().get(args.split)
    if not sp:
        print(f"unknown split {args.split!r}", file=sys.stderr)
        return 1
    last = last_numbers()
    print(sp.get("name", args.split))
    for ex in sp.get("exercises") or []:
        prev = last.get(ex["id"])
        mark = ""
        if prev:
            w, r = top_set(prev["sets"])
            mark = f"   last: {f'{w:g}x{r}' if w else f'{r} reps'}"
        print(f"  {ex.get('sets', 2)} × {ex['name']}{mark}")
    return 0


def cmd_log(args) -> int:
    if args.stdin_json:
        payload = json.load(sys.stdin)
        exercises = payload.get("exercises") or []
        minutes = payload.get("minutes")
        when, note = payload.get("ts"), payload.get("note", "")
    else:
        grouped: dict[str, dict] = {}
        for raw in args.set or []:
            m = SET_RE.match(raw.strip())
            if not m:
                print(f"can't read set {raw!r} — expected id:135x8 or id:x12",
                      file=sys.stderr)
                return 1
            g = grouped.setdefault(m["id"], {"id": m["id"], "sets": []})
            g["sets"].append({"weight": m["w"], "reps": m["r"]})
            if not m["w"]:
                g["unit"] = "bw"
        exercises = list(grouped.values())
        minutes, when, note = args.minutes, args.when, args.note

    try:
        record = build(args.split, exercises, minutes, when, note)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    append(record)
    vol = volume(record["exercises"])
    print(f"logged: {record['detail']}" + (f" · {vol:,.0f} lb moved" if vol else ""))
    return 0


def cmd_cardio(args) -> int:
    acts = {c["id"]: c for c in A.workouts().get("cardio", []) if c.get("id")}
    if args.activity not in acts:
        print(f"unknown activity {args.activity!r} — "
              f"workouts.yaml has {', '.join(acts) or 'none'}", file=sys.stderr)
        return 1
    name = acts[args.activity].get("name", args.activity.title())
    minutes = args.minutes or acts[args.activity].get("default_minutes")
    record = {
        "ts": args.when or datetime.now(A.TZ).isoformat(timespec="seconds"),
        "kind": "cardio",
        "detail": args.note.strip() or name,
        "minutes": minutes,
        "with": [w.strip() for w in (args.with_ or "").split(",") if w.strip()],
        "activity": args.activity,
    }
    append(record)
    print(f"logged: {record['detail']}" + (f" · {minutes}m" if minutes else ""))
    return 0


def cmd_history(args) -> int:
    rows = gym_history()[-args.limit:]
    if args.exercise:
        names = A.exercise_names()
        if args.exercise not in names:
            print(f"unknown exercise {args.exercise!r}", file=sys.stderr)
            return 1
        print(names[args.exercise])
        for e in rows:
            for ex in e.get("exercises") or []:
                if ex.get("id") == args.exercise:
                    sets = "  ".join(
                        f"{s['weight']:g}x{s['reps']}" if s.get("weight")
                        else f"x{s['reps']}" for s in ex["sets"])
                    print(f"  {(e.get('ts') or '')[:10]}   {sets}")
        return 0
    for e in rows:
        print(f"{(e.get('ts') or '')[:10]}  {e.get('detail','')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("next", help="print the split that comes after the last one logged")

    q = sub.add_parser("plan", help="print a split with last session's numbers")
    q.add_argument("split")

    lg = sub.add_parser("log", help="record a completed workout")
    lg.add_argument("split")
    lg.add_argument("--set", action="append", metavar="ID:WEIGHTxREPS",
                    help="repeatable; omit the weight for bodyweight (id:x12)")
    lg.add_argument("--minutes", type=int, default=None)
    lg.add_argument("--note", default="", help="overrides the generated summary")
    lg.add_argument("--when", default=None, help="ISO timestamp; defaults to now")
    lg.add_argument("--stdin-json", action="store_true",
                    help="read {exercises, minutes, ts, note} from stdin instead")

    cd = sub.add_parser("cardio", help="record cardio")
    cd.add_argument("activity")
    cd.add_argument("--minutes", type=int, default=None)
    cd.add_argument("--note", default="")
    cd.add_argument("--with", dest="with_", default="")
    cd.add_argument("--when", default=None)

    hs = sub.add_parser("history", help="what you have logged")
    hs.add_argument("--exercise", default="", help="one lift's progression")
    hs.add_argument("--limit", type=int, default=12)

    args = p.parse_args()
    return {"next": cmd_next, "plan": cmd_plan, "log": cmd_log,
            "cardio": cmd_cardio, "history": cmd_history}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
