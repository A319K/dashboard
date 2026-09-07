---
name: review
description: Weekly retrospective — aggregate the session and life logs, find where focus actually happens, and write the findings into PROFILE.md so next week's plan adjusts. Use when the user says "review my week", "how did this week go", "what did I get done", or on a scheduled weekly run.
---

# /review — learn from the week, then adjust

This is the recursive loop. Without it the schedule never improves.

## Steps

### 1. Aggregate
```bash
python3 ~/Documents/.agent/bin/review.py --days 7
```
Gives time per project vs. budget, focus by day × hour, planned-vs-actual drift,
unplanned sessions, blockers, and habit counts.

### 2. Compare plan to reality
Read `pending_calendar.jsonl` (or the plan calendar, once writes are live) for
what was *planned*, and `sessions.jsonl` for what *happened*. Compute:
- **Completion rate** — planned blocks that produced a session
- **Slippage** — which projects consistently didn't get touched
- **Displacement** — where unplanned work happened instead

### 3. Find the patterns
Look specifically for:
- **Hours with consistently high focus** → move more work there next week
- **Hours with consistently low focus or no-shows** → stop scheduling there
- **Unplanned sessions clustering at an hour that was never planned** → the
  calendar should move to meet the user rather than fight them. If they keep
  working at 22:00 on their own and it goes well, schedule there.
- **Duration drift** — if a project's blocks always run 85 minutes, 50-minute
  blocks are a lie for that project. Change the block size.
- **Budget mismatch** — a commitment that never hits its floor, or always blows
  its ceiling, has the wrong budget. Propose the change.

**Require three observations before acting on a pattern.** Two data points are
noise, and a schedule that thrashes weekly is worse than a static one.

### 4. Write findings into `PROFILE.md`
Update the observed sections with the tables and a short prose finding. Every
claim must trace to a number. Append to **Adjustments made** whenever the
schedule changes because of an observation, with the evidence beside it.

### 5. Propose the changes
Concretely:
- budget changes in `commitments.yaml`
- placement changes for `/plan-week`
- `max_blocks_per_day` up or down based on completion rate

Get approval before editing `commitments.yaml`.

### 6. Update `STATE.md` and roll forward
Refresh the week header, project states, habit counts, and open deadlines. Carry
unfinished deadline work into next week explicitly.

### 7. Improve the workspace `CLAUDE.md`
If the week surfaced anything durable about how the user works, a new hard
constraint, or a correction to the map, fold it in. This is where a generic
system becomes specific to one person — it happens here, every week, or it
doesn't happen.

## Rules

- **Report the numbers before the interpretation.** Then interpret.
- **A bad week is data, not a verdict.** If completion was 30%, the finding is
  "the plan was wrong about something" — over-scheduled, wrong hours, blocks too
  long, first actions too vague. Diagnose the plan, not the person. Never
  editorialize about discipline or motivation.
- Habit shortfalls get one factual line: the count, the target, the open windows.
- Don't rewrite `PROFILE.md` wholesale each week. Append and refine — the history
  of what was believed and when is itself useful.
