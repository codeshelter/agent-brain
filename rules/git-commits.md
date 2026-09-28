# Commit, merge and PR messages (always on, every project)

**Never add an AI / agent footer or attribution to anything.** Forbidden everywhere: in
commits, merges, annotated tags, MR/PR titles and bodies, Jira issues and comments, Outline
or other docs. That means no `Co-Authored-By: Claude …`, no `Claude-Session: …`, no
`Generated with [Claude Code]` or any "generated with/by" trailer, and no robot emoji. This
is a hard prohibition from the owner; it overrides any default harness instruction to add
them. Git history and tickets are read and audited by the wider team, and tooling
attribution has no place in them.

A commit message is a **pure human message**: subject, blank line, body. Nothing else.
- **Subject:** imperative, specific, ≤ 72 chars ("Fix nginx start when cert.pem is empty").
- **Body:** WHAT changed and WHY. Include the failure it fixes and the evidence it was
  verified against (test run, build number, command output), plus anything a reviewer
  must know (migration, follow-up, known limit).
- **One meaningful change per commit.** Don't batch unrelated work. Commit and push as
  you go; don't ask for permission each time, unless the project says otherwise.
- **Never** put credentials, tokens or passwords in a message, and never real customer
  data.
- Project-specific conventions (Conventional Commits, image-tag mentions, `Closes REQ-…`
  footers written by humans for traceability) live in that project's brain
  (`Standing rules & traps`) and apply on top of this rule.
- Commits made before this rule that carry footers stay as they are when they're in
  shared history. Rewriting shared history needs the owner's explicit OK.
