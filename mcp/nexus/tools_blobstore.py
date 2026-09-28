#!/usr/bin/env python3
"""
Blob store management -- including making the reported numbers reflect reality.

Worth understanding before using these tools: deleting a component or asset in
Nexus does NOT free disk space. It marks the blob soft-deleted. Disk usage,
blob counts and quota status only catch up when the `blobstore.compact` task
runs. That is why a blob store can report a total size far larger than the sum
of its live assets -- and why blobCount can even go negative when the recorded
count and the blobs on disk have drifted apart.

So the order of operations that actually reclaims space is:
    1. delete the components/assets you no longer want
    2. nexus_blobstore_compact  -- reclaims the soft-deleted blobs
    3. nexus_list_blobstores    -- re-read the now-truthful numbers

If the counts are drifted rather than merely stale, reconciliation is the
repair path: see nexus_reconcile_plan_*, which drives this build's /v1/plan
API.
"""
from __future__ import annotations

import json

from . import _capabilities as caps
from . import _http
from . import _tasks

_COMPACT_TASK = "blobstore.compact"


def _blobstore_brief(b: dict) -> dict:
    count = b.get("blobCount")
    total = b.get("totalSizeInBytes")
    avail = b.get("availableSpaceInBytes")
    out = {
        "name": b.get("name"),
        "type": b.get("type"),
        "unavailable": b.get("unavailable"),
        "blobCount": count,
        "totalSize": _http.human_bytes(total),
        "totalSizeInBytes": total,
        "availableSpace": _http.human_bytes(avail),
        "availableSpaceInBytes": avail,
        "softQuota": b.get("softQuota"),
    }
    notes = []
    if isinstance(count, int) and count < 0:
        notes.append(
            f"blobCount is negative ({count}). The recorded count has drifted "
            "from what is on disk -- the reported figures are NOT trustworthy. "
            "Run nexus_blobstore_compact, and if that does not settle it, "
            "reconcile with nexus_reconcile_plan_create.")
    quota = b.get("softQuota") or {}
    if quota.get("type") == "spaceRemainingQuota" and isinstance(avail, int):
        limit = quota.get("limit")
        if isinstance(limit, int) and avail < limit:
            notes.append(
                f"soft quota breached: {_http.human_bytes(avail)} remaining is "
                f"below the {_http.human_bytes(limit)} limit.")
    if quota.get("type") == "spaceUsedQuota" and isinstance(total, int):
        limit = quota.get("limit")
        if isinstance(limit, int) and total > limit:
            notes.append(
                f"soft quota breached: {_http.human_bytes(total)} used exceeds "
                f"the {_http.human_bytes(limit)} limit.")
    if notes:
        out["warnings"] = notes
    return out


def _parse_config(raw: str, argname: str) -> dict:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{argname} is not valid JSON: {exc}") from None
    if not isinstance(d, dict):
        raise RuntimeError(f"{argname} must be a JSON object")
    return d


def register(mcp):

    # --- inspection ---------------------------------------------------------

    @mcp.tool()
    def nexus_list_blobstores() -> dict:
        """All blob stores with size, count and quota, plus honesty warnings.

        Flags a negative blob count or a breached soft quota rather than
        reporting the raw numbers as if they were reliable.
        """
        stores = _http.call("GET", "/v1/blobstores") or []
        return {"count": len(stores),
                "blobstores": [_blobstore_brief(b) for b in stores]}

    @mcp.tool()
    def nexus_get_blobstore(name: str, type: str = "file") -> dict:
        """Full configuration of one blob store.

        type is file, s3, azure, google or group -- Nexus exposes a separate
        endpoint per backing type.
        """
        t = type.strip().lower()
        path = f"/v1/blobstores/{t}/{name}"
        caps.require_path(f"/v1/blobstores/{t}/{{name}}", f"{t} blob stores")
        return _http.call("GET", path) or {}

    @mcp.tool()
    def nexus_blobstore_quota_status(name: str) -> dict:
        """Whether a blob store is within its soft quota, and by how much."""
        d = _http.call("GET", f"/v1/blobstores/{name}/quota-status") or {}
        return {
            "name": d.get("blobStoreName", name),
            "quota_breached": d.get("isViolation"),
            "message": d.get("message"),
        }

    # --- the "reflect real data" path ---------------------------------------

    @mcp.tool()
    def nexus_blobstore_compact(name: str = "default", confirm: bool = False,
                                wait: bool = True,
                                timeout_seconds: int = 900) -> dict:
        """Reclaim soft-deleted blobs so disk usage reflects live content.

        This is the step that makes deletions real. Nexus only frees space when
        the compact task runs; until then, deleted artifacts still occupy disk
        and the reported totals stay inflated.

        Runs the existing `blobstore.compact` task for this blob store. Marked
        destructive because the space it reclaims is not recoverable -- the
        soft-deleted blobs are gone for good afterwards.
        """
        _http.require_confirm(
            confirm, f"compacting blob store {name!r} (permanently discards "
                     "soft-deleted blobs)")
        candidates = _tasks.find_by_type(_COMPACT_TASK, name)
        if not candidates:
            raise RuntimeError(
                f"No {_COMPACT_TASK} task exists for blob store {name!r}. "
                "Nexus has no REST endpoint to create a task, so create one in "
                "the UI (Administration -> System -> Tasks -> Admin - Compact "
                "blob store), then call this tool again.")
        task = candidates[0]
        before = next((b for b in (_http.call("GET", "/v1/blobstores") or [])
                       if b.get("name") == name), {})
        # Capture lastRun BEFORE triggering. A freshly triggered task keeps
        # reporting the previous run's state and result until the scheduler
        # picks it up, so this baseline is the only reliable way to tell a new
        # run's completion from a stale one.
        baseline = _tasks.get_task(task["id"]).get("lastRun")
        _tasks.run_task(task["id"])
        out = {
            "blobstore": name,
            "task": {"id": task.get("id"), "name": task.get("name")},
            "triggered": True,
            "previous_run": baseline,
            "before": _blobstore_brief(before) if before else None,
        }
        if not wait:
            out["note"] = ("Compaction runs in the background. Re-read "
                           "nexus_list_blobstores later to see the settled size. "
                           f"A new run has completed once lastRun differs from "
                           f"{baseline}.")
            return out
        out["result"] = _tasks.wait_for(task["id"], timeout_seconds,
                                        baseline_last_run=baseline)
        after = next((b for b in (_http.call("GET", "/v1/blobstores") or [])
                      if b.get("name") == name), {})
        out["after"] = _blobstore_brief(after) if after else None
        if before and after:
            freed = (before.get("totalSizeInBytes") or 0) - (after.get("totalSizeInBytes") or 0)
            out["reclaimed"] = _http.human_bytes(freed)
        if out["result"].get("never_started"):
            out["note"] = out["result"]["note"]
            out["reclaimed"] = "nothing -- the run did not happen"
        elif out["result"].get("timed_out"):
            out["note"] = (f"Still running after {timeout_seconds}s. This is not "
                           "a failure -- large blob stores take a while. Check "
                           "nexus_get_task for progress.")
        return out

    @mcp.tool()
    def nexus_reconcile_plan_list() -> dict:
        """Existing blob store reconciliation plans.

        Reconciliation rebuilds the metadata Nexus holds about a blob store
        from the blobs actually on disk. It is the repair path when counts have
        drifted rather than merely gone stale -- a negative blobCount being the
        clearest symptom.
        """
        caps.require_path("/v1/plan", "Reconcile plans")
        return {"plans": _http.call("GET", "/v1/plan"),
                "details": _http.call("GET", "/v1/plan/details")}

    @mcp.tool()
    def nexus_reconcile_plan_get(plan_id: str) -> dict:
        """One reconciliation plan by id."""
        caps.require_path("/v1/plan/{planId}", "Reconcile plans")
        return _http.call("GET", f"/v1/plan/{plan_id}") or {}

    @mcp.tool()
    def nexus_reconcile_plan_details(plan_id: str = "", state: str = "",
                                     repository: str = "") -> dict:
        """Line-by-line detail of what a reconciliation plan covers.

        Read this before executing anything -- it is the only way to see what a
        plan would touch.
        """
        caps.require_path("/v1/plan/details", "Reconcile plans")
        return _http.call("GET", "/v1/plan/details",
                          params={"planId": plan_id, "state": state,
                                  "repository": repository}) or {}

    @mcp.tool()
    def nexus_reconcile_plan_create(blob_stores: str = "", repositories: str = "",
                                    since_days: int = 0, since_hours: int = 0,
                                    since_minutes: int = 0, start_date: str = "",
                                    end_date: str = "",
                                    confirm: bool = False) -> dict:
        """Create a reconciliation plan, scoped by blob store, repository and time.

        Takes QUERY parameters, not a JSON body -- Nexus is unusual here.

        IMPORTANT: this is not a dry run. This build's API documents the 204
        response as "Reconciliation plans created AND EXECUTED", so creating a
        plan can immediately rewrite blob store metadata. It is gated for that
        reason. Narrow the scope with a time window (since_days / since_hours)
        rather than reconciling an entire blob store's history in one go.

        blob_stores   comma-separated names, e.g. "default"
        repositories  comma-separated names; omit for all
        since_*       look back this far; combine or use start_date/end_date
        start_date    ISO date, e.g. "2026-09-01"
        """
        caps.require_path("/v1/plan", "Reconcile plans")
        window = (since_days or since_hours or since_minutes
                  or start_date or end_date)
        _http.require_confirm(
            confirm,
            "creating a reconciliation plan"
            + (f" scoped to blobStores={blob_stores or 'ALL'}"
               f" repositories={repositories or 'ALL'}")
            + (" -- with NO time window, so it covers the blob store's entire "
               "history" if not window else "")
            + ". This build executes plans on creation, rewriting blob store "
              "metadata")
        params = {"blobStores": blob_stores, "repositories": repositories,
                  "startDate": start_date, "endDate": end_date}
        for key, val in (("sinceDays", since_days), ("sinceHours", since_hours),
                         ("sinceMinutes", since_minutes)):
            if val:
                params[key] = str(int(val))
        try:
            result = _http.call("POST", "/v1/plan", params=params)
        except _http.NexusError as exc:
            if "planReconciliation" in exc.detail:
                # The endpoint exists, but it drives a scheduled task that this
                # instance does not have. Nexus has no REST route to create a
                # task, so this cannot be fixed from here.
                raise RuntimeError(
                    "Reconciliation is unavailable: this instance has no "
                    "'blobstore.planReconciliation' task, and Nexus exposes no "
                    "REST endpoint to create one. Create it in the UI first "
                    "(Administration -> System -> Tasks -> Create task -> "
                    "'Reconcile blob store' / 'Repair - Reconcile component "
                    "database from blob store'), then call this tool again. "
                    "Run nexus_list_tasks(task_type='blobstore.planReconciliation') "
                    "to confirm once it exists.") from None
            raise
        return {"created": True, "scope": {k: v for k, v in params.items() if v},
                "response": result,
                "note": "Re-read nexus_reconcile_plan_list and "
                        "nexus_list_blobstores to see the effect."}

    @mcp.tool()
    def nexus_reconcile_plan_execute(plan_id: str = "",
                                     confirm: bool = False) -> dict:
        """Execute a reconciliation plan that has not yet run.

        With plan_id, executes that one plan; without it, executes EVERY
        non-executed plan. Rewrites blob store metadata, so it is gated.
        """
        caps.require_path("/v1/plan", "Reconcile plans")
        target = f"plan {plan_id}" if plan_id else "ALL non-executed plans"
        _http.require_confirm(
            confirm, f"executing {target} (rewrites blob store metadata)")
        path = f"/v1/plan/{plan_id}" if plan_id else "/v1/plan"
        return {"executed": target, "response": _http.call("PUT", path)}

    @mcp.tool()
    def nexus_reconcile_plan_delete(plan_id: str = "", confirm: bool = False) -> dict:
        """Delete a reconciliation plan (all plans if plan_id is omitted)."""
        caps.require_path("/v1/plan", "Reconcile plans")
        target = f"plan {plan_id}" if plan_id else "ALL reconciliation plans"
        _http.require_confirm(confirm, f"deleting {target}")
        path = f"/v1/plan/{plan_id}" if plan_id else "/v1/plan"
        _http.call("DELETE", path)
        return {"deleted": target}

    # --- lifecycle ----------------------------------------------------------

    @mcp.tool()
    def nexus_create_blobstore(type: str, config: str) -> dict:
        """Create a blob store.

        type    file, s3, azure, google or group
        config  JSON object, e.g. {"name": "builds", "path": "/nexus/blobs/builds"}
                for file, or {"name": "grp", "members": ["a","b"],
                "fillPolicy": "writeToFirst"} for group. Run
                nexus_api_capabilities(search="blobstores") for the schema.
        """
        t = type.strip().lower()
        caps.require_path(f"/v1/blobstores/{t}", f"{t} blob stores")
        _http.call("POST", f"/v1/blobstores/{t}", _parse_config(config, "config"))
        return {"created": True, "type": t,
                "name": _parse_config(config, "config").get("name")}

    @mcp.tool()
    def nexus_update_blobstore(type: str, name: str, config: str,
                               confirm: bool = False) -> dict:
        """Update a blob store's configuration.

        Gated: changing the path or backing store of a live blob store can
        orphan every artifact in it.
        """
        t = type.strip().lower()
        caps.require_path(f"/v1/blobstores/{t}/{{name}}", f"{t} blob stores")
        _http.require_confirm(confirm, f"reconfiguring blob store {name!r}")
        _http.call("PUT", f"/v1/blobstores/{t}/{name}", _parse_config(config, "config"))
        return {"updated": True, "type": t, "name": name}

    @mcp.tool()
    def nexus_delete_blobstore(name: str, confirm: bool = False) -> dict:
        """Delete a blob store.

        Nexus refuses if any repository still uses it. Every artifact stored in
        it becomes unreachable, so this is gated.
        """
        _http.require_confirm(confirm, f"deleting blob store {name!r}")
        _http.call("DELETE", f"/v1/blobstores/{name}")
        return {"deleted": True, "name": name}

    @mcp.tool()
    def nexus_blobstore_group_convert(name: str, new_name_for_original: str,
                                      confirm: bool = False) -> dict:
        """Convert an existing blob store into a group, keeping it as a member.

        The original is renamed to new_name_for_original and becomes the first
        member of a new group that takes over its old name.
        """
        caps.require_path("/v1/blobstores/group/convert/{name}/{newNameForOriginal}",
                          "Blob store group conversion")
        _http.require_confirm(confirm, f"converting blob store {name!r} to a group")
        _http.call("POST",
                   f"/v1/blobstores/group/convert/{name}/{new_name_for_original}")
        return {"converted": True, "group_name": name,
                "original_renamed_to": new_name_for_original}
