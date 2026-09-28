---
name: handoff
description: End-of-session handoff for a project with an agent-brain (a .agent-brain folder in the project or above). Updates the project's STATE.md snapshot and its card board with what this session changed, checks size limits and saves to the brain's local git, so the next session starts from the latest state. Use for /handoff, "wrap up", "save progress", or before ending meaningful work in such a project.
---

# /handoff

`$BRAIN_TOOL` = the `Tool:` command printed in this session's agent-brain context
(e.g. `python ".../tools/brain.py"`). `brain.py where` prints the brain directory.
Everything stays in the project's `.agent-brain/`; nothing is pushed anywhere.

## 1. Find the brain
`$BRAIN_TOOL where` from the working folder. None → tell the user the project has no brain
and offer `/onboard-project`; stop.

## 2. Update `STATE.md` (edit in place)
It is a SNAPSHOT of now, never an append log; its git history is the log
(`$BRAIN_TOOL history`). Keep the section headings. From THIS session only:
- Finished items → **Recently done** (with commit/Jira/card evidence); when full, drop the
  oldest (they remain in the closed card and in history).
- **Now / Blocked / Next up** must be true as of now; every open item cites evidence.
- New lasting lessons → **Standing rules & traps**; replace the weakest when full.
- Update `_Last consolidated:`.
Limits (enforced by `check`): total ≤ 120 KB; Goal 6 KB/15 · Now 18 KB/25 · Blocked 12 KB/15 ·
Next up 12 KB/20 · Open defects 18 KB/40 · Recently done 18 KB/40 · Standing rules 12 KB/30 ·
Stale 10 KB/25 · Where things live 10 KB/40. Only Now, Blocked, Next up and Standing rules
load at session start (~10 KB), so keep those four tight and most important first.
Long detail goes to cards or topic memory files, linked under **Where things live**.
**Never write secrets** (passwords, PINs, tokens, keys). If the project uses an alias map
(`aliases.json`), keep writing hosts as `<aliases>`.

## 3. Update the cards
- Work finished → `$BRAIN_TOOL card-status N done` + `$BRAIN_TOOL card-note N "<what, evidence>"`.
- In progress / blocked → `card-status N doing|blocked` + a note: what was done, current
  state, exact next step, evidence.
- New open work → `$BRAIN_TOOL card-new "<title>" "<body>" <kind> <status> [JIRA]`
  (kind: bug|feature|investigation|debt|infra).

## 4. Save
`$BRAIN_TOOL save "handoff: <one line>"`: checks the size limits, rebuilds BOARD.md + BOARD.html and
commits to the brain's local git. If the check fails, shorten STATE.md; never bypass it.

## 5. Report
Three lines: what changed in state, cards moved/created, the save commit.
