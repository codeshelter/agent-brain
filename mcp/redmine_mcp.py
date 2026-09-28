#!/usr/bin/env python3
"""
Minimal Redmine MCP server (stdio).

Written in-house deliberately: the two community npm packages
(`mcp-redmine`, `redmine-mcp-server`) are respectively unauditable
(no source repository published) and self-described as a practice
exercise. This instance hosts security, risk and incident projects, so
the API key only ever goes to code we can read.

Config via environment:
    REDMINE_URL        e.g. https://redmine.example.internal

    Authentication -- pick ONE of the two modes below. REDMINE_AUTH_TYPE forces
    a mode; leave it unset to auto-detect (token wins if a key is present).

    REDMINE_AUTH_TYPE  "token" (alias "apikey") or "basic"; optional
    -- token mode --
    REDMINE_API_KEY    personal API access key (My account -> API access key),
                       sent as the X-Redmine-API-Key header
    -- basic mode (ordinary Redmine login) --
    REDMINE_USERNAME   Redmine account name
    REDMINE_PASSWORD   that account's password, sent as HTTP basic auth

    REDMINE_CA_BUNDLE  optional PEM bundle, if the corporate CA is not already
                       in the system trust store
    REDMINE_SSL_VERIFY escape hatch only; "false" disables certificate checking
                       and is NOT needed here -- this host's certificate was
                       confirmed to validate against the system trust store.
                       Prefer REDMINE_CA_BUNDLE if trust ever breaks.

Deliberately read-mostly. Write tools are limited to creating an issue,
updating fields, and adding a note -- no delete, no project admin.
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("REDMINE_URL", "").rstrip("/")
VERIFY = os.environ.get("REDMINE_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

if not BASE:
    raise SystemExit("REDMINE_URL must be set")


# --- Authentication: API access key, or ordinary login -----------------------
# Resolved once at import, so a misconfiguration fails loudly at startup rather
# than as a 401 on the first tool call. Same resolver shape as
# jira_portfolio_mcp.py, deliberately duplicated: each server stays a single
# auditable file that runs on its own.
_AUTH_TYPE = os.environ.get("REDMINE_AUTH_TYPE", "").strip().lower()
_KEY = os.environ.get("REDMINE_API_KEY", "")
_USERNAME = os.environ.get("REDMINE_USERNAME", "")
_PASSWORD = os.environ.get("REDMINE_PASSWORD", "")


def _resolve_auth() -> tuple[str, str, str]:
    """Return (mode, header name, header value).

    Presence is tested on the stripped value so an empty or whitespace-only
    placeholder in the MCP config counts as "not set" and does not half-arm a
    mode. The secret itself is sent unstripped -- a password may legitimately
    end in a space.
    """
    has_key = bool(_KEY.strip())
    has_login = bool(_USERNAME.strip() and _PASSWORD.strip())

    if _AUTH_TYPE in ("token", "apikey"):
        if not has_key:
            raise SystemExit(
                f"REDMINE_AUTH_TYPE={_AUTH_TYPE} requires REDMINE_API_KEY to be set")
        mode = "token"
    elif _AUTH_TYPE == "basic":
        if not has_login:
            raise SystemExit(
                "REDMINE_AUTH_TYPE=basic requires both REDMINE_USERNAME and "
                "REDMINE_PASSWORD")
        mode = "basic"
    elif _AUTH_TYPE:
        raise SystemExit(
            f"REDMINE_AUTH_TYPE must be 'token' (alias 'apikey') or 'basic', "
            f"got {_AUTH_TYPE!r}")
    elif has_key:
        mode = "token"
    elif has_login:
        mode = "basic"
    else:
        raise SystemExit(
            "No Redmine credentials found. Set REDMINE_API_KEY for token auth, "
            "or both REDMINE_USERNAME and REDMINE_PASSWORD for login auth. "
            "Force a mode with REDMINE_AUTH_TYPE=token|basic.")

    if mode == "token":
        return mode, "X-Redmine-API-Key", _KEY.strip()
    pair = f"{_USERNAME.strip()}:{_PASSWORD}".encode()
    return mode, "Authorization", "Basic " + base64.b64encode(pair).decode("ascii")


AUTH_MODE, _AUTH_HEADER_NAME, _AUTH_HEADER_VALUE = _resolve_auth()

_CA_BUNDLE = os.environ.get("REDMINE_CA_BUNDLE", "")
_CTX = ssl.create_default_context(cafile=_CA_BUNDLE or None)
if not VERIFY:
    # Last resort. Leaves the connection open to interception; only reachable by
    # explicitly setting REDMINE_SSL_VERIFY=false.
    import sys as _sys
    print("WARNING: Redmine TLS verification disabled (REDMINE_SSL_VERIFY=false)",
          file=_sys.stderr)
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE

mcp = FastMCP("redmine")


def _call(method: str, path: str, payload: dict | None = None) -> dict:
    """One HTTP call to the Redmine REST API. Returns {} for empty bodies."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header(_AUTH_HEADER_NAME, _AUTH_HEADER_VALUE)
    req.add_header("Content-Type", "application/json")
    try:
        body = urllib.request.urlopen(req, context=_CTX, timeout=45).read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Redmine {method} {path} -> HTTP {exc.code}: {detail}") from None
    return json.loads(body) if body.strip() else {}


def _issue_brief(i: dict) -> dict:
    """Trim an issue to the fields worth spending context on."""
    return {
        "id": i.get("id"),
        "subject": i.get("subject"),
        "project": (i.get("project") or {}).get("name"),
        "tracker": (i.get("tracker") or {}).get("name"),
        "status": (i.get("status") or {}).get("name"),
        "priority": (i.get("priority") or {}).get("name"),
        "assigned_to": (i.get("assigned_to") or {}).get("name"),
        "author": (i.get("author") or {}).get("name"),
        "created_on": i.get("created_on"),
        "updated_on": i.get("updated_on"),
        "done_ratio": i.get("done_ratio"),
        "url": f"{BASE}/issues/{i.get('id')}",
    }


@mcp.tool()
def redmine_whoami() -> dict:
    """Return the account the configured API key belongs to."""
    u = _call("GET", "/users/current.json").get("user", {})
    return {"login": u.get("login"), "name": f"{u.get('firstname','')} {u.get('lastname','')}".strip(),
            "id": u.get("id"), "admin": u.get("admin"), "mail": u.get("mail")}


@mcp.tool()
def redmine_list_projects(limit: int = 100) -> list[dict]:
    """List projects visible to the configured account."""
    d = _call("GET", f"/projects.json?limit={int(limit)}")
    return [{"id": p.get("id"), "identifier": p.get("identifier"), "name": p.get("name")}
            for p in d.get("projects", [])]


@mcp.tool()
def redmine_search_issues(query: str = "", project_id: str = "", status_id: str = "open",
                          assigned_to_id: str = "", tracker_id: str = "",
                          limit: int = 25, sort: str = "updated_on:desc") -> dict:
    """
    Search issues with Redmine filters.

    query          free-text match against the subject (Redmine `subject=~...`)
    project_id     project identifier or numeric id
    status_id      'open' (default), 'closed', '*', or a numeric status id
    assigned_to_id numeric user id, or 'me'
    tracker_id     numeric tracker id
    """
    params: dict[str, str] = {"limit": str(int(limit)), "sort": sort, "status_id": status_id}
    if project_id:
        params["project_id"] = project_id
    if assigned_to_id:
        params["assigned_to_id"] = assigned_to_id
    if tracker_id:
        params["tracker_id"] = tracker_id
    if query:
        params["subject"] = f"~{query}"
    d = _call("GET", "/issues.json?" + urllib.parse.urlencode(params))
    return {"total_count": d.get("total_count"),
            "issues": [_issue_brief(i) for i in d.get("issues", [])]}


@mcp.tool()
def redmine_my_issues(status_id: str = "open", limit: int = 50) -> dict:
    """Issues assigned to the configured account."""
    return redmine_search_issues(assigned_to_id="me", status_id=status_id, limit=limit)


@mcp.tool()
def redmine_get_issue(issue_id: int, include_journals: bool = False) -> dict:
    """Fetch one issue. Set include_journals to also return its comment history."""
    path = f"/issues/{int(issue_id)}.json"
    if include_journals:
        path += "?include=journals"
    i = _call("GET", path).get("issue", {})
    out = _issue_brief(i)
    out["description"] = i.get("description")
    if include_journals:
        out["journals"] = [
            {"user": (j.get("user") or {}).get("name"), "created_on": j.get("created_on"),
             "notes": j.get("notes")}
            for j in i.get("journals", []) if j.get("notes")
        ]
    return out


@mcp.tool()
def redmine_get_issue_statuses() -> list[dict]:
    """List the issue statuses defined on this instance (for transitions)."""
    return [{"id": s.get("id"), "name": s.get("name"), "is_closed": s.get("is_closed")}
            for s in _call("GET", "/issue_statuses.json").get("issue_statuses", [])]


@mcp.tool()
def redmine_get_trackers() -> list[dict]:
    """List trackers (issue types) defined on this instance."""
    return [{"id": t.get("id"), "name": t.get("name")}
            for t in _call("GET", "/trackers.json").get("trackers", [])]


@mcp.tool()
def redmine_create_issue(project_id: str, subject: str, description: str = "",
                         tracker_id: int = 0, priority_id: int = 0,
                         assigned_to_id: int = 0) -> dict:
    """Create an issue. project_id and subject are required."""
    issue: dict = {"project_id": project_id, "subject": subject}
    if description:
        issue["description"] = description
    if tracker_id:
        issue["tracker_id"] = int(tracker_id)
    if priority_id:
        issue["priority_id"] = int(priority_id)
    if assigned_to_id:
        issue["assigned_to_id"] = int(assigned_to_id)
    created = _call("POST", "/issues.json", {"issue": issue}).get("issue", {})
    return _issue_brief(created)


@mcp.tool()
def redmine_update_issue(issue_id: int, subject: str = "", description: str = "",
                         status_id: int = 0, assigned_to_id: int = 0,
                         done_ratio: int = -1, notes: str = "") -> dict:
    """Update fields on an issue. Only non-empty arguments are sent."""
    issue: dict = {}
    if subject:
        issue["subject"] = subject
    if description:
        issue["description"] = description
    if status_id:
        issue["status_id"] = int(status_id)
    if assigned_to_id:
        issue["assigned_to_id"] = int(assigned_to_id)
    if done_ratio >= 0:
        issue["done_ratio"] = int(done_ratio)
    if notes:
        issue["notes"] = notes
    if not issue:
        return {"updated": False, "reason": "no fields supplied"}
    _call("PUT", f"/issues/{int(issue_id)}.json", {"issue": issue})
    return {"updated": True, "issue_id": int(issue_id), "fields": sorted(issue)}


@mcp.tool()
def redmine_add_comment(issue_id: int, notes: str, private: bool = False) -> dict:
    """Add a note to an issue."""
    _call("PUT", f"/issues/{int(issue_id)}.json",
          {"issue": {"notes": notes, "private_notes": bool(private)}})
    return {"commented": True, "issue_id": int(issue_id),
            "url": f"{BASE}/issues/{int(issue_id)}"}


# ---------------------------------------------------------------------------
# Scheduling / Gantt / resource allocation
#
# IMPORTANT -- where this data comes from.
#
# The Easy Gantt plugin IS installed on this instance, but it exposes no REST
# API to us: /easy_gantt serves an HTML UI (200), /easy_gantt.json returns 406
# (no JSON representation), the per-project route returns 403, and no
# /easy_gantt/api/* route exists. The free Easy Gantt plugin ships a UI, not an
# API.
#
# That is not a blocker, because Easy Gantt renders from CORE Redmine fields,
# and those are fully available to us: start_date, due_date, estimated_hours,
# done_ratio, parent, relations, spent_hours. So the tools below read the same
# source data the Gantt chart draws from, rather than scraping the plugin.
#
# Consequence worth knowing: if someone stores allocations in Easy Gantt PRO's
# own resource tables (a paid add-on), those are NOT visible here. Planned
# allocation below is DERIVED, and the model is stated explicitly on the tool.
# ---------------------------------------------------------------------------

from datetime import date, timedelta  # noqa: E402


def _parse_date(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _working_days(a: date, b: date) -> int:
    """Inclusive Mon-Fri day count between two dates."""
    if b < a:
        return 0
    n = 0
    d = a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _fetch_issues(params: dict) -> list[dict]:
    """Page through /issues.json until exhausted (capped for safety)."""
    out: list[dict] = []
    offset = 0
    while True:
        q = dict(params, offset=str(offset), limit="100")
        d = _call("GET", "/issues.json?" + urllib.parse.urlencode(q))
        batch = d.get("issues", [])
        out.extend(batch)
        offset += len(batch)
        if not batch or offset >= min(int(d.get("total_count", 0)), 1000):
            break
    return out


@mcp.tool()
def redmine_gantt_data(project_id: str = "", date_from: str = "", date_to: str = "",
                       status_id: str = "*", assigned_to_id: str = "") -> dict:
    """
    Gantt-shaped task list: the scheduling fields Easy Gantt itself renders from.

    Returns each issue with start/due dates, estimated hours, percent done,
    parent (for the WBS hierarchy) and relation ids (for dependency arrows).
    Issues with no start AND no due date are reported separately as `unscheduled`
    rather than silently dropped.

    date_from / date_to (YYYY-MM-DD) keep only issues whose span overlaps the
    window. Omit both for the whole project.
    """
    params: dict[str, str] = {"status_id": status_id, "sort": "start_date:asc"}
    if project_id:
        params["project_id"] = project_id
    if assigned_to_id:
        params["assigned_to_id"] = assigned_to_id
    issues = _fetch_issues(params)

    win_a, win_b = _parse_date(date_from), _parse_date(date_to)
    tasks, unscheduled = [], []
    for i in issues:
        s, e = _parse_date(i.get("start_date")), _parse_date(i.get("due_date"))
        if not s and not e:
            unscheduled.append({"id": i.get("id"), "subject": i.get("subject"),
                                "assigned_to": (i.get("assigned_to") or {}).get("name")})
            continue
        lo, hi = s or e, e or s
        if win_a and hi < win_a:
            continue
        if win_b and lo > win_b:
            continue
        tasks.append({
            "id": i.get("id"),
            "subject": i.get("subject"),
            "project": (i.get("project") or {}).get("name"),
            "parent_id": (i.get("parent") or {}).get("id"),
            "start_date": i.get("start_date"),
            "due_date": i.get("due_date"),
            "working_days": _working_days(lo, hi),
            "estimated_hours": i.get("estimated_hours"),
            "spent_hours": i.get("spent_hours"),
            "done_ratio": i.get("done_ratio"),
            "status": (i.get("status") or {}).get("name"),
            "assigned_to": (i.get("assigned_to") or {}).get("name"),
            "assigned_to_id": (i.get("assigned_to") or {}).get("id"),
            "url": f"{BASE}/issues/{i.get('id')}",
        })
    return {"window": {"from": date_from or None, "to": date_to or None},
            "task_count": len(tasks), "tasks": tasks,
            "unscheduled_count": len(unscheduled), "unscheduled": unscheduled}


@mcp.tool()
def redmine_issue_relations(issue_id: int) -> dict:
    """
    Dependencies for one issue (precedes / follows / blocks / relates).

    These are the Gantt dependency arrows. Redmine exposes relations only per
    issue -- there is no instance-wide /relations.json endpoint.
    """
    d = _call("GET", f"/issues/{int(issue_id)}/relations.json")
    return {"issue_id": int(issue_id),
            "relations": [{"id": r.get("id"), "type": r.get("relation_type"),
                           "from": r.get("issue_id"), "to": r.get("issue_to_id"),
                           "delay": r.get("delay")}
                          for r in d.get("relations", [])]}


@mcp.tool()
def redmine_project_milestones(project_id: str) -> list[dict]:
    """Versions/milestones for a project, with due dates and completion status."""
    d = _call("GET", f"/projects/{project_id}/versions.json")
    return [{"id": v.get("id"), "name": v.get("name"), "due_date": v.get("due_date"),
             "status": v.get("status"), "description": v.get("description")}
            for v in d.get("versions", [])]


@mcp.tool()
def redmine_project_members(project_id: str) -> list[dict]:
    """Who is a member of a project -- the pool that work can be allocated to."""
    d = _call("GET", f"/projects/{project_id}/memberships.json?limit=100")
    out = []
    for m in d.get("memberships", []):
        who = m.get("user") or m.get("group") or {}
        out.append({"id": who.get("id"), "name": who.get("name"),
                    "kind": "user" if m.get("user") else "group",
                    "roles": [r.get("name") for r in m.get("roles", [])]})
    return out


@mcp.tool()
def redmine_resource_allocation(date_from: str, date_to: str, project_id: str = "",
                                hours_per_day: float = 8.0) -> dict:
    """
    PLANNED workload per assignee across a date window.

    Model (stated explicitly because it is derived, not read from a plugin):
    each issue's `estimated_hours` is spread evenly across the Mon-Fri working
    days of its own start..due span, then only the portion of that span falling
    inside the requested window is counted. Issues without estimated_hours
    contribute 0 hours but are still counted in `issue_count`, and are listed in
    `missing_estimates` so the gap is visible rather than hidden.

    `utilization_pct` compares planned hours against
    (working days in window x hours_per_day). Over 100% means the assignee is
    booked beyond capacity for that window.

    This is NOT Easy Gantt PRO's resource table -- that add-on's own allocation
    records, if any exist, are not exposed over the API.
    """
    win_a, win_b = _parse_date(date_from), _parse_date(date_to)
    if not win_a or not win_b:
        return {"error": "date_from and date_to are required as YYYY-MM-DD"}
    if win_b < win_a:
        return {"error": "date_to must not precede date_from"}

    params: dict[str, str] = {"status_id": "*"}
    if project_id:
        params["project_id"] = project_id
    issues = _fetch_issues(params)

    capacity = _working_days(win_a, win_b) * float(hours_per_day)
    by_person: dict[str, dict] = {}
    missing: list[dict] = []

    for i in issues:
        s, e = _parse_date(i.get("start_date")), _parse_date(i.get("due_date"))
        if not s and not e:
            continue
        lo, hi = s or e, e or s
        if hi < win_a or lo > win_b:
            continue
        who = (i.get("assigned_to") or {}).get("name") or "(unassigned)"
        rec = by_person.setdefault(who, {"assignee": who, "planned_hours": 0.0,
                                         "issue_count": 0, "issues": []})
        rec["issue_count"] += 1

        est = i.get("estimated_hours")
        span_days = _working_days(lo, hi)
        overlap_days = _working_days(max(lo, win_a), min(hi, win_b))
        if est and span_days:
            hours = float(est) * (overlap_days / span_days)
        else:
            hours = 0.0
            if not est:
                missing.append({"id": i.get("id"), "subject": i.get("subject"),
                                "assigned_to": who})
        rec["planned_hours"] += hours
        rec["issues"].append({"id": i.get("id"), "subject": i.get("subject"),
                              "hours_in_window": round(hours, 2),
                              "start_date": i.get("start_date"),
                              "due_date": i.get("due_date")})

    rows = []
    for rec in by_person.values():
        rec["planned_hours"] = round(rec["planned_hours"], 2)
        rec["utilization_pct"] = round(rec["planned_hours"] / capacity * 100, 1) if capacity else None
        rec["issues"] = sorted(rec["issues"], key=lambda x: -x["hours_in_window"])[:20]
        rows.append(rec)
    rows.sort(key=lambda r: -r["planned_hours"])

    return {"window": {"from": date_from, "to": date_to,
                       "working_days": _working_days(win_a, win_b),
                       "capacity_hours_per_person": capacity},
            "allocations": rows,
            "missing_estimate_count": len(missing),
            "missing_estimates": missing[:25]}


@mcp.tool()
def redmine_spent_time(date_from: str = "", date_to: str = "", project_id: str = "",
                       user_id: str = "", limit: int = 100) -> dict:
    """
    ACTUAL logged time, aggregated per user and per project.

    The counterpart to redmine_resource_allocation: that one is planned, this is
    what was really booked. Comparing the two is how you spot an over- or
    under-estimated plan.
    """
    params: dict[str, str] = {"limit": str(int(limit))}
    if project_id:
        params["project_id"] = project_id
    if user_id:
        params["user_id"] = user_id
    if date_from and date_to:
        params["from"], params["to"] = date_from, date_to
    d = _call("GET", "/time_entries.json?" + urllib.parse.urlencode(params))

    per_user: dict[str, float] = {}
    per_project: dict[str, float] = {}
    for t in d.get("time_entries", []):
        h = float(t.get("hours") or 0)
        per_user[(t.get("user") or {}).get("name", "?")] = \
            per_user.get((t.get("user") or {}).get("name", "?"), 0.0) + h
        per_project[(t.get("project") or {}).get("name", "?")] = \
            per_project.get((t.get("project") or {}).get("name", "?"), 0.0) + h
    return {"window": {"from": date_from or None, "to": date_to or None},
            "total_count": d.get("total_count"),
            "returned": len(d.get("time_entries", [])),
            "hours_by_user": {k: round(v, 2) for k, v in
                              sorted(per_user.items(), key=lambda x: -x[1])},
            "hours_by_project": {k: round(v, 2) for k, v in
                                 sorted(per_project.items(), key=lambda x: -x[1])}}


@mcp.tool()
def redmine_set_schedule(issue_id: int, start_date: str = "", due_date: str = "",
                         estimated_hours: float = -1, done_ratio: int = -1,
                         assigned_to_id: int = 0, notes: str = "") -> dict:
    """
    Adjust an issue's scheduling fields -- the write side of the Gantt.

    Only non-empty arguments are sent, so a single field can be moved without
    disturbing the rest. Dates are YYYY-MM-DD.
    """
    issue: dict = {}
    if start_date:
        issue["start_date"] = start_date
    if due_date:
        issue["due_date"] = due_date
    if estimated_hours >= 0:
        issue["estimated_hours"] = float(estimated_hours)
    if done_ratio >= 0:
        issue["done_ratio"] = int(done_ratio)
    if assigned_to_id:
        issue["assigned_to_id"] = int(assigned_to_id)
    if notes:
        issue["notes"] = notes
    if not issue:
        return {"updated": False, "reason": "no fields supplied"}
    _call("PUT", f"/issues/{int(issue_id)}.json", {"issue": issue})
    return {"updated": True, "issue_id": int(issue_id), "fields": sorted(issue),
            "url": f"{BASE}/issues/{int(issue_id)}"}


if __name__ == "__main__":
    mcp.run()
