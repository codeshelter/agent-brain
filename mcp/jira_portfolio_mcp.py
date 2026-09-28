#!/usr/bin/env python3
"""
Jira Portfolio (Advanced Roadmaps) MCP server -- stdio.

Covers the gap in `mcp-atlassian`: that package ships 63 tools spanning core
Jira, Jira Software, Service Desk and Proforma, but NOTHING for Portfolio plans.
This server sits alongside it rather than replacing it.

--------------------------------------------------------------------------
What the Portfolio API on this instance actually exposes -- probed, not assumed
--------------------------------------------------------------------------
Jira 8.20.30 Server uses the legacy JPO namespace. Working, JSON-returning:

    GET /rest/jpo/1.0/plans/list      -> all plans
    GET /rest/jpo/1.0/plans/<id>      -> one plan's configuration
    GET /rest/jpo/1.0/programs/list   -> programs AND plans together
    GET /rest/jpo/1.0/configuration   -> instance limits

Everything else 404s: no /plans/<id>/issues, /scope, /teams, /state, /export,
/versions, and no /teams, /resources, /hierarchy at top level.

TRAP WORTH KNOWING: /rest/portfolio/1/plans, /rest/plans/1.0/plans and
/rest/roadmaps/1.0/plans all return **HTTP 200 with an HTML login page**, not
JSON. A 200 there means "unknown route, here is the login screen". Any code
that trusts the status code alone will silently believe Portfolio works. This
module checks Content-Type on every call for exactly that reason.

--------------------------------------------------------------------------
How plan SCOPE is reconstructed
--------------------------------------------------------------------------
Because no /plans/<id>/issues route exists, scope is derived the same way
Portfolio itself builds it: a plan declares `issueSources` (Board / Project /
Filter), and those resolve through core Jira. Portfolio's own scheduling data
lives in JQL-searchable custom fields (Target start, Target end, Parent Link,
Team), so the roadmap and hierarchy tools read those directly.

Field ids are DISCOVERED BY NAME at runtime, never hardcoded -- they differ per
instance (here: Target start = customfield_14561).

Config via environment:
    JIRA_URL              e.g. https://jira.example.internal

    Authentication -- pick ONE of the two modes below. JIRA_AUTH_TYPE forces a
    mode; leave it unset to auto-detect (token wins if a token is present).

    JIRA_AUTH_TYPE        "token" (alias "pat") or "basic"; optional
    -- token mode --
    JIRA_PERSONAL_TOKEN   personal access token, sent as "Authorization: Bearer"
    -- basic mode (ordinary Jira login) --
    JIRA_USERNAME         Jira account name
    JIRA_API_TOKEN        that account's password on Server/DC; named to match
                          mcp-atlassian so one env block serves both servers

    JIRA_CA_BUNDLE        optional PEM bundle if the corporate CA is not trusted
    JIRA_SSL_VERIFY       escape hatch only; "false" disables cert checking and
                          is NOT needed here -- this host validates against the
                          system trust store.
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

BASE = os.environ.get("JIRA_URL", "").rstrip("/")
VERIFY = os.environ.get("JIRA_SSL_VERIFY", "true").lower() not in ("false", "0", "no")
CA_BUNDLE = os.environ.get("JIRA_CA_BUNDLE", "")

if not BASE:
    raise SystemExit("JIRA_URL must be set")


# --- Authentication: personal access token, or ordinary login ----------------
# Resolved once at import, so a misconfiguration fails loudly at startup rather
# than surfacing later as Jira's 200-plus-HTML-login-page (see NotAnApiResponse).
# Same resolver shape as redmine_mcp.py, deliberately duplicated: each server
# stays a single auditable file that runs on its own.
_AUTH_TYPE = os.environ.get("JIRA_AUTH_TYPE", "").strip().lower()
_TOKEN = os.environ.get("JIRA_PERSONAL_TOKEN", "")
_USERNAME = os.environ.get("JIRA_USERNAME", "")
_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")


def _resolve_auth() -> tuple[str, str]:
    """Return (mode, Authorization header value).

    Presence is tested on the stripped value so an empty or whitespace-only
    placeholder in the MCP config counts as "not set" and does not half-arm a
    mode. The secret itself is sent unstripped -- a password may legitimately
    end in a space.
    """
    has_token = bool(_TOKEN.strip())
    has_login = bool(_USERNAME.strip() and _API_TOKEN.strip())

    if _AUTH_TYPE in ("token", "pat"):
        if not has_token:
            raise SystemExit(
                f"JIRA_AUTH_TYPE={_AUTH_TYPE} requires JIRA_PERSONAL_TOKEN to be set")
        mode = "token"
    elif _AUTH_TYPE == "basic":
        if not has_login:
            raise SystemExit(
                "JIRA_AUTH_TYPE=basic requires both JIRA_USERNAME and JIRA_API_TOKEN")
        mode = "basic"
    elif _AUTH_TYPE:
        raise SystemExit(
            f"JIRA_AUTH_TYPE must be 'token' (alias 'pat') or 'basic', got {_AUTH_TYPE!r}")
    elif has_token:
        mode = "token"
    elif has_login:
        mode = "basic"
    else:
        raise SystemExit(
            "No Jira credentials found. Set JIRA_PERSONAL_TOKEN for token auth, "
            "or both JIRA_USERNAME and JIRA_API_TOKEN for login auth. "
            "Force a mode with JIRA_AUTH_TYPE=token|basic.")

    if mode == "token":
        return mode, "Bearer " + _TOKEN.strip()
    pair = f"{_USERNAME.strip()}:{_API_TOKEN}".encode()
    return mode, "Basic " + base64.b64encode(pair).decode("ascii")


AUTH_MODE, _AUTH_HEADER = _resolve_auth()

_CTX = ssl.create_default_context(cafile=CA_BUNDLE or None)
if not VERIFY:
    import sys as _sys
    print("WARNING: Jira TLS verification disabled (JIRA_SSL_VERIFY=false)", file=_sys.stderr)
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE

mcp = FastMCP("jira-portfolio")


class NotAnApiResponse(RuntimeError):
    """Raised when Jira answers 200 with HTML -- i.e. the route does not exist."""


def _get(path: str) -> dict | list:
    """GET returning parsed JSON, rejecting HTML-login responses explicitly."""
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", _AUTH_HEADER)
    req.add_header("Accept", "application/json")
    try:
        resp = urllib.request.urlopen(req, context=_CTX, timeout=60)
        ctype = resp.headers.get("Content-Type", "")
        body = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {path} -> HTTP {exc.code}: "
                           f"{exc.read().decode(errors='replace')[:300]}") from None
    if "json" not in ctype:
        raise NotAnApiResponse(
            f"GET {path} returned {ctype!r}, not JSON. On this Jira that means the "
            f"route does not exist -- unknown /rest paths render the login page "
            f"with status 200."
        )
    return json.loads(body)


def _put(path: str, payload: dict) -> None:
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), method="PUT")
    req.add_header("Authorization", _AUTH_HEADER)
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, context=_CTX, timeout=60).read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"PUT {path} -> HTTP {exc.code}: "
                           f"{exc.read().decode(errors='replace')[:300]}") from None


# --- Portfolio custom fields, discovered by name (ids vary per instance) ------
_FIELD_NAMES = {
    "target_start": "Target start",
    "target_end": "Target end",
    "parent_link": "Parent Link",
    "team": "Team",
    "epic_link": "Epic Link",
}
_FIELD_CACHE: dict[str, str] = {}


def _fields() -> dict[str, str]:
    """Resolve Portfolio field names -> customfield ids, once per process."""
    if _FIELD_CACHE:
        return _FIELD_CACHE
    for f in _get("/rest/api/2/field"):
        for key, name in _FIELD_NAMES.items():
            if f.get("name", "").lower() == name.lower() and key not in _FIELD_CACHE:
                _FIELD_CACHE[key] = f["id"]
    return _FIELD_CACHE


def _search(jql: str, fields: list[str], limit: int = 100) -> dict:
    q = urllib.parse.urlencode({"jql": jql, "maxResults": str(limit),
                                "fields": ",".join(fields)})
    return _get("/rest/api/2/search?" + q)


def _board_filter(board_id: str | int) -> dict:
    """
    A board's backing filter (id + JQL).

    Note: /rest/agile/1.0/board/<id> returns only {id, self, name, type} -- it
    carries NO filter and NO location. The filter is only on the /configuration
    sub-resource, so anything trying to derive a board's scope from the plain
    board object silently finds nothing.
    """
    cfg = _get(f"/rest/agile/1.0/board/{board_id}/configuration")
    fid = (cfg.get("filter") or {}).get("id")
    out = {"board_name": cfg.get("name"), "board_type": cfg.get("type"),
           "filter_id": fid, "jql": None}
    if fid:
        out["jql"] = _get(f"/rest/api/2/filter/{fid}").get("jql")
    return out


def _brief(issue: dict, fm: dict[str, str]) -> dict:
    f = issue.get("fields", {})
    team = f.get(fm.get("team", ""))
    if isinstance(team, dict):
        team = team.get("title") or team.get("name") or team.get("value")
    return {
        "key": issue.get("key"),
        "summary": f.get("summary"),
        "type": (f.get("issuetype") or {}).get("name"),
        "status": (f.get("status") or {}).get("name"),
        "assignee": (f.get("assignee") or {}).get("displayName"),
        "target_start": f.get(fm.get("target_start", "")),
        "target_end": f.get(fm.get("target_end", "")),
        "parent_link": f.get(fm.get("parent_link", "")),
        "team": team,
        "url": f"{BASE}/browse/{issue.get('key')}",
    }


# ----------------------------- tools ----------------------------------------

@mcp.tool()
def portfolio_health() -> dict:
    """
    Confirm Portfolio is reachable and report which routes actually work.

    Useful first call: it distinguishes "Portfolio is installed and answering"
    from "the route 200s with a login page", which look identical by status code.
    """
    out: dict = {"jira": None, "portfolio_available": False, "routes": {}, "fields": {}}
    try:
        info = _get("/rest/api/2/serverInfo")
        out["jira"] = {"version": info.get("version"), "deployment": info.get("deploymentType")}
    except Exception as exc:
        out["jira"] = f"error: {exc}"
    for label, path in [("plans", "/rest/jpo/1.0/plans/list"),
                        ("programs", "/rest/jpo/1.0/programs/list"),
                        ("configuration", "/rest/jpo/1.0/configuration")]:
        try:
            _get(path)
            out["routes"][label] = "ok"
            out["portfolio_available"] = True
        except NotAnApiResponse:
            out["routes"][label] = "HTML login page (route absent)"
        except Exception as exc:
            out["routes"][label] = f"error: {str(exc)[:120]}"
    try:
        out["fields"] = _fields()
    except Exception as exc:
        out["fields"] = f"error: {exc}"
    return out


@mcp.tool()
def portfolio_list_plans() -> dict:
    """All Portfolio plans, grouped under the programs they belong to."""
    data = _get("/rest/jpo/1.0/programs/list")
    programs = {p["programId"]: p.get("title") for p in data.get("programs", [])}
    plans = []
    for p in data.get("plans", []):
        plans.append({"id": p.get("id"), "title": p.get("title"),
                      "program_id": p.get("programId"),
                      "program": programs.get(p.get("programId")),
                      "read_only": p.get("readOnly")})
    return {"program_count": len(programs), "programs": programs,
            "plan_count": len(plans), "plans": plans}


@mcp.tool()
def portfolio_list_programs() -> list[dict]:
    """Programs defined on this instance, with the plans each contains."""
    data = _get("/rest/jpo/1.0/programs/list")
    by_prog: dict = {p["programId"]: {"program_id": p["programId"], "title": p.get("title"),
                                      "plans": []} for p in data.get("programs", [])}
    for p in data.get("plans", []):
        pid = p.get("programId")
        if pid in by_prog:
            by_prog[pid]["plans"].append({"id": p.get("id"), "title": p.get("title")})
    return list(by_prog.values())


@mcp.tool()
def portfolio_get_plan(plan_id: int) -> dict:
    """
    One plan's configuration: planning unit, issue sources, scheduling fields,
    non-working days and calculation settings.
    """
    d = _get(f"/rest/jpo/1.0/plans/{int(plan_id)}")
    return {
        "id": d.get("id"),
        "title": d.get("title"),
        "program_id": d.get("programId"),
        "planning_unit": d.get("planningUnit"),
        "issue_sources": d.get("issueSources", []),
        "non_working_days": d.get("nonWorkingDays", []),
        "include_completed_issues_days": d.get("includeCompletedIssuesFor"),
        "multi_scenario_enabled": d.get("multiScenarioEnabled"),
        "calculation": d.get("calculationConfiguration"),
        "baseline_start_field": (d.get("baselineStartField") or {}).get("key"),
        "baseline_end_field": (d.get("baselineEndField") or {}).get("key"),
    }


@mcp.tool()
def portfolio_plan_sources(plan_id: int) -> dict:
    """
    Resolve a plan's issue sources into real names.

    A plan stores sources as bare ids (Board 4682, Project 24074). This turns
    them into board names and project keys so it is obvious what actually feeds
    the plan.
    """
    plan = _get(f"/rest/jpo/1.0/plans/{int(plan_id)}")
    resolved = []
    for src in plan.get("issueSources", []):
        kind, val = src.get("type"), src.get("value")
        entry = {"type": kind, "id": val}
        try:
            if kind == "Project":
                p = _get(f"/rest/api/2/project/{val}")
                entry.update({"key": p.get("key"), "name": p.get("name")})
            elif kind == "Board":
                bf = _board_filter(val)
                entry.update({"name": bf["board_name"], "board_type": bf["board_type"],
                              "filter_id": bf["filter_id"], "jql": bf["jql"]})
            elif kind == "Filter":
                fl = _get(f"/rest/api/2/filter/{val}")
                entry.update({"name": fl.get("name"), "jql": fl.get("jql")})
        except Exception as exc:
            entry["resolve_error"] = str(exc)[:150]
        resolved.append(entry)
    return {"plan_id": plan.get("id"), "title": plan.get("title"), "sources": resolved}


@mcp.tool()
def portfolio_plan_scope(plan_id: int, limit: int = 100, scheduled_only: bool = False) -> dict:
    """
    The issues feeding a plan, with their Portfolio scheduling fields.

    Reconstructed from the plan's issue sources, because this Jira exposes no
    /plans/<id>/issues route. Board sources contribute their board's issues,
    Project sources a project JQL, Filter sources the saved filter's JQL.

    scheduled_only=True keeps only issues that actually carry a Target start or
    Target end.
    """
    fm = _fields()
    want = ["summary", "issuetype", "status", "assignee"] + [
        fm[k] for k in ("target_start", "target_end", "parent_link", "team") if k in fm]
    plan = _get(f"/rest/jpo/1.0/plans/{int(plan_id)}")

    clauses, notes = [], []
    for src in plan.get("issueSources", []):
        kind, val = src.get("type"), src.get("value")
        try:
            if kind == "Project":
                p = _get(f"/rest/api/2/project/{val}")
                clauses.append(f'project = "{p.get("key")}"')
            elif kind == "Board":
                bf = _board_filter(val)
                if bf["jql"]:
                    clauses.append(f"({bf['jql']})")
                else:
                    notes.append(f"board {val} ({bf['board_name']}): no backing filter")
            elif kind == "Filter":
                fl = _get(f"/rest/api/2/filter/{val}")
                clauses.append(f"({fl.get('jql')})")
        except Exception as exc:
            notes.append(f"{kind} {val}: {str(exc)[:120]}")

    if not clauses:
        return {"plan_id": plan.get("id"), "title": plan.get("title"),
                "issue_count": 0, "issues": [],
                "notes": notes or ["no resolvable issue sources"]}

    jql = " OR ".join(clauses)
    if scheduled_only and "target_start" in fm:
        jql = f"({jql}) AND (\"{_FIELD_NAMES['target_start']}\" is not EMPTY " \
              f"OR \"{_FIELD_NAMES['target_end']}\" is not EMPTY)"
    res = _search(jql, want, limit)
    return {"plan_id": plan.get("id"), "title": plan.get("title"),
            "planning_unit": plan.get("planningUnit"),
            "jql": jql, "total_matching": res.get("total"),
            "returned": len(res.get("issues", [])),
            "issues": [_brief(i, fm) for i in res.get("issues", [])],
            "notes": notes}


@mcp.tool()
def portfolio_roadmap(date_from: str = "", date_to: str = "", project: str = "",
                      team: str = "", limit: int = 100) -> dict:
    """
    Roadmap view: issues carrying Portfolio target dates, ordered by start.

    Reads the Target start / Target end custom fields directly, so it works
    across plans (a plan is only a lens over the same underlying fields).
    Dates are YYYY-MM-DD.
    """
    fm = _fields()
    if "target_start" not in fm:
        return {"error": "Target start field not found -- is Portfolio installed?"}
    ts, te = _FIELD_NAMES["target_start"], _FIELD_NAMES["target_end"]
    parts = [f'("{ts}" is not EMPTY OR "{te}" is not EMPTY)']
    if date_from:
        parts.append(f'"{te}" >= "{date_from}"')
    if date_to:
        parts.append(f'"{ts}" <= "{date_to}"')
    if project:
        parts.append(f'project = "{project}"')
    if team:
        parts.append(f'"{_FIELD_NAMES["team"]}" = "{team}"')
    jql = " AND ".join(parts) + f' ORDER BY "{ts}" ASC'
    want = ["summary", "issuetype", "status", "assignee"] + [
        fm[k] for k in ("target_start", "target_end", "parent_link", "team") if k in fm]
    res = _search(jql, want, limit)
    return {"jql": jql, "total": res.get("total"),
            "returned": len(res.get("issues", [])),
            "items": [_brief(i, fm) for i in res.get("issues", [])]}


@mcp.tool()
def portfolio_hierarchy(parent_key: str, depth: int = 2, limit: int = 100) -> dict:
    """
    Walk the Portfolio hierarchy below an issue via the Parent Link field.

    Portfolio stacks initiative -> epic -> story using Parent Link (above epic)
    and Epic Link (epic -> story). Both are followed here.
    """
    fm = _fields()
    want = ["summary", "issuetype", "status", "assignee"] + [
        fm[k] for k in ("target_start", "target_end", "parent_link", "team") if k in fm]

    def children(key: str) -> list[dict]:
        clauses = [f'"{_FIELD_NAMES["parent_link"]}" = "{key}"']
        if "epic_link" in fm:
            clauses.append(f'"{_FIELD_NAMES["epic_link"]}" = "{key}"')
        clauses.append(f'parent = "{key}"')
        try:
            res = _search(" OR ".join(clauses), want, limit)
            return [_brief(i, fm) for i in res.get("issues", [])]
        except Exception:
            return []

    def walk(key: str, level: int) -> list[dict]:
        if level > int(depth):
            return []
        out = []
        for c in children(key):
            c["children"] = walk(c["key"], level + 1)
            out.append(c)
        return out

    return {"root": parent_key, "depth": int(depth), "children": walk(parent_key, 1)}


@mcp.tool()
def portfolio_team_workload(date_from: str = "", date_to: str = "", limit: int = 200) -> dict:
    """
    Scheduled work grouped by the Portfolio Team field over a date window.

    Counts issues, not hours: Portfolio estimates live in plan scenarios that
    this Jira does not expose over REST, so an hour figure here would be
    invented. Issue counts and date spans are real.
    """
    fm = _fields()
    if "team" not in fm:
        return {"error": "Team field not found -- is Portfolio installed?"}
    ts, te = _FIELD_NAMES["target_start"], _FIELD_NAMES["target_end"]
    parts = [f'("{ts}" is not EMPTY OR "{te}" is not EMPTY)']
    if date_from:
        parts.append(f'"{te}" >= "{date_from}"')
    if date_to:
        parts.append(f'"{ts}" <= "{date_to}"')
    want = ["summary", "issuetype", "status", "assignee"] + [
        fm[k] for k in ("target_start", "target_end", "parent_link", "team") if k in fm]
    res = _search(" AND ".join(parts), want, limit)

    buckets: dict[str, dict] = {}
    for i in res.get("issues", []):
        b = _brief(i, fm)
        name = b.get("team") or "(no team)"
        rec = buckets.setdefault(name, {"team": name, "issue_count": 0, "issues": []})
        rec["issue_count"] += 1
        if len(rec["issues"]) < 15:
            rec["issues"].append({"key": b["key"], "summary": b["summary"],
                                  "target_start": b["target_start"],
                                  "target_end": b["target_end"]})
    rows = sorted(buckets.values(), key=lambda r: -r["issue_count"])
    return {"window": {"from": date_from or None, "to": date_to or None},
            "total_scheduled": res.get("total"), "teams": rows,
            "note": "counts are issues, not hours -- plan-scenario estimates are "
                    "not exposed by this Jira's Portfolio API"}


@mcp.tool()
def portfolio_set_target_dates(issue_key: str, target_start: str = "",
                               target_end: str = "") -> dict:
    """
    Set an issue's Portfolio Target start / Target end (YYYY-MM-DD).

    This is the write side of the roadmap. Only non-empty values are sent.
    Note that a plan may recalculate derived dates from its own scenario; this
    writes the underlying fields, which is what Portfolio schedules against.
    """
    fm = _fields()
    payload: dict = {}
    if target_start and "target_start" in fm:
        payload[fm["target_start"]] = target_start
    if target_end and "target_end" in fm:
        payload[fm["target_end"]] = target_end
    if not payload:
        return {"updated": False, "reason": "no dates supplied, or fields not found"}
    _put(f"/rest/api/2/issue/{issue_key}", {"fields": payload})
    return {"updated": True, "issue": issue_key, "fields": sorted(payload),
            "url": f"{BASE}/browse/{issue_key}"}


if __name__ == "__main__":
    mcp.run()
