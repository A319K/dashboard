#!/usr/bin/env python3
"""Local dashboard for the .agent state layer. Stdlib only — no build step.

    python3 ~/Documents/.agent/dashboard/server.py

Binds 127.0.0.1 only. This is an on-demand view, not a daemon: nothing in the
system depends on it running. Start it when you want it, Ctrl-C when done.
"""
from __future__ import annotations

import base64
import json
import math
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import agentlib as A  # noqa: E402
import workout as W  # noqa: E402

HERE = Path(__file__).resolve().parent
AGENT = A.AGENT
RUNTIME = AGENT / "log" / "runtime.json"
INBOX = AGENT / "inbox"
TASKS = AGENT / "tasks.jsonl"
CALENDAR = AGENT / "calendar.json"
CAL_SOURCE = AGENT / "calendar_source.txt"
CAL_REFRESH_SECONDS = 600
PORT = 7717
BLOCK_MINUTES = 50
BREAK_MINUTES = 10

# What /intake can actually read. Anything else is refused at the door rather
# than sitting in the inbox as a file no skill can open.
INBOX_EXT = {".pdf", ".md", ".txt", ".rtf", ".docx", ".doc", ".pptx", ".xlsx",
             ".csv", ".tsv", ".png", ".jpg", ".jpeg", ".webp", ".heic",
             ".ics", ".json", ".yaml", ".yml", ".html"}
MAX_UPLOAD = 40 * 1024 * 1024
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_cal_lock = threading.Lock()
_cal_checked = 0.0


def refresh_calendar() -> None:
    """Re-pull the ICS feed, at most once every CAL_REFRESH_SECONDS.

    Only runs when .agent/calendar_source.txt holds a secret iCal URL. Without
    one the cache is whatever a Claude session last wrote through
    `calendar_sync.py --from-mcp`, and the UI says how old that is.
    """
    global _cal_checked
    if not CAL_SOURCE.exists():
        return
    with _cal_lock:
        if time.time() - _cal_checked < CAL_REFRESH_SECONDS:
            return
        _cal_checked = time.time()
    threading.Thread(target=run_cli, args=("calendar_sync.py", []), daemon=True).start()


def calendar_cache() -> dict:
    if not CALENDAR.exists():
        return {"synced": None, "source": None, "events": []}
    try:
        return json.loads(CALENDAR.read_text())
    except json.JSONDecodeError:
        return {"synced": None, "source": "unreadable", "events": []}


def week_events(day: datetime) -> list[dict]:
    """Calendar events falling in the week that contains `day`."""
    start, end = A.week_bounds(day)
    out = []
    for ev in calendar_cache().get("events", []):
        when = A.parse_ts(ev.get("start"))
        if when and start <= when < end:
            out.append(ev)
    return out


def unwrap(text: str) -> str:
    """Collapse the hard line wraps in the project .md files into flowing text.

    The files are hand-wrapped at ~78 chars, which reads as broken mid-sentence
    line breaks in the UI. Blank lines still separate paragraphs.
    """
    parts = re.split(r"\n\s*\n", text.strip())
    return "\n\n".join(" ".join(p.split()) for p in parts)


def split_blockers(text: str) -> list[str]:
    """Blockers section → a list. Empty when it says some form of 'none'."""
    text = text.strip()
    if not text or re.match(r"^none\b", text, re.I):
        return []
    items = re.split(r"\n\s*[-*]\s+", "\n" + text)
    return [" ".join(i.split()) for i in items if i.strip()]


def read_runtime() -> dict:
    if RUNTIME.exists():
        try:
            return json.loads(RUNTIME.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def write_runtime(data: dict) -> None:
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME.write_text(json.dumps(data, indent=2))


_snap_lock = threading.Lock()
_snap_at = 0.0
SNAPSHOT_SECONDS = 120


def snapshot() -> None:
    """Commit the state layer to its private history, at most twice a minute.

    Runs detached so a slow git never delays a response, and stays silent on
    failure: a missing history is a worse day later, but a broken save button is
    a worse day now. `bin/state log` is where you find out whether it is working.
    """
    global _snap_at
    script = AGENT / "bin" / "state"
    if not script.exists():
        return
    with _snap_lock:
        if time.time() - _snap_at < SNAPSHOT_SECONDS:
            return
        _snap_at = time.time()
    threading.Thread(
        target=lambda: subprocess.run(
            [str(script), "save"], capture_output=True, text=True, timeout=20),
        daemon=True).start()


def run_cli(script: str, args: list[str], stdin: str | None = None) -> tuple[bool, str]:
    """Route every write through the existing CLIs so validation stays in one place."""
    proc = subprocess.run(
        [sys.executable, str(AGENT / "bin" / script), *args],
        capture_output=True, text=True, input=stdin,
    )
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        snapshot()
    return proc.returncode == 0, out


def build_state() -> dict:
    now = datetime.now(A.TZ)
    wk_start, wk_end = A.week_bounds(now)
    meta = A.project_meta()
    sessions = A.sessions()
    life = A.life()

    wk_sessions = [s for s in sessions
                   if (t := A.parse_ts(s.get("ts"))) and wk_start <= t < wk_end]
    wk_life = [e for e in life
               if (t := A.parse_ts(e.get("ts"))) and wk_start <= t < wk_end]

    # ---- projects
    projects = []
    for pid, cm in meta.items():
        st = A.project_state(pid)
        sec = st.get("sections", {})
        mins = sum(s.get("actual_minutes") or 0
                   for s in wk_sessions if s.get("project") == pid)
        focus = [s["focus"] for s in wk_sessions
                 if s.get("project") == pid and s.get("focus")]
        last = next((s for s in reversed(sessions) if s.get("project") == pid), None)
        blockers = split_blockers(sec.get("blockers", ""))
        projects.append({
            "id": pid,
            "name": cm.get("name", pid),
            "lane": cm.get("lane", ""),
            "dir": cm.get("dir", ""),
            "priority": cm.get("priority", "medium"),
            "flexible": bool(cm.get("flexible")),
            "archived": bool(cm.get("archived")),
            "hours_min": cm.get("hours_min", 0),
            "hours_max": cm.get("hours_max", 0),
            "minutes_this_week": mins,
            "sessions_this_week": len([s for s in wk_sessions if s.get("project") == pid]),
            "avg_focus": round(sum(focus) / len(focus), 1) if focus else None,
            "status": unwrap(sec.get("status", "")),
            "next": unwrap(sec.get("next step", "")),
            "blockers": blockers,
            "last_touched": str(st.get("meta", {}).get("last_touched") or ""),
            "last_next": (last or {}).get("next", ""),
        })
    order = {"high": 0, "medium": 1, "low": 2}
    projects.sort(key=lambda p: (p["archived"], order.get(p["priority"], 3),
                                 -p["minutes_this_week"]))

    # ---- habits
    habits = []
    for h in A.commitments().get("habits", []):
        n = len([e for e in wk_life if e.get("kind") == h["id"]])
        habits.append({
            "id": h["id"],
            "count": n,
            "target": h.get("target_per_week", 0),
            "stretch": h.get("stretch"),
            "next_split": A.next_split(life) if h["id"] == "gym" else None,
        })

    # ---- deadlines
    dls = []
    for d in A.deadlines():
        due = A.parse_ts(d.get("due"))
        if not due or d.get("status") in ("done",):
            continue
        dls.append({
            "id": d.get("id"),
            "title": d.get("title", ""),
            "commitment": d.get("commitment", ""),
            "due": due.isoformat(),
            "days_left": (due - now).total_seconds() / 86400,
            "est_hours": d.get("est_hours"),
            "status": d.get("status", "open"),
        })
    dls.sort(key=lambda d: d["days_left"])

    # ---- blocks (queued; becomes the live plan calendar after reconnect)
    blocks = []
    for b in A.queued_blocks():
        start = A.parse_ts(b.get("start"))
        if not start or not (wk_start <= start < wk_end) or b.get("status") != "pending":
            continue
        done = any(s.get("planned_block_id") == b["id"] for s in sessions)
        blocks.append({
            "id": b["id"],
            "summary": b.get("summary", ""),
            "commitment": b.get("commitment"),
            "first_action": b.get("first_action") or "",
            "kind": b.get("kind", "block"),
            "start": start.isoformat(),
            "minutes": b.get("minutes", 50),
            "dow": start.weekday(),
            "done": done,
            "past": start < now,
        })
    blocks.sort(key=lambda b: b["start"])

    # ---- calendar events for the week grid, grouped into their own rows
    refresh_calendar()
    cache = calendar_cache()
    fixed = []
    for ev in week_events(now):
        start = A.parse_ts(ev["start"])
        fixed.append({
            "dow": start.weekday(),
            "label": ev["summary"],
            "location": ev.get("location", ""),
            "kind": ev.get("kind", "other"),
            "all_day": bool(ev.get("all_day")),
            "start": ev["start"],
            "end": ev["end"],
        })
    synced = A.parse_ts(cache.get("synced"))
    calendar = {
        "synced": cache.get("synced"),
        "source": cache.get("source"),
        "live": CAL_SOURCE.exists(),
        "age_minutes": round((now - synced).total_seconds() / 60) if synced else None,
        "count": len(fixed),
    }

    # ---- focus heatmap (all history)
    cells: dict[str, list[int]] = {}
    for s in sessions:
        t = A.parse_ts(s.get("ts"))
        if t and s.get("focus"):
            cells.setdefault(f"{t.weekday()}-{t.hour}", []).append(s["focus"])
    heat = {k: round(sum(v) / len(v), 2) for k, v in cells.items()}

    # ---- this week's actual sessions, for the trace
    week_sessions = []
    for s in wk_sessions:
        t = A.parse_ts(s["ts"])
        mins = s.get("actual_minutes") or 25
        week_sessions.append({
            "project": s.get("project"),
            "start": (t - timedelta(minutes=mins)).isoformat(),
            "minutes": mins,
            "focus": s.get("focus"),
            "did": s.get("did", ""),
        })

    env = A.commitments().get("envelope", {})
    return {
        "week_sessions": week_sessions,
        "now": now.isoformat(),
        "week_start": wk_start.isoformat(),
        "today_dow": now.weekday(),
        "projects": projects,
        "habits": habits,
        "deadlines": dls,
        "blocks": blocks,
        "fixed": fixed,
        "heatmap": heat,
        "active": read_runtime().get("active"),
        "envelope": env,
        "recent": [
            {**s, "when": A.parse_ts(s["ts"]).strftime("%a %m/%d %H:%M")}
            for s in sessions[-8:][::-1] if A.parse_ts(s.get("ts"))
        ],
        "totals": {
            "minutes": sum(s.get("actual_minutes") or 0 for s in wk_sessions),
            "sessions": len(wk_sessions),
        },
        "meals_this_week": len([e for e in wk_life
                                if e.get("kind") in ("meal", "social")]),
        "tasks": tasks_state(now),
        "tasks_done_earlier": len([
            t for t in A.read_jsonl(TASKS)
            if t.get("status") == "done"
            and (d := A.parse_ts(t.get("done_ts"))) and d < wk_start]),
        "inbox": inbox_files(),
        "calendar": calendar,
        "session_count": len(sessions),
    }


def tasks_state(now: datetime) -> list[dict]:
    """Open and scheduled tasks, plus whatever was finished this week.

    Older finished tasks stay in the file — `task.py prune` clears them out —
    but they don't belong on a screen whose job is what to do next.
    """
    wk_start, _ = A.week_bounds(now)
    out, earlier = [], 0
    for t in A.read_jsonl(TASKS):
        if t.get("status") == "done":
            done = A.parse_ts(t.get("done_ts"))
            if not done or done < wk_start:
                earlier += 1          # kept in the file, just not on this screen
                continue
        due = A.parse_ts(t.get("due"))
        out.append({
            **t,
            "due": due.isoformat() if due else None,
            "days_left": (due - now).total_seconds() / 86400 if due else None,
            "blocks_needed": math.ceil((t.get("est_minutes") or BLOCK_MINUTES) / BLOCK_MINUTES),
        })
    rank = {"open": 0, "scheduled": 1, "done": 2}
    out.sort(key=lambda t: (rank.get(t["status"], 3),
                            t["days_left"] if t["days_left"] is not None else 999,
                            t.get("created") or ""))
    for t in out:
        t["done_earlier_count"] = earlier
    return out


def day_busy(day: datetime) -> list[tuple[datetime, datetime]]:
    """Everything already claiming time on that date: calendar events and queued blocks."""
    spans = []
    for ev in week_events(day):
        if ev.get("all_day"):
            continue          # a birthday doesn't stop you working that day
        start, end = A.parse_ts(ev["start"]), A.parse_ts(ev["end"])
        if start and end and start.date() == day.date():
            spans.append((start, end))
    for b in A.queued_blocks():
        start = A.parse_ts(b.get("start"))
        if start and start.date() == day.date() and b.get("status") == "pending":
            spans.append((start, start + timedelta(minutes=b.get("minutes", BLOCK_MINUTES))))
    return sorted(spans)


def free_slots(day: datetime, count: int, now: datetime) -> list[datetime]:
    """Up to `count` block-sized openings on that day, earliest first.

    Respects the envelope, leaves a break after each block, never places a block
    in the past, and stops at max_blocks_per_day counting what's already queued.
    """
    if day.date() < now.date():
        return []                       # a block you can't attend isn't a plan

    env = A.commitments().get("envelope", {})
    eh, em = map(int, str(env.get("earliest", "08:00")).split(":"))
    lh, lm = map(int, str(env.get("latest", "23:00")).split(":"))
    cap = int(env.get("max_blocks_per_day", 4))

    queued_today = len([b for b in A.queued_blocks()
                        if (t := A.parse_ts(b.get("start"))) and t.date() == day.date()
                        and b.get("status") == "pending"])
    count = min(count, max(0, cap - queued_today))
    if count <= 0:
        return []

    busy = day_busy(day)
    window_end = day.replace(hour=lh, minute=lm)
    cursor = day.replace(hour=eh, minute=em)
    if day.date() == now.date():
        cursor = max(cursor, now.replace(second=0, microsecond=0))
        cursor += timedelta(minutes=(-cursor.minute) % 15)   # round to a clean start

    out = []
    while len(out) < count and cursor + timedelta(minutes=BLOCK_MINUTES) <= window_end:
        end = cursor + timedelta(minutes=BLOCK_MINUTES)
        clash = next((b for b in busy if b[0] < end and cursor < b[1]), None)
        if clash:
            cursor = clash[1]
            continue
        out.append(cursor)
        busy.append((cursor, end))
        busy.sort()
        cursor = end + timedelta(minutes=BREAK_MINUTES)
    return out


def inbox_files() -> list[dict]:
    """Whatever is sitting in .agent/inbox/ waiting for /intake."""
    if not INBOX.exists():
        return []
    out = []
    for p in sorted(INBOX.iterdir(), key=lambda q: q.stat().st_mtime, reverse=True):
        if p.is_file() and not p.name.startswith("."):
            out.append({
                "name": p.name,
                "size": p.stat().st_size,
                "dropped": datetime.fromtimestamp(p.stat().st_mtime, A.TZ)
                                   .isoformat(timespec="seconds"),
            })
    return out


def inbox_path(name: str) -> Path | None:
    """Resolve a client-supplied name to a file directly inside the inbox."""
    base = Path(name).name.strip()
    if not base or base.startswith("."):
        return None
    path = (INBOX / base).resolve()
    return path if path.parent == INBOX.resolve() else None


def free_name(name: str) -> Path:
    """Never overwrite. hw1.pdf → hw1-2.pdf → hw1-3.pdf"""
    path = inbox_path(name)
    if path is None:
        raise ValueError("unusable filename")
    stem, suffix, n = path.stem, path.suffix, 2
    while path.exists():
        path = INBOX / f"{stem}-{n}{suffix}"
        n += 1
    return path


def queue_done(data: dict) -> str:
    """Queue a finished session for the Claude Plan calendar.

    This process is stdlib-only and cannot reach the Google Calendar MCP, so a
    completed session becomes a pending row in pending_calendar.jsonl exactly
    like a planned block does. A Claude session flushes the queue. Returns a
    short suffix for the toast, or "" when there is nothing to say.
    """
    start, end = data.get("started_at"), data.get("ended_at")
    if not (start and end):
        return ""                      # a live-clock checkout has no span to record
    pid = data.get("project", "")
    name = A.project_meta().get(pid, {}).get("name", pid)
    did = (data.get("did") or "").strip()
    # Title says the work happened; a planned block's title says what to start.
    summary = f"\u2713 {name}" + (f" \u2014 {did.splitlines()[0][:60]}" if did else "")
    ok, out = run_cli("queue_event.py", [
        "--summary", summary, "--start", start, "--end", end,
        "--kind", "done", "--commitment", pid, "--notes", did])
    return "\n" + (out if ok else f"(calendar queue failed: {out})")


def set_project_next(pid: str, text: str) -> tuple[bool, str]:
    path = AGENT / "projects" / f"{pid}.md"
    if not path.exists():
        return False, f"no state file for {pid}"
    body = path.read_text()
    pattern = re.compile(r"(\*\*Next step:\*\*)(.*?)(?=\n\*\*|\n##|\Z)", re.S)
    if not pattern.search(body):
        return False, "no '**Next step:**' section found"
    path.write_text(pattern.sub(lambda m: f"{m.group(1)} {text.strip()}\n", body, count=1))
    return True, "updated"


# ---------------------------------------------------------------- training

def build_train() -> dict:
    """State for the training view.

    Kept off /api/state on purpose: the board never needs the full exercise
    history, and this is only read when the view is actually open.
    """
    now = datetime.now(A.TZ)
    wk_start, wk_end = A.week_bounds(now)
    life = A.life()
    tmpl = A.workouts()
    last = W.last_numbers()

    def decorate(ex: dict) -> dict:
        """Hang last session's numbers on a template row, alternate included."""
        out = {"id": ex["id"], "name": ex.get("name", ex["id"]),
               "sets": ex.get("sets", 2), "unit": ex.get("unit") or "lb",
               "last": last.get(ex["id"])}
        if ex.get("or"):
            out["or"] = decorate(ex["or"])
        return out

    splits = [{"id": sp["id"], "name": sp.get("name", sp["id"]),
               "exercises": [decorate(e) for e in sp.get("exercises") or []]}
              for sp in tmpl.get("splits", []) if sp.get("id")]

    wk_life = [e for e in life
               if (t := A.parse_ts(e.get("ts"))) and wk_start <= t < wk_end]
    targets = {h["id"]: h for h in A.commitments().get("habits", [])}

    recent = []
    for e in [x for x in life if x.get("kind") in ("gym", "cardio")][-12:][::-1]:
        t = A.parse_ts(e.get("ts"))
        recent.append({
            "ts": e.get("ts"),
            "when": t.strftime("%a %m/%d") if t else "",
            "kind": e.get("kind"),
            "split": e.get("split"),
            "activity": e.get("activity"),
            "detail": e.get("detail", ""),
            "minutes": e.get("minutes"),
            "exercises": e.get("exercises") or [],
            "volume": W.volume(e.get("exercises") or []),
        })

    return {
        "now": now.isoformat(),
        "rotation": tmpl.get("rotation") or [],
        "splits": splits,
        "cardio": tmpl.get("cardio") or [],
        "next": A.next_split(life),
        "week_splits": [e.get("split") for e in wk_life
                        if e.get("kind") == "gym" and e.get("split")],
        "active": read_runtime().get("workout"),
        "recent": recent,
        "week": {
            k: {"count": len([e for e in wk_life if e.get("kind") == k]),
                "target": (targets.get(k) or {}).get("target_per_week", 0),
                "stretch": (targets.get(k) or {}).get("stretch")}
            for k in ("gym", "cardio")
        },
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            try:
                return self._send(200, build_state())
            except Exception as exc:  # surface parse errors in the UI
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
        if path == "/api/train":
            try:
                return self._send(200, build_train())
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
        if path in ("/", "/index.html"):
            html = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            return self.wfile.write(html)
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid JSON"})

        if path == "/api/checkout":
            args = ["--project", data["project"], "--tool", "claude-code",
                    "--did", data.get("did", "").strip() or "(no summary)",
                    "--next", data.get("next", "").strip()]
            for flag, key in (("--actual-minutes", "actual_minutes"),
                              ("--planned-minutes", "planned_minutes"),
                              ("--started-at", "started_at"),
                              ("--ended-at", "ended_at"),
                              ("--focus", "focus")):
                if data.get(key) not in (None, ""):
                    args += [flag, str(data[key])]
            if data.get("blockers"):
                args += ["--blockers", data["blockers"]]
            if data.get("block_id"):
                args += ["--block-id", data["block_id"]]
            ok, out = run_cli("log_session.py", args)
            if ok and data.get("next", "").strip():
                set_project_next(data["project"], data["next"])
            if ok:
                rt = read_runtime()
                rt.pop("active", None)
                write_runtime(rt)
                out += queue_done(data)
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/life":
            args = [data.get("kind", "other")]
            if data.get("detail"):
                args += ["--detail", data["detail"]]
            if data.get("minutes"):
                args += ["--minutes", str(data["minutes"])]
            if data.get("with"):
                args += ["--with", data["with"]]
            ok, out = run_cli("log_life.py", args)
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/project":
            op = data.get("op")
            if op == "add":
                args = ["add", (data.get("id") or "").strip(),
                        "--name", data.get("name", ""),
                        "--lane", data.get("lane", ""),
                        "--hours-min", str(data.get("hours_min", 0)),
                        "--hours-max", str(data.get("hours_max", 2)),
                        "--priority", data.get("priority", "medium")]
                if data.get("dir"):
                    args += ["--dir", data["dir"]]
                if data.get("flexible"):
                    args += ["--flexible"]
            elif op in ("archive", "restore"):
                args = [op, (data.get("id") or "").strip()]
            else:
                return self._send(400, {"ok": False, "message": f"unknown op {op!r}"})
            ok, out = run_cli("project.py", args)
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/next":
            ok, out = set_project_next(data["project"], data.get("next", ""))
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/task":
            op = data.get("op")
            if op == "add":
                title = (data.get("title") or "").strip()
                if not title:
                    return self._send(400, {"ok": False, "message": "a task needs a title"})
                args = ["add", title, "--project", data.get("project", "")]
                for flag, key in (("--est", "est"), ("--due", "due"),
                                  ("--first-action", "first_action"),
                                  ("--deadline", "deadline")):
                    if data.get(key):
                        args += [flag, str(data[key])]
            elif op in ("done", "reopen", "restore"):
                args = [op, data.get("id", "")]
            elif op == "update":
                args = ["set", data.get("id", "")]
                for flag, key in (("--title", "title"), ("--project", "project"),
                                  ("--est", "est"), ("--due", "due"),
                                  ("--first-action", "first_action"),
                                  ("--status", "status")):
                    if key in data:
                        args += [flag, "" if data[key] is None else str(data[key])]
            elif op == "delete":
                args = ["rm", data.get("id", "")]
            else:
                return self._send(400, {"ok": False, "message": f"unknown task op {op!r}"})
            ok, out = run_cli("task.py", args)
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/schedule":
            # Drag a task onto a day: place as many blocks as its estimate needs.
            task = next((t for t in A.read_jsonl(TASKS) if t["id"] == data.get("task")), None)
            if not task:
                return self._send(400, {"ok": False, "message": "no such task"})
            if not task.get("first_action"):
                return self._send(400, {"ok": False, "message":
                    "give the task a first action before scheduling it — a block "
                    "that says only \u201cwork on it\u201d is the one that gets skipped"})
            try:
                day = datetime.fromisoformat(data["date"]).replace(
                    hour=0, minute=0, second=0, microsecond=0, tzinfo=A.TZ)
            except (KeyError, ValueError, TypeError):
                return self._send(400, {"ok": False, "message": "unreadable date"})

            now = datetime.now(A.TZ)
            wanted = math.ceil((task.get("est_minutes") or BLOCK_MINUTES) / BLOCK_MINUTES)
            slots = free_slots(day, wanted, now)
            if not slots:
                return self._send(400, {"ok": False, "message":
                    f"no room on {day:%a %m/%d} — the day is full or already behind you"})

            name = A.project_meta().get(task["project"], {}).get("name", task["project"])
            before = {b["id"] for b in A.queued_blocks()}
            for start in slots:
                ok, out = run_cli("queue_event.py", [
                    "--summary", f"{name} — {task['title']}",
                    "--start", start.isoformat(timespec="seconds"),
                    "--minutes", str(BLOCK_MINUTES), "--kind", "block",
                    "--commitment", task["project"],
                    "--first-action", task["first_action"]])
                if not ok:
                    return self._send(400, {"ok": False, "message": out})
            for bid in [b["id"] for b in A.queued_blocks() if b["id"] not in before]:
                run_cli("task.py", ["set", task["id"], "--add-block", bid])

            times = ", ".join(f"{s:%H:%M}" for s in slots)
            short = f" ({wanted - len(slots)} still to place)" if len(slots) < wanted else ""
            return self._send(200, {"ok": True, "message":
                f"{day:%a} {times} — {len(slots)} block"
                f"{'s' if len(slots) > 1 else ''} queued{short}"})

        if path == "/api/inbox":
            name, data = data.get("name", ""), data.get("data", "")
            if Path(name).suffix.lower() not in INBOX_EXT:
                return self._send(400, {"ok": False,
                    "message": f"{Path(name).suffix or 'that file type'} isn\u2019t something /intake can read"})
            try:
                raw = base64.b64decode(data, validate=True)
            except Exception:
                return self._send(400, {"ok": False, "message": "the file didn\u2019t decode"})
            if len(raw) > MAX_UPLOAD:
                return self._send(400, {"ok": False, "message": "over the 40 MB limit"})
            try:
                INBOX.mkdir(parents=True, exist_ok=True)
                dest = free_name(name)
            except ValueError as exc:
                return self._send(400, {"ok": False, "message": str(exc)})
            dest.write_bytes(raw)
            return self._send(200, {"ok": True, "message": f"{dest.name} is in the inbox",
                                    "name": dest.name})

        if path == "/api/inbox/remove":
            target = inbox_path(data.get("name", ""))
            if target is None or not target.is_file():
                return self._send(400, {"ok": False, "message": "no such file in the inbox"})
            target.unlink()
            return self._send(200, {"ok": True, "message": f"removed {target.name}"})

        if path == "/api/workout":
            op = data.get("op")
            rt = read_runtime()
            act = rt.get("workout")

            if op == "start":
                split = data.get("split")
                if split not in A.split_meta():
                    return self._send(400, {"ok": False, "message": f"no split called {split!r}"})
                act = {"split": split,
                       "started": datetime.now(A.TZ).isoformat(timespec="seconds"),
                       "exercises": {}, "swaps": {}}
                write_runtime({**rt, "workout": act})
                return self._send(200, {"ok": True, "active": act})

            if op == "discard":
                rt.pop("workout", None)
                write_runtime(rt)
                return self._send(200, {"ok": True, "message": "workout discarded"})

            if not act:
                return self._send(400, {"ok": False, "message": "no workout in progress"})

            if op == "sets":
                # The page sends the whole exercise every edit rather than a
                # delta, so a dropped request can never leave a half-written set.
                eid = data.get("exercise")
                if eid not in A.exercise_names():
                    return self._send(400, {"ok": False, "message": f"unknown exercise {eid!r}"})
                rows = []
                for st in data.get("sets") or []:
                    reps = st.get("reps")
                    w = st.get("weight")
                    rows.append({"weight": None if w in (None, "") else float(w),
                                 "reps": None if reps in (None, "") else int(reps)})
                act["exercises"][eid] = {"unit": data.get("unit") or "lb", "sets": rows}
                write_runtime({**rt, "workout": act})
                return self._send(200, {"ok": True})

            if op == "swap":
                act.setdefault("swaps", {})[data.get("slot")] = data.get("exercise")
                write_runtime({**rt, "workout": act})
                return self._send(200, {"ok": True, "active": act})

            if op == "finish":
                started = A.parse_ts(act.get("started"))
                minutes = data.get("minutes")
                if minutes in (None, ""):
                    minutes = round((datetime.now(A.TZ) - started).total_seconds() / 60) \
                        if started else None
                # The page sends its own copy so a debounced save still in flight
                # can't be dropped between the last keystroke and Finish.
                src = data.get("exercises") or act.get("exercises", {})
                payload = {
                    "exercises": [{"id": eid, "unit": ex.get("unit"),
                                   "sets": [st for st in ex.get("sets") or [] if st.get("reps")]}
                                  for eid, ex in src.items()],
                    "minutes": int(minutes) if minutes else None,
                    "note": data.get("note", ""),
                }
                ok, out = run_cli("workout.py", ["log", act["split"], "--stdin-json"],
                                  stdin=json.dumps(payload))
                if ok:                       # only clear once it is safely on disk
                    rt.pop("workout", None)
                    write_runtime(rt)
                return self._send(200 if ok else 400, {"ok": ok, "message": out})

            return self._send(400, {"ok": False, "message": f"unknown op {op!r}"})

        if path == "/api/cardio":
            args = ["cardio", data.get("activity", "")]
            if data.get("minutes"):
                args += ["--minutes", str(int(data["minutes"]))]
            if data.get("note"):
                args += ["--note", data["note"]]
            ok, out = run_cli("workout.py", args)
            return self._send(200 if ok else 400, {"ok": ok, "message": out})

        if path == "/api/start":
            write_runtime({**read_runtime(), "active": {
                "project": data.get("project"),
                "block_id": data.get("block_id"),
                "label": data.get("label", ""),
                "first_action": data.get("first_action", ""),
                "started": datetime.now(A.TZ).isoformat(timespec="seconds"),
            }})
            return self._send(200, {"ok": True})

        if path == "/api/stop":
            rt = read_runtime()
            rt.pop("active", None)
            write_runtime(rt)
            return self._send(200, {"ok": True})

        self.send_error(404)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"dashboard → {url}   (Ctrl-C to stop)")
    if "--no-open" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
