# Jira issues and comments (read before creating, commenting on, or closing an issue)

Consolidated from the owner's rules (2026-05-26 to 2026-09). Project specifics (project
key, component, REQ ids, forbidden fields, which tracker docs to link) live in that
project's brain, under `Standing rules & traps`. Check them before acting.

## 1. Write for a human, always
The audience is teammates, stakeholders and QA, not a build log.
- **Lead with one plain-language line:** what changed or what it means.
- **Use Jira wiki markup:** `h3.` sub-headings, `*bold*`, `*` bullets, `#` numbered
  lists, `{{monospace}}` only for the occasional key or command, `{noformat}` for logs.
- **Short sections** ("What was done", "How it was verified", "Still open") instead
  of one paragraph.
- **Keep keys, SHAs and paths to a minimum.** Reference them; don't recite inventories.
  Issue keys auto-link.
- Explain it the way you would to a colleague who stepped away.
- **No AI/agent footer or attribution** (see the always-on commit rule). **No secrets**, ever.

## 2. Creating issues
- **Check for duplicates before filing anything:** JQL for the same component, label
  or summary among unresolved issues. If one exists, **comment on it** instead.
- **Summary:** plain English, ≤ 80 chars, says *what* is wrong or delivered, never just
  an identifier. Bug pattern: `<what failed, in human terms> on build #<N>`.
- **Bug description sections, in order:** `h3. What this verifies / What is expected` ·
  `h3. What happened` (failure in `{noformat}`, truncated) · `h3. Evidence` (build link,
  test key, execution key) · `h3. First-look triage`.
- **Backward documentation** (filing work that already runs): present-tense capability
  statement ("The appliance acquires a TLS certificate at first boot"), business
  perspective, evidence by reference, plus the project's traceability line (e.g.
  `Closes REQ-VM-<n>.<m>`, `Xray coverage: <key>`).
- **Some fields can't be set at create** in some projects; they return 400 and belong
  to a workflow transition. Check the project's rules, or `create-meta`, first.
- Link test evidence with the right link types (e.g. "Detected by" from bug to execution).

## 3. Never close silently
**Every transition to Done/Closed/Resolved gets a comment first** (or right after).
A closed issue with no comment leaves reviewers no audit trail.
- **Bug:** what the problem was (plain terms), what fixed it, how to confirm.
- **Task / sub-task:** what was delivered and why it matters, how it was tested.
- **The close comment must also carry** the **public link** to the reference doc (not a
  login-gated URL), and the **test evidence** when the issue has or needs coverage
  (test set/plan, test keys, latest green execution).
- **In progress / blocked:** a status comment covering what is done, what remains, and
  who acts next.

## 4. Keep Jira, docs and code in step
Every delivered change is recorded in **git** (its own commit), **Jira** (issue or
comment) and the project's **docs**, plus the job config when a CI parameter changed.
Treat that as the closing step of every task, not a follow-up.
