# Skills

Six workflows that turn the CLIs into a system. They're written for
[Claude Code](https://claude.com/claude-code) but they're plain Markdown — any
agent that can read instructions and run shell commands can follow them.

| Skill | What it does |
|---|---|
| `/checkin` | Loads state at the start of a session: where things stood, the next step, blockers, deadlines |
| `/checkout` | Records the session, ticks off finished tasks, updates the project's rolling state |
| `/intake` | A document becomes deadlines, tasks, and scheduled blocks |
| `/plan-week` | Tasks and budgets become a proposed week, for approval |
| `/review` | Finds where focus actually happens, writes it to `PROFILE.md` so next week adjusts |
| `/log-life` | Records habits and social plans, reports streaks against targets |

## Install

```bash
cp -r skills/* ~/.claude/skills/
```

Restart Claude Code and they're available as `/checkin`, `/intake`, and so on.

To scope them to this workspace instead of globally, copy them to
`.claude/skills/` inside the directory you work from.

## Make them yours

These ship deliberately generic — `course1`, `research`, `side-project` — so they
work before you've configured anything. They get better as you make them
specific:

- **Name your actual projects.** Once `commitments.yaml` lists your real
  commitments, edit the skills to reference them by name. `/intake` classifying a
  PDF is much faster when it knows your course numbers are the header of every
  handout.
- **Record what your tooling costs.** If a project needs a slow IDE or a dataset
  download before real work starts, say so in `/intake` — the estimates get
  honest.
- **Add your own hard rules.** Anything you'd otherwise re-explain every session:
  which repos need a push done by hand, which APIs are rate-limited and want a
  mock in testing, which machine holds which secrets.
- **Let `/review` do it for you.** Step 7 folds durable findings back into
  `CLAUDE.md` every week. That is the mechanism by which a generic system becomes
  yours — it happens there, or it doesn't happen.

The prose matters more than it looks. "A `next` of *continue working on it* is a
failed checkout" is doing real work in `/checkout`; delete it and the quality of
your logs degrades within a week.
