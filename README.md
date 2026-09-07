# Command

A local-first planning dashboard for people who work across too many projects at
once. It turns documents into deadlines, deadlines into tasks, and tasks into
50-minute blocks that each carry a concrete first action — because the cold
start is the bottleneck, not the work.

Runs entirely on your machine. Python standard library only, no build step, no
account, no telemetry. Your data never leaves the laptop.

<!-- Add a screenshot here: docs/screenshot.png -->

## What it does

- **A week view** where one cell is one hour. Logged work lights up, with
  brightness set by how focused you said you were. Planned blocks show as a
  dither, classes and other fixed events as their own reference rows.
- **A task list** in a slide-out drawer, and a **planner** where you drag a task
  onto a day and it places blocks around your existing commitments — respecting
  a daily cap, leaving breaks, and never scheduling into the past.
- **A live calendar feed.** Point it at a calendar's secret iCal address and it
  refreshes itself every 10 minutes.
- **An inbox** you drop a syllabus or spec into.
- **Session logging** — what changed, how focused you were, and the first action
  for next time.

Nothing is ever written to your calendar. Blocks are queued to a local file for
you to approve.

## Requirements

Python 3.11+. That's it.

## Setup

```bash
git clone https://github.com/A319K/dashboard.git ~/Documents/.agent
cd ~/Documents/.agent

cp examples/commitments.example.yaml commitments.yaml
cp examples/deadlines.example.yaml   deadlines.yaml

./bin/calendar_sync.py --demo    # optional: a sample week, to see it populated
./bin/dash
```

Then open http://127.0.0.1:7717/.

The `--demo` step fills the week view with a plausible sample timetable so the
UI isn't empty on first run. It's generated relative to the current week, so it
never goes stale, and the header labels it as sample data. Any real sync
replaces it.

Edit `commitments.yaml` to list your own projects. The `id` of each one is what
everything else keys off, and `lane` picks its colour.

### Live calendar (optional)

In Google Calendar: Settings → your calendar → Integrate calendar → **Secret
address in iCal format**. Then:

```bash
echo 'https://calendar.google.com/calendar/ical/.../basic.ics' > calendar_source.txt
```

The dashboard re-fetches every 10 minutes. Add an event on your phone and it
appears — no session, no API key.

One URL per line merges several calendars. Prefix a line with a label and that
feed's events take the label as their kind instead of being guessed from the
title:

```
https://calendar.google.com/calendar/ical/.../basic.ics
plan  https://calendar.google.com/calendar/ical/.../basic.ics
```

> `calendar_source.txt` is a credential — anyone holding that URL can read the
> whole calendar without logging in. It is gitignored. Don't commit it.

## The CLIs

The dashboard shells out to these, so validation lives in one place. They work
standalone and any tool — including another AI agent — can drive them.

```bash
bin/task.py add "Vivado lab 2 setup" --project cs440 --est 2h --due 2026-09-12 \
    --first-action "open lab2.pdf and do the constraint file only"
bin/task.py list
bin/task.py done cs440-vivado-lab-2-setup
bin/task.py restore cs440-vivado-lab-2-setup   # deletes are recoverable

bin/log_session.py --project cs440 --focus 4 --actual-minutes 50 \
    --did "wrote the constraint file" --next "map the pins"
bin/log_life.py gym --detail "push day"

bin/calendar_sync.py          # refresh from the iCal feed
bin/queue_event.py --list     # blocks waiting for approval
bin/review.py                 # weekly retrospective
```

## Layout

```
bin/          the CLIs — the only things that write state
dashboard/    server.py + index.html, the whole UI
examples/     starter configs to copy
projects/     one rolling state file per project (yours, gitignored)
log/          append-only session and life history (yours, gitignored)
```

Your actual data — `commitments.yaml`, `tasks.jsonl`, `calendar.json`,
`projects/*.md`, `log/*.jsonl` — is gitignored by design. This repo is the
system; your week stays on your machine.

## Design notes

**A block without a first action is a defect.** The system refuses to schedule a
task that has no concrete opener. "Work on the homework" is the block that gets
skipped; "open lab2.pdf and do the constraint file only" is the one that gets
started.

**Under-schedule on purpose.** An overfull week gets abandoned wholesale, which
is a worse failure than an under-used day. Hence the daily cap.

**Nothing is destructive.** Deleted tasks are recoverable, calendar writes are
queued for approval rather than executed, and the tools only ever append to the
logs.

## Using it with Claude Code

The repo is designed to be driven by an agent as well as by hand. The
`bin/` CLIs are the interface: they validate input, so an agent can't corrupt
state by writing files directly. If you use Claude Code, point a skill at
`bin/task.py` and `bin/log_session.py` and it can plan and check out your week.

## License

MIT — see [LICENSE](LICENSE). Fork it and make it yours.
