# Command

A local-first planning dashboard for people who work across too many projects at
once. It turns documents into deadlines, deadlines into tasks, and tasks into
50-minute blocks that each carry a concrete first action — because the cold
start is the bottleneck, not the work.

Runs entirely on your machine. Python standard library only, no build step, no
account, no telemetry. Your data never leaves the laptop.

<!-- Add a screenshot here: docs/screenshot.png -->

## What it does

- **A week view** where one cell is one hour. Logged work lights up across the
  hours it actually ran. Planned blocks show as a dither, classes and other
  fixed events as their own reference rows.
- **A task list** in a slide-out drawer, and a **planner** where you drag a task
  onto a day and it places blocks around your existing commitments — respecting
  a daily cap, leaving breaks, and never scheduling into the past.
- **A live calendar feed.** Point it at a calendar's secret iCal address and it
  refreshes itself every 10 minutes.
- **An inbox** you drop a syllabus or spec into.
- **Session logging** — a day and a start/end time, what changed, and the first
  action for next time. Log it now or backdate it; a session is a span, so the
  week view puts it where the work happened.

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
cp examples/workouts.example.yaml    workouts.yaml

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

### Training

`workouts.yaml` holds your splits, the order you cycle them in, and the cardio
you actually do. Edit it and reload — nothing about a routine is hardcoded in
the UI. The training view lives at `#train`, or through the gym card under
Streaks.

It is built around one comparison: last session's numbers for each exercise sit
beside today's empty boxes, so the weight you are chasing is already in front of
you. Beat it and the box marks itself. Which split comes up next is derived from
the last one you logged, so skipping a day shifts the rotation rather than
leaving you behind it.

A workout is stored as an ordinary `gym` entry in `log/life.jsonl` with the
exercises attached, so the streak pips on the board count it without knowing
anything about sets and reps.

### A private history for your state (optional, recommended)

Everything this repo ignores — your projects, logs, tasks, config — has no
version history by default. One mistyped checkout overwrites a project's next
step with no way back. `bin/state` fixes that with a second git dir, kept outside
the synced folder, tracking exactly what this repo omits:

```bash
git init --bare ~/.agent-state.git -b main
git --git-dir=~/.agent-state.git config core.worktree ~/Documents/.agent
git --git-dir=~/.agent-state.git config core.bare false
./bin/state add -f STATE.md PROFILE.md commitments.yaml workouts.yaml \
    deadlines.yaml tasks.jsonl calendar.json projects/*.md log/*.jsonl
./bin/state save "initial"
```

Then `state log`, `state diff`, and `state restore <path> [ref]` to put a file
back. The dashboard commits automatically after each write (debounced to two
minutes), so history accrues without you remembering. Give it no remote — the
whole point is that it stays on your machine.

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

bin/log_session.py --project cs440 \
    --started-at 2026-09-06T15:00 --ended-at 2026-09-06T17:00 \
    --did "wrote the constraint file" --next "map the pins"
bin/log_life.py gym --detail "push day"

bin/workout.py next                       # which split is up
bin/workout.py plan push                  # the split, with last time's numbers
bin/workout.py log push --set bench:135x8 --set bench:135x7 --minutes 60
bin/workout.py cardio run --minutes 30
bin/workout.py history --exercise bench   # one lift's progression

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

Your actual data — `commitments.yaml`, `workouts.yaml`, `tasks.jsonl`, `calendar.json`,
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

The CLIs are the interface: they validate input, so an agent can't corrupt state
by writing files directly. `skills/` ships six workflows that turn them into a
system:

```bash
cp -r skills/* ~/.claude/skills/
cp CLAUDE.md.example ~/Documents/CLAUDE.md   # then edit it
```

| Skill | What it does |
|---|---|
| `/checkin` | Loads state at the start of a session — next step, blockers, deadlines |
| `/checkout` | Records the session, ticks off finished tasks, updates project state |
| `/intake` | A document becomes deadlines, tasks, and scheduled blocks |
| `/plan-week` | Tasks and budgets become a proposed week, for approval |
| `/review` | Finds which hours you actually work, so next week's plan adjusts |
| `/log-life` | Records habits and social plans, reports streaks |

They ship generic on purpose — `course1`, `research`, `side-project` — so they
work before you've configured anything, and get better as you make them specific
to your own courses and projects. See [skills/README.md](skills/README.md).

Setting up your calendar, filling in `commitments.yaml`, and adapting the skills
are all things you can just ask your own Claude to do once the repo is cloned.

## License

MIT — see [LICENSE](LICENSE). Fork it and make it yours.
