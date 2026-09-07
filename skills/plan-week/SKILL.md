---
name: plan-week
description: Build the week — combine fixed calendar events, weekly time budgets, open tasks and deadlines, and learned focus patterns into a proposed schedule of 50-minute work blocks, each carrying a concrete first action. Use when the user says "plan my week", "what should this week look like", "make me a schedule", or on a scheduled weekly run.
---

# /plan-week — propose the week

## Inputs, in this order

1. `~/Documents/.agent/commitments.yaml` — budgets, envelope, per-day cap
2. **`task.py list --json`** — the open task table. This is the main source of
   block content: a task already carries a title, an estimate, and a first
   action, which is exactly what a block needs.
3. `~/Documents/.agent/deadlines.yaml` — everything `status: open`. A deadline
   with no task behind it is work nobody has broken down yet; say so.
4. `~/Documents/.agent/PROFILE.md` — which hours actually work (may be empty early)
5. **Fixed events** — `~/Documents/.agent/calendar.json`, refreshed by
   `bin/calendar_sync.py`. If it's stale, re-sync before planning. Say how old
   the data is.
6. `~/Documents/.agent/projects/*.md` — each project's `next`, for projects that
   have budget but no tasks yet

## Algorithm

1. **Lay down fixed events.** Classes, labs, standing meetings, anything the user
   put on their own calendar. These never move.
2. **Place deadline work first**, backward from each due date (see `/intake`).
   Deadlines outrank budgets.
3. **Fill remaining budgets by priority** — `high` before `medium` before `low`.
   Deep-work commitments (`allow_double_block: true`) get a contiguous pair in
   the largest open run available.
4. **Honour each commitment's `prefers` field.** `after_lecture` work goes near
   its class, while the material is fresh and the context switch is cheap;
   `night` work goes late; `deep_work` wants the longest uninterrupted run;
   `flexible` fills whatever is left.
5. **Respect the caps.** The envelope and `max_blocks_per_day` from
   `commitments.yaml`, 50-minute blocks with 10-minute gaps.
6. **Under-fill on purpose.** Leave at least one large open run untouched. An
   overfull week gets abandoned wholesale — that is the dominant failure mode,
   and it is worse than an under-used day.
7. **Write a first action into every block**, distinct per block. Take it from
   the task's `first_action` where a task drives the block, otherwise the
   project's `next`. Never repeat "work on X" four times.
8. **Split a task by its estimate** — `est_minutes / 50`, rounded up — and give
   each block a *different* opener describing that slice of the work. Attach
   every queued block back to its task:
   `task.py set <task-id> --add-block <block-id>` (this flips it to `scheduled`).
   A task with no `first_action` cannot be scheduled; ask for one instead of
   inventing it.

## Output

Present the week as a day-by-day table **before writing anything**:

```
FRI 9/12
  09:00-10:50  research (2×)   ↳ Run the comparison on 3 inputs, paste outputs
  13:00-13:50  Course 1        ↳ Re-derive the lecture-4 proof on paper
```

Then show the totals against budget:

```
research   3.3h / 3-4h  ✓
course1    1.7h / 1-2h  ✓
side       0h   / 1-2h  ✗ — squeezed by the Course 2 deadline Thursday
```

**Get explicit approval, then queue each block** via
`~/Documents/.agent/bin/queue_event.py`. Blocks land in
`pending_calendar.jsonl` for review rather than being written to a calendar.
Finally update `STATE.md` with the week.

## Rules

- **Show the whole week and get approval before writing any of it.** Autonomy is
  earned per task type; this one hasn't earned it.
- Never schedule habits (gym, cardio). Those are logged after the fact — see
  `/log`. A workout nobody committed to becomes a block they "failed."
- If the plan can't fit everything, say what didn't fit and why, rather than
  silently dropping the lowest-priority work.
