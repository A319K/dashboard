#!/usr/bin/env python3
"""Shared readers for the .agent state layer. Stdlib only, no dependencies.

Includes a deliberately small YAML loader covering exactly the shapes used by
commitments.yaml and deadlines.yaml — nested maps, lists of scalars, and lists
of maps. It raises on anything it doesn't understand rather than guessing, so a
malformed file fails loudly instead of silently losing a commitment.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# Located relative to this file, not to $HOME/Documents. The whole tree can be
# moved or renamed and every CLI still finds its state.
AGENT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/New_York")

_SCALAR_INT = re.compile(r"^-?\d+$")
_SCALAR_FLOAT = re.compile(r"^-?\d+\.\d+$")


class YamlError(ValueError):
    """Raised when the file uses YAML beyond this loader's supported subset."""


def _scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return None
    if s[0] in "\"'" and s[-1] == s[0] and len(s) >= 2:
        return s[1:-1]
    # inline flow collections — we only emit simple ones
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    if s == "{}":
        return {}
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _SCALAR_INT.match(s):
        return int(s)
    if _SCALAR_FLOAT.match(s):
        return float(s)
    return s


def _strip_comment(line: str) -> str:
    """Remove a trailing # comment, respecting quotes."""
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def load_yaml(path: Path) -> Any:
    """Parse the supported YAML subset. Returns dict, list, or None if empty."""
    if not path.exists():
        return None

    rows: list[tuple[int, str]] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        text = _strip_comment(raw)
        if not text.strip():
            continue
        if "\t" in text[: len(text) - len(text.lstrip())]:
            raise YamlError(f"{path.name}:{n}: tab indentation is not supported")
        rows.append((len(text) - len(text.lstrip()), text.strip()))

    if not rows:
        return None

    pos = 0

    def parse_block(indent: int) -> Any:
        nonlocal pos
        if pos >= len(rows):
            return None
        if rows[pos][1].startswith("- "):
            return parse_list(indent)
        return parse_map(indent)

    def parse_list(indent: int) -> list:
        nonlocal pos
        items: list[Any] = []
        while pos < len(rows):
            ind, text = rows[pos]
            if ind < indent or not text.startswith("- "):
                break
            if ind > indent:
                raise YamlError(f"unexpected indent in list near {text!r}")
            body = text[2:].strip()
            pos += 1
            if ":" in body and not body.startswith(("\"", "'")):
                # list of maps: first pair inline, rest indented beneath
                key, _, val = body.partition(":")
                entry: dict[str, Any] = {key.strip(): _scalar(val)}
                child = indent + 2
                while pos < len(rows) and rows[pos][0] >= child and \
                        not rows[pos][1].startswith("- "):
                    entry.update(parse_map(rows[pos][0]))
                items.append(entry)
            else:
                items.append(_scalar(body))
        return items

    def parse_map(indent: int) -> dict:
        nonlocal pos
        out: dict[str, Any] = {}
        while pos < len(rows):
            ind, text = rows[pos]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError(f"unexpected indent near {text!r}")
            if text.startswith("- "):
                break
            if ":" not in text:
                raise YamlError(f"expected 'key: value' near {text!r}")
            key, _, val = text.partition(":")
            key, val = key.strip(), val.strip()
            pos += 1
            if val:
                out[key] = _scalar(val)
            elif pos < len(rows) and (
                rows[pos][0] > indent
                or (rows[pos][0] == indent and rows[pos][1].startswith("- "))
            ):
                out[key] = parse_block(rows[pos][0])
            else:
                out[key] = None
        return out

    return parse_block(rows[0][0])


# ---------------------------------------------------------------- readers

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def commitments() -> dict:
    return load_yaml(AGENT / "commitments.yaml") or {}


def deadlines() -> list[dict]:
    data = load_yaml(AGENT / "deadlines.yaml") or {}
    return data.get("deadlines") or []


def sessions() -> list[dict]:
    return read_jsonl(AGENT / "log" / "sessions.jsonl")


def life() -> list[dict]:
    return read_jsonl(AGENT / "log" / "life.jsonl")


def workouts() -> dict:
    """The training templates: rotation order, splits, cardio activities."""
    return load_yaml(AGENT / "workouts.yaml") or {}


def split_meta() -> dict[str, dict]:
    """Split id -> its workouts.yaml entry, in file order."""
    return {s["id"]: s for s in workouts().get("splits", []) if s.get("id")}


def exercise_names() -> dict[str, str]:
    """Exercise id -> display name, including the alternates behind `or`."""
    out: dict[str, str] = {}
    for sp in workouts().get("splits", []):
        for ex in sp.get("exercises", []) or []:
            for side in (ex, ex.get("or")):
                if side and side.get("id"):
                    out[side["id"]] = side.get("name", side["id"])
    return out


def next_split(history: list[dict] | None = None) -> str | None:
    """The split after the one most recently logged.

    Derived rather than stored, so a skipped day shifts the rotation
    forward instead of leaving you permanently behind it.
    """
    order = workouts().get("rotation") or []
    if not order:
        return None
    for e in reversed(history if history is not None else life()):
        last = e.get("split")
        if last in order:
            return order[(order.index(last) + 1) % len(order)]
    return order[0]


def queued_blocks(include_done: bool = False) -> list[dict]:
    """Pending calendar rows. Plans only, unless include_done.

    Completed sessions ("done") share the queue because they flush to the same
    calendar, but they are not plans: the dashboard already draws them from
    sessions.jsonl, and counting them as blocks would double-draw the week and
    eat into max_blocks_per_day.
    """
    rows = read_jsonl(AGENT / "pending_calendar.jsonl")
    if include_done:
        return rows
    return [r for r in rows if r.get("kind") != "done"]


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 through the following Monday, in local time."""
    now = now or datetime.now(TZ)
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt


def project_meta() -> dict[str, dict]:
    """Project id → its commitments.yaml entry."""
    return {c["id"]: c for c in commitments().get("commitments", []) if c.get("id")}


def project_state(pid: str) -> dict:
    """Parse .agent/projects/<pid>.md into frontmatter + named sections."""
    path = AGENT / "projects" / f"{pid}.md"
    if not path.exists():
        return {}
    text = path.read_text()
    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        _, _, rest = text.partition("---")
        fm, _, body = rest.partition("---")
        for line in fm.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = _scalar(v)

    sections: dict[str, str] = {}
    # [ \t]* not \s*: an empty section must not run past the blank line and
    # swallow the next one. **Next step:** with nothing after it is empty, and
    # the **Blockers:** below it is its own section.
    for m in re.finditer(r"\*\*(.+?):\*\*[ \t]*(.*?)(?=\n\*\*|\n##|\Z)", body, re.S):
        sections[m.group(1).strip().lower()] = m.group(2).strip()

    return {"meta": meta, "sections": sections, "path": str(path)}
