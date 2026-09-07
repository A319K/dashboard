---
name: checkin
description: Load workspace state at the start of a work session — the current week, the project's rolling status, and its recent session history. Use when starting work in any tracked project, when the user says "check in", "where were we", "what's the state", or when a session begins in a directory that has a matching .agent/projects/ entry.
---

# /checkin — start a work session

Loads state so the session starts knowing where things stood. Read-only; it
never modifies anything.

## Steps

1. **Identify the project.** Map the working directory to a project id using
   `~/Documents/.agent/commitments.yaml` (the `dir:` field). If the cwd is the
   workspace root itself, this is a top-level session — read `STATE.md` and stop
   there.

2. **Read, in this order:**
   - `~/Documents/.agent/STATE.md` — the current week
   - `~/Documents/.agent/projects/<id>.md` — rolling status, next step, blockers
   - the last 3 sessions for this project:
     ```bash
     grep '"project": *"<id>"' ~/Documents/.agent/log/sessions.jsonl | tail -3
     ```
   - any deadlines for it:
     ```bash
     grep -A6 "commitment: <id>" ~/Documents/.agent/deadlines.yaml
     ```
   - open tasks:
     ```bash
     python3 ~/Documents/.agent/bin/task.py list --project <id>
     ```
   - the project's own `CLAUDE.md` / `AGENTS.md` — always the authority for how
     to work there

3. **Report back in under 10 lines:**
   - where things stand (one line)
   - the recorded **next step** — quote it verbatim, it's the cold-start opener
   - open blockers
   - any deadline inside 10 days, with days remaining
   - if a planned block exists for right now, name it and its first action

4. **Note the start time.** `/checkout` needs it to compute actual minutes. Say
   the time out loud so it survives context compaction.

## Rules

- **Never invent state.** If `next` is unset, say so and ask — don't infer a next
  step by reading the code.
- If `.agent/projects/<id>.md` doesn't exist, offer to create it, then proceed.
- Don't summarize the whole codebase. This is a status load, not an exploration.
