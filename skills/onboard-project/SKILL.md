---
name: onboard-project
description: Give a project an agent-brain so every session in any of its folders starts with its current state and card board. Finds the project's folders and history (Claude memories, .remember, progress/roadmap files, git, Jira), creates <project root>/.agent-brain, links outlying folders, consolidates STATE.md and cards, and shows the result for review. Use for "/onboard-project <name>", "add <project> to agent-brain", or a brand-new project.
---

# /onboard-project <name>

`$BRAIN_TOOL` = the `Tool:` command printed in this session's agent-brain context.
The brain lives in the project's own folder; nothing is published anywhere.

## 1. Discover the footprint (read-only)
Search the work roots on this machine (ask if unsure; here: `C:\CI_CD`, `C:\Projects-IDEMIA`):
- **Folders** of the project incl. copies, variants and `.claude/worktrees`.
- **Claude memory dirs** in `~/.claude/projects/` whose names encode those paths
  (count memory files and session `.jsonl`).
- `.remember/`, `CLAUDE.md`, `.superpowers/sdd/**/progress.md`, `docs/roadmap.md`,
  `CHANGELOG.md`, git repos (branch + last commit date; **never print remote URLs**, they
  may hold credentials), Jira keys cited in memories.
- Existing brain? `$BRAIN_TOOL where <folder>`.

## 2. Confirm with the user (AskUserQuestion)
Show the folders and their history. Ask: project id (short, lowercase), title, the
**root** folder (the common parent that should hold `.agent-brain/`), and which outlying
folders to link. Brand-new project: ask for goal and first next steps; skip step 4.

## 3. Create
- `$BRAIN_TOOL init <id> "<title>" <root>`: creates `<root>/.agent-brain` (template
  STATE.md, empty board, local git; excluded from the project's own git via info/exclude).
- For each folder outside the root: `$BRAIN_TOOL link <folder> <root>/.agent-brain`.

## 4. Consolidate (one general-purpose agent, in the background)
Give it every source from step 1 and these instructions:
- Read sources read-only; memories from the last ~6 weeks in full, older ones by header
  (plus older ones holding open items). Optional read-only Jira status check.
- Rewrite `<root>/.agent-brain/STATE.md` keeping the template headings, as a SNAPSHOT of
  now; every open item cites evidence; unclear/conflicting → "Stale / needs verification".
  Limits: total ≤ 120 KB; Goal 6 KB/15 · Now 18 KB/25 · Blocked 12 KB/15 · Next up 12 KB/20 ·
  Open defects 18 KB/40 · Recently done 18 KB/40 · Standing rules 12 KB/30 · Stale 10 KB/25 ·
  Where things live 10 KB/40. Most important first in Now/Blocked/Next up/Standing rules
  (only those load at session start).
- Write a cards file (JSON list: `title`, `status` todo|doing|blocked|review, `kind`
  bug|feature|investigation|debt|infra, `jira`, `body` = 2-6 lines: goal, state, next
  step, evidence), only genuinely open work.
- **Never write secrets** (passwords, PINs, tokens, keys) into STATE.md or cards.
- Report: sources read, items per section, card count, conflicts, top 5 open items.

## 5. Load, verify, review
- `$BRAIN_TOOL seed-cards <cards.json>` from inside the root.
- `$BRAIN_TOOL check <root>` must be clean; read STATE.md and spot-check 3 claims.
- Hook test: pipe `{"cwd": "<a project folder>"}` into `$BRAIN_TOOL session-start`.
- `$BRAIN_TOOL save "onboard <id>"`.
- Show the user: sections + counts, conflicts, top open items, cards by status, and
  where the brain lives. Apply their corrections, then `save` again.
