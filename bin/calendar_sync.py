#!/usr/bin/env python3
"""Pull Google Calendar into .agent/calendar.json, which the dashboard reads.

Two ways in, because they fail differently:

  1. ICS URL (self-refreshing). Google Calendar → Settings → your calendar →
     "Secret address in iCal format". Put it in .agent/calendar_source.txt and
     the dashboard re-fetches on its own every 10 minutes. No Claude session
     needed — add an event on your phone and it shows up.

        calendar_sync.py --ics https://calendar.google.com/calendar/ical/.../basic.ics

     Each calendar has its own secret address. Put one URL per line in
     calendar_source.txt to merge several. Prefix a line with a label and every
     event from that feed carries it as its kind, instead of being guessed at
     from the title — which matters for the plan calendar, whose blocks are
     named after courses and would otherwise be filed as classes:

        https://calendar.google.com/calendar/ical/.../basic.ics
        plan  https://calendar.google.com/calendar/ical/.../basic.ics

     Blank lines and #-comments are ignored.

  2. Stdin (a Claude session with the Google Calendar MCP). Pipe the events
     array from list_events straight in:

        calendar_sync.py --from-mcp < events.json

The secret ICS address is a credential: anyone holding it can read the whole
calendar. calendar_source.txt is gitignored and is never printed by this script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentlib as A  # noqa: E402

CACHE = A.AGENT / "calendar.json"
SOURCE = A.AGENT / "calendar_source.txt"
TZ = ZoneInfo("America/New_York")
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


# ------------------------------------------------------------------ shape

def classify(summary: str) -> str:
    """class | tutoring | other. Drives which row an event lands on."""
    s = (summary or "").lower()
    if "tutor" in s:
        return "tutoring"
    if re.search(r"\b[a-z]{2,6}\s?\d{3}\b", s) or \
       re.search(r"\b(lec|lecture|lab|disc|discussion|recitation|seminar|section)\b", s):
        return "class"
    return "other"


def event(uid: str, summary: str, start: datetime, end: datetime,
          location: str = "", all_day: bool = False, kind: str = "") -> dict:
    return {
        "id": uid,
        "summary": summary or "(untitled)",
        "location": location or "",
        "start": start.astimezone(TZ).isoformat(timespec="seconds"),
        "end": end.astimezone(TZ).isoformat(timespec="seconds"),
        "all_day": all_day,
        "kind": kind or classify(summary),
    }


# ------------------------------------------------------------------- ICS

def unfold(text: str) -> list[str]:
    """RFC 5545 folds long lines with a leading space or tab on the next line."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def unescape(value: str) -> str:
    return (value.replace("\\n", "\n").replace("\\N", "\n")
                 .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def parse_prop(line: str) -> tuple[str, dict[str, str], str] | None:
    """'DTSTART;TZID=America/New_York:20260907T101000' → name, params, value"""
    head, sep, value = line.partition(":")
    if not sep:
        return None
    name, *raw_params = head.split(";")
    params = {}
    for p in raw_params:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return name.upper(), params, value


def parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    """Returns (aware datetime, is_all_day)."""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d")
        return d.replace(tzinfo=TZ), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=ZoneInfo("UTC")), False
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tz = params.get("TZID")
    try:
        return naive.replace(tzinfo=ZoneInfo(tz) if tz else TZ), False
    except Exception:
        return naive.replace(tzinfo=TZ), False


def parse_ics(text: str) -> list[dict]:
    """VEVENTs as raw dicts. Unsupported properties are ignored, not guessed at."""
    events, current = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            current = {"exdate": [], "rrule": None}
            continue
        if line == "END:VEVENT":
            if current and current.get("start"):
                events.append(current)
            current = None
            continue
        if current is None:
            continue
        prop = parse_prop(line)
        if not prop:
            continue
        name, params, value = prop
        if name == "DTSTART":
            current["start"], current["all_day"] = parse_dt(value, params)
        elif name == "DTEND":
            current["end"], _ = parse_dt(value, params)
        elif name == "DURATION":
            m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
            if m:
                current["duration"] = timedelta(hours=int(m.group(1) or 0),
                                                minutes=int(m.group(2) or 0))
        elif name in ("SUMMARY", "LOCATION", "UID", "STATUS"):
            current[name.lower()] = unescape(value)
        elif name == "RRULE":
            current["rrule"] = dict(
                (k.upper(), v) for k, _, v in (p.partition("=") for p in value.split(";")))
        elif name == "EXDATE":
            for part in value.split(","):
                current["exdate"].append(parse_dt(part, params)[0])
        elif name == "RECURRENCE-ID":
            current["recurrence_id"] = parse_dt(value, params)[0]
    return events


def expand(raw: dict, window: tuple[datetime, datetime]) -> list[datetime]:
    """Start times of this event inside the window. Weekly/daily rules only."""
    start, (lo, hi) = raw["start"], window
    rule = raw.get("rrule")
    if not rule:
        return [start] if lo <= start < hi else []

    freq = rule.get("FREQ", "")
    if freq not in ("DAILY", "WEEKLY"):
        # Monthly/yearly rules aren't expanded — the base occurrence still shows,
        # so an unsupported rule under-reports rather than inventing dates.
        return [start] if lo <= start < hi else []

    interval = int(rule.get("INTERVAL") or 1)
    until = None
    if rule.get("UNTIL"):
        until, _ = parse_dt(rule["UNTIL"], {})
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    days = [WEEKDAYS[d] for d in rule.get("BYDAY", "").split(",")
            if d in WEEKDAYS] or [start.weekday()]
    skip = {d.astimezone(TZ).replace(second=0, microsecond=0) for d in raw["exdate"]}

    out, emitted = [], 0
    if freq == "DAILY":
        cursor, step = start, timedelta(days=interval)
    else:
        # walk week by week from the Monday of the first occurrence
        cursor = start - timedelta(days=start.weekday())
        step = timedelta(weeks=interval)

    guard = 0
    while cursor < hi and guard < 2000:
        guard += 1
        candidates = [cursor] if freq == "DAILY" else [
            (cursor + timedelta(days=d)).replace(
                hour=start.hour, minute=start.minute, second=start.second)
            for d in sorted(days)]
        for c in candidates:
            if c < start:
                continue
            if until and c > until:
                return out
            if count is not None and emitted >= count:
                return out
            emitted += 1
            if c.replace(second=0, microsecond=0) in skip:
                continue
            if lo <= c < hi:
                out.append(c)
        cursor += step
    return out


def read_sources() -> list[tuple[str, str]]:
    """calendar_source.txt → [(kind_label, url)]. A bare line has no label."""
    if not SOURCE.exists():
        return []
    out = []
    for line in SOURCE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and "://" in parts[1]:
            out.append((parts[0].lower(), parts[1].strip()))
        else:
            out.append(("", line))
    return out


def from_ics(sources: list[tuple[str, str]], days: int) -> list[dict]:
    raws = []
    for label, url in sources:
        with urllib.request.urlopen(url, timeout=25) as fh:
            for raw in parse_ics(fh.read().decode("utf-8", "replace")):
                raw["kind_label"] = label
                raws.append(raw)

    now = datetime.now(TZ)
    lo = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    window = (lo, lo + timedelta(days=days))

    overrides = {}
    for r in raws:
        if r.get("recurrence_id"):
            overrides[(r.get("uid"), r["recurrence_id"].astimezone(TZ)
                       .replace(second=0, microsecond=0))] = r

    out = []
    for raw in raws:
        if raw.get("recurrence_id") or raw.get("status") == "CANCELLED":
            continue
        length = (raw["end"] - raw["start"]) if raw.get("end") \
            else raw.get("duration") or timedelta(hours=1)
        for start in expand(raw, window):
            key = (raw.get("uid"), start.astimezone(TZ).replace(second=0, microsecond=0))
            over = overrides.get(key)
            if over:
                if over.get("status") == "CANCELLED":
                    continue
                o_len = (over["end"] - over["start"]) if over.get("end") else length
                out.append(event(f"{over.get('uid','')}-{over['start']:%Y%m%dT%H%M}",
                                 over.get("summary", ""), over["start"],
                                 over["start"] + o_len, over.get("location", ""),
                                 over.get("all_day", False), raw.get("kind_label", "")))
                continue
            out.append(event(f"{raw.get('uid','')}-{start:%Y%m%dT%H%M}",
                             raw.get("summary", ""), start, start + length,
                             raw.get("location", ""), raw.get("all_day", False),
                             raw.get("kind_label", "")))
    return out


# ------------------------------------------------------------------- MCP

def from_mcp(payload: str) -> list[dict]:
    """The events array from the Google Calendar MCP's list_events."""
    data = json.loads(payload)
    rows = data.get("events", data) if isinstance(data, dict) else data
    out = []
    for e in rows:
        start, end = e.get("start", {}), e.get("end", {})
        s = start.get("dateTime") or start.get("date")
        t = end.get("dateTime") or end.get("date")
        if not s or e.get("status") == "cancelled":
            continue
        sdt = datetime.fromisoformat(s)
        edt = datetime.fromisoformat(t) if t else sdt + timedelta(hours=1)
        if sdt.tzinfo is None:
            sdt, edt = sdt.replace(tzinfo=TZ), edt.replace(tzinfo=TZ)
        out.append(event(e.get("id", ""), e.get("summary", ""), sdt, edt,
                         e.get("location", ""), bool(start.get("date"))))
    return out


def write(events: list[dict], source: str) -> None:
    events.sort(key=lambda e: e["start"])
    CACHE.write_text(json.dumps({
        "synced": datetime.now(TZ).isoformat(timespec="seconds"),
        "source": source,
        "events": events,
    }, indent=2))
    kinds = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "nothing"
    print(f"synced {len(events)} event(s) — {summary}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ics", help="Secret iCal URL. Defaults to calendar_source.txt.")
    p.add_argument("--from-mcp", action="store_true",
                   help="Read a list_events JSON payload on stdin instead.")
    p.add_argument("--days", type=int, default=28, help="Window to expand, from Monday.")
    args = p.parse_args()

    if args.from_mcp:
        write(from_mcp(sys.stdin.read()), "google-mcp")
        return 0

    sources = [("", args.ics)] if args.ics else read_sources()
    if not sources:
        print("no ICS url: pass --ics, or put the secret iCal address in\n"
              f"  {SOURCE}\n"
              "Google Calendar → Settings → the calendar → Secret address in iCal format.",
              file=sys.stderr)
        return 1
    try:
        labels = [l or "auto" for l, _ in sources]
        write(from_ics(sources, args.days), "ics: " + ", ".join(labels))
    except Exception as exc:
        print(f"ICS fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
