---
name: checkout
description: End a work session by recording it — appends to .agent/log/sessions.jsonl, ticks off finished tasks, and rewrites the project's rolling state file. Use when the user says "checkout", "check out", "log this session", "wrap up", "done for now", or when a work session is ending.
---

# /checkout — record the session

This is the core handoff of the whole system. A session that did real work and
didn't check out is invisible to next week's plan.

## Steps

1. **Identify the project id** from the working directory via
   `~/Documents/.agent/commitments.yaml`.

2. **Draft the record yourself from what actually happened this session** — don't
   interrogate the user for things you already know. You know what changed, what
   broke, and what's left.

3. **Ask exactly two things** (keep it to one short message):
   - *"Focus this session, 1-5?"* — 1 = scattered/couldn't start, 5 = locked in.
   - *"Anything I got wrong in this summary?"* — show the drafted `did` / `next`.

   That's it. Two questions. This runs at the end of every session, so friction
   here kills the whole system.

4. **Append one line** to `~/Documents/.agent/log/sessions.jsonl`:

   ```bash
   python3 ~/Documents/.agent/bin/log_session.py \
     --project <id> --tool claude-code \
     --planned-minutes 50 --actual-minutes 85 --focus 4 \
     --did "..." --next "..." --blockers "..."
   ```

   Field meanings:
   - `planned_minutes` — the scheduled block length, or `null` if unplanned
   - `actual_minutes` — real elapsed time. Estimate honestly; over-reporting
     poisons the duration model
   - `focus` — the 1-5 rating. **This single field powers the learning loop.**
   - `did` — what changed, concretely. Not "worked on X."
   - `next` — the first action for next time, specific enough to start cold
   - `blockers` — comma-separated, or empty

5. **Tick off any task the session finished.** Check the project's open tasks
   against what actually got done, and close the ones that are complete:

   ```bash
   python3 ~/Documents/.agent/bin/task.py list --project <id>
   python3 ~/Documents/.agent/bin/task.py done <task-id>
   ```

   Only close what's finished — a task half-done stays open with its
   `--first-action` updated to the *new* opener, so the next block starts where
   this one stopped:

   ```bash
   python3 ~/Documents/.agent/bin/task.py set <task-id> \
     --first-action "pick up at step 3 — the config is written, the wiring isn't"
   ```

   If the session surfaced new work, add it now while you still remember it.
   Confirm closures in the same short message as the two questions above rather
   than asking separately.

6. **Rewrite `~/Documents/.agent/projects/<id>.md`**: update `last_touched`,
   `last_session`, **Status**, **Next step**, **Blockers**. Keep the existing
   structure and any hard-rules section intact.

7. **Follow the project's own logging convention too.** If a repo keeps its own
   append-only log — a `docs/agent-log.md`, a `results_log.jsonl`, a session log
   at the bottom of its `CLAUDE.md` — writing to it is not optional. That log is
   how the next session in *that* repo knows what happened. Check the project's
   `CLAUDE.md` for the convention.

8. **If anything changed the map** — a new constraint, a project going active or
   dormant, a correction to how the user works — update the workspace
   `CLAUDE.md` or `.agent/PROFILE.md` in the same session. This is the recursive
   part; it only works if it happens at the moment of discovery.

## Rules

- **A `next` of "continue working on it" is a failed checkout.** It must name a
  concrete first action, because it becomes the opening line of a scheduled
  block and the cold start is the hard part.
- Write the record even for a bad session. A 20-minute block with focus 2 is the
  most valuable kind of data the system collects — it's how the schedule learns
  which hours don't work.
- Never fabricate `actual_minutes`. If genuinely unknown, pass `null`.
