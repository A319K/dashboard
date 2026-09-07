---
name: log-life
description: Log a gym session, cardio, meal, or social plan to the life log, and report habit streaks against weekly targets. Use whenever the user mentions working out, doing cardio, "dinner with X", "lunch with X", or asks how their consistency looks this week.
---

# /log — record a life event

Habits and social plans are **logged, not scheduled**. The user reports after
the fact (or names a time for a meal), the system records and tracks frequency
against target. Never put speculative gym blocks on a calendar — a block nobody
committed to becomes a block they "failed."

## Usage

```bash
python3 ~/Documents/.agent/bin/log_life.py gym    --detail "push day" --minutes 75
python3 ~/Documents/.agent/bin/log_life.py cardio --detail "3mi run"  --minutes 28
python3 ~/Documents/.agent/bin/log_life.py meal   --detail "dinner" --with "a friend" \
    --when "2026-09-09T19:00:00-04:00"
python3 ~/Documents/.agent/bin/log_life.py social --detail "..."
```

Kinds: `gym`, `cardio`, `meal`, `social`, `sleep`, `other`.

## Behavior

1. **Parse loosely.** "hit legs today", "went for a 3 mile run", "dinner with
   Sam at 7" should all just work. Infer `kind`, `detail`, `with`, and `when`.
   Don't interrogate — if minutes weren't mentioned, leave them null.

2. **A meal or social event with a stated time also gets a calendar event.** If
   calendar writes are still deferred in this workspace, queue it instead — see
   `queue_event.py` and the calendar notes in `CLAUDE.md`.

3. **Report the streak** after logging, in one line:

   ```
   logged: gym — push day. 3rd gym session this week (target 4-5). Cardio 1/2.
   ```

   Targets live in `commitments.yaml` under `habits`. Count the current week
   Monday–Sunday from `life.jsonl`.

4. **If it's late in the week and a count is below target**, say so plainly and
   once, naming the open windows. Then drop it — no nagging, no second mention.

## Rules

- Never guess at a workout that wasn't reported. Missing data is missing data.
- Never moralize about a missed target. Report the number and move on.
