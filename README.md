# agent-brain

A Claude Code plugin that gives every project a **brain**: the project's current state and
task board, loaded automatically at the start of every session in any of the project's
folders, so new sessions and tasks continue where the last one stopped.

This repo holds **only the plugin**. Each project's brain lives in its own folder,
`<project root>/.agent-brain/`, on the machine where the project lives.

## Install on a machine

```bash
gh auth login                                    # once, if this repo is private
```
In Claude Code:
```
/plugin marketplace add codeshelter/agent-brain
/plugin install agent-brain@agent-brain
```
Requires Python 3 on PATH. Restart Claude Code after installing.

## Use

| Situation | Do |
|---|---|
| Project already has a brain | Just start Claude Code in any of its folders. The state and board load automatically. |
| Existing project, no brain yet | `/onboard-project <name>`: finds its folders and history, creates the brain, consolidates state and cards, shows it for review. |
| Brand-new project | `/onboard-project <name>` and give the goal + first steps. |
| End of meaningful work | `/handoff`: updates state and cards, saves to the brain's local git. |

## A project brain (`<project root>/.agent-brain/`)

| File | Purpose |
|---|---|
| `project.json` | id and title |
| `STATE.md` | Snapshot of "now" (rewritten, not a log). Max 120 KB with per-section caps; only Now / Blocked / Next up / Standing rules load at session start. |
| `cards/NNN-*.md` | One task card each: status, kind, jira, body, dated log |
| `BOARD.md` | Kanban view generated from the cards |
| `aliases.json` | Optional `<alias>` → real host map, shown at session start |
| `.git/` | Local-only history (`brain.py history`); never pushed by the tool |

A folder uses the nearest `.agent-brain` found walking up. Folders outside the root get a
pointer file via `brain.py link <folder> <root>/.agent-brain`. `init` adds `/.agent-brain/`
to the project repo's `.git/info/exclude`; commit it to the project repo only if you choose to.

## Plugin contents

| Path | What |
|---|---|
| `hooks/hooks.json` | SessionStart: injects the always-on rules, and the project's brain if there is one |
| `skills/handoff`, `skills/onboard-project` | The two workflows |
| `rules/karpathy-guidelines.md` | Always on in every session |
| `rules/enduser-guide.md` | Rule book for customer-facing guides (listed at session start) |
| `templates/STATE.md` | Section skeleton for a new brain |
| `tools/brain.py` | `where, init, link, session-start, check, save, history, board, card-new, card-status, card-note, seed-cards, check-repo` (stdlib only) |
| `tools/pre-commit` | `check-repo`: blocks project data, internal hosts/IPs and secrets in this repo |
