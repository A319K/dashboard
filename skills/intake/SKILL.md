---
name: intake
description: Process a document the user hands over — read it, file it into the right project directory, extract deadlines into .agent/deadlines.yaml, turn each deliverable into a task, and schedule work blocks backward from each due date. Use when they share a PDF, syllabus, assignment, problem set, or spec, drop a file in .agent/inbox/, or say "here's my syllabus", "take this", "file this".
---

# /intake — turn a document into filed work and scheduled blocks

The highest-value loop in the system. Work that isn't blocked out in advance is
work that gets started late, so a document must become *scheduled blocks with
first actions* — not a summary.

## Steps

### 1. Read it
Actually read the file. PDFs via the Read tool's `pages`. Never work from the
filename.

### 2. Classify
Which commitment does it belong to? Match against `commitments.yaml`. Course
numbers and project names are usually explicit in a header.
**If ambiguous, ask — a misfiled document is worse than a slow one.**

### 3. File it
Move it to the commitment's `dir`. Create subdirectories that match what's
already there rather than inventing a scheme.

```bash
mv "<source>" ~/Documents/<project-dir>/hw1.pdf
```

Report the destination path. Never delete the original — move it.

### 4. Extract deadlines
Every date with a deliverable attached. For each, append to
`~/Documents/.agent/deadlines.yaml`:

```yaml
- id: course1-hw1
  commitment: course1
  title: "Homework 1 — <topic>"
  due: "2026-09-15T23:59:00-04:00"
  source: "<project-dir>/hw1.pdf"
  est_hours: 3
  status: open
  blocks: []
```

- `est_hours` — your honest estimate of *this user's* time, not a generic one.
  Weight by problem count and whether it needs tooling (a specific IDE, LaTeX, a
  dataset) that costs setup time before any real work starts.
- A syllabus yields *many* deadlines at once. Get them all; that's the point.
- Times default to 23:59 local when only a date is given. Say that you assumed it.

### 5. Turn each deliverable into a task
A deadline is a date; a task is the work. The dashboard, `/plan-week` and
`/checkout` all read the task table, so a deadline with no task behind it shows
up as work nobody has broken down.

```bash
python3 ~/Documents/.agent/bin/task.py add "HW1 — <topic>" \
  --project course1 --est 3h --due 2026-09-15 --deadline course1-hw1 \
  --first-action "open hw1.pdf and write out problem 1's setup only"
```

- One task per deliverable, not per document. A syllabus with nine assignments
  yields nine tasks.
- `--first-action` is required in practice: a task without one can't be
  scheduled from the planner, and a block that says only "work on HW1" is the
  one that gets skipped. Write the opener you'd want to read cold.
- Split anything over ~4h into tasks that are separately startable, so the
  estimate stays honest and progress is visible partway through.

### 6. Schedule backward from the due date
This is the part that matters.

- Split `est_hours` into 50-minute blocks.
- Place the **last** block no later than the day before the due date. Never the
  due date itself.
- Spread the rest backward across open windows, respecting: the envelope in
  `commitments.yaml`, `max_blocks_per_day`, and existing fixed events from
  `calendar.json`.
- Prefer hours `PROFILE.md` says work. Early on there's no data — prefer the
  largest uninterrupted runs in the week, and say that's why you chose them.
- **Write a distinct first action into every block.** Not "work on HW1" ×4, but
  "read problems 1-3 and write the setup for #1", then "solve #1 and #2". Each
  block needs its own cold-start opener.

Queue each one:

```bash
python3 ~/Documents/.agent/bin/queue_event.py \
  --summary "Course 1 — HW1" --start "2026-09-11T15:00:00-04:00" --minutes 50 \
  --kind block --commitment course1 \
  --first-action "Read problems 1-3, write the setup for #1 only"
```

Also queue a `--kind deadline` marker on the due date itself, and attach each
queued block back to its task so the dashboard shows it as scheduled:

```bash
python3 ~/Documents/.agent/bin/task.py set <task-id> --add-block <block-id>
```

### 7. Report
Short. Where it was filed, the deadlines found, the blocks proposed with days of
runway. Then ask for approval before considering it settled.

## Rules

- **Backward from the deadline, never forward from today.** Forward scheduling
  is what produces a last-minute scramble.
- If a deadline lands inside 48 hours, say so first, before anything else.
- If `est_hours` would need more blocks than the remaining days allow, flag the
  crunch explicitly and propose what gives — the `flexible: true` commitments
  yield first, lowest priority before highest. Announce the trade; never make it
  silently.
- Update the relevant `.agent/projects/<id>.md` with the new deadline.
- **Files arrive two ways.** The user may hand you a path directly, or drop files
  on the dashboard's Inbox, which writes them to `.agent/inbox/`. Check there
  when they say "I dropped something in" — and move files out of the inbox as
  you file them, so what's left is always what's still unprocessed.
