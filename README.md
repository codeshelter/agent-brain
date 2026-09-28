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

## MCP servers (Jira, Redmine, Nexus)

The plugin registers four MCP servers (`mcpServers` in `.claude-plugin/plugin.json`, so the repo folder itself is not read as a project MCP config); their tools appear as
`mcp__plugin_agent-brain_<server>__<tool>`.

| Server | Source | Needs |
|---|---|---|
| `jira-onprem` | PyPI `mcp-atlassian` (via `uvx`) | Jira URL + PAT |
| `jira-portfolio` | `mcp/jira_portfolio_mcp.py` (Advanced Roadmaps / Portfolio) | Jira URL + PAT |
| `redmine` | `mcp/redmine_mcp.py` | Redmine URL + API key |
| `nexus` | `mcp/nexus_mcp.py` + `mcp/nexus/` (Nexus 3 REST, ~90 tools) | Nexus URL + user + password |

Credentials are plugin settings, never files: run `/plugin configure agent-brain`
(secrets go to the OS keychain). Requires `uv`/`uvx` on PATH. TLS verification is on;
`*_CA_BUNDLE` / `*_SSL_VERIFY` env overrides exist in the sources for exceptional cases.

## A project brain (`<project root>/.agent-brain/`)

| File | Purpose |
|---|---|
| `project.json` | id and title |
| `STATE.md` | Snapshot of "now" (rewritten, not a log). Max 120 KB with per-section caps; only Now / Blocked / Next up / Standing rules load at session start. |
| `cards/NNN-*.md` | One task card each: status, kind, jira, body, dated log |
| `BOARD.md` | Kanban view generated from the cards (loaded into sessions) |
| `BOARD.html` | Same board as one self-contained HTML5 page for Chrome/Edge: columns by status, search, kind filters, click a card for its body and log. Offline, no external resources. `brain.py board-open` opens it. |
| `aliases.json` | Optional `<alias>` → real host map, shown at session start |
| `.git/` | Local-only history (`brain.py history`); never pushed by the tool |

A folder uses the nearest `.agent-brain` found walking up. **Only trusted brains are loaded**
(`~/.claude/agent-brain-trusted.json`, outside any repo): `init` and `link` trust the brain they
create; a brain that arrives some other way (e.g. inside a cloned repo) is ignored until you
review it and run `brain.py trust <path>`. `check`/`save` refuse secrets (tokens, keys,
passwords) in STATE.md and cards. Folders outside the root get a
pointer file via `brain.py link <folder> <root>/.agent-brain`. `init` adds `/.agent-brain/`
to the project repo's `.git/info/exclude`; commit it to the project repo only if you choose to.

## Plugin contents

| Path | What |
|---|---|
| `hooks/hooks.json` | SessionStart: injects the always-on rules, and the project's brain if there is one |
| `skills/handoff`, `skills/onboard-project` | The two workflows |
| `rules/karpathy-guidelines.md` | Always on in every session |
| `rules/git-commits.md` | Always on: pure human commit/merge/PR messages, **no AI footer anywhere** |
| `rules/jira.md` | Rule book for creating, commenting on and closing Jira issues |
| `rules/enduser-guide.md` | Rule book for customer-facing guides (listed at session start) |
| `templates/STATE.md` | Section skeleton for a new brain |
| `tools/brain.py` | `where, init, link, trust, session-start, check, save, history, board, board-open, card-new, card-status, card-note, seed-cards, check-repo` (stdlib only) |
| `mcp/` | Source of the MCP servers (declared in plugin.json) |
| `tools/board_html.py` | Renders BOARD.html (stdlib only) |
| `tools/commit-msg` | Git hook that rejects AI/agent footers; copy into any repo's `.git/hooks/` |
| `tools/pre-commit` | `check-repo`: blocks project data, internal hosts/IPs and secrets in this repo |
