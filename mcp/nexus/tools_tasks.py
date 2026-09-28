#!/usr/bin/env python3
"""Scheduled tasks: list, inspect, run, stop, wait."""
from __future__ import annotations

from . import _http
from . import _tasks

# Task types that destroy data or take the instance offline. Running one of
# these needs confirm=True; everything else (index rebuilds, health checks,
# metadata refreshes) is safe to trigger.
_DESTRUCTIVE_TYPES = {
    "blobstore.compact",
    "assetBlob.cleanup",
    "repository.cleanup",
    "repository.purge-unused",
    "repository.docker.upload-purge",
    "blobstore.rebuildComponentDB",
    "db.backup",
    "script",
}


def register(mcp):

    @mcp.tool()
    def nexus_list_tasks(task_type: str = "", state: str = "") -> dict:
        """Scheduled tasks on this instance.

        task_type filters by type, e.g. blobstore.compact, assetBlob.cleanup,
        healthcheck. state filters by current state, e.g. RUNNING, WAITING.
        """
        items = _tasks.list_tasks(task_type)
        if state:
            items = [t for t in items
                     if (t.get("currentState") or "").upper() == state.upper()]
        types: dict[str, int] = {}
        for t in _tasks.list_tasks():
            types[t.get("type") or "?"] = types.get(t.get("type") or "?", 0) + 1
        return {"returned": len(items), "types_present": dict(sorted(types.items())),
                "tasks": [_tasks.brief(t) for t in items]}

    @mcp.tool()
    def nexus_get_task(task_id: str) -> dict:
        """One task, including its last result and next scheduled run."""
        t = _tasks.get_task(task_id)
        out = _tasks.brief(t)
        out["properties"] = t.get("properties")
        return out

    @mcp.tool()
    def nexus_run_task(task_id: str, confirm: bool = False, wait: bool = False,
                       timeout_seconds: int = 600) -> dict:
        """Trigger a task now.

        Tasks that destroy data -- compaction, blob cleanup, repository cleanup
        -- require confirm=True. Safe tasks such as index rebuilds and health
        checks run without it.

        Set wait=True to poll until the task settles instead of returning as
        soon as it is triggered.
        """
        t = _tasks.get_task(task_id)
        if not t:
            raise RuntimeError(f"No task with id {task_id}")
        ttype = t.get("type") or ""
        if ttype in _DESTRUCTIVE_TYPES:
            _http.require_confirm(
                confirm, f"running task {t.get('name')!r} (type {ttype})")
        # Baseline before triggering -- a just-triggered task still reports the
        # previous run's result until the scheduler picks it up.
        baseline = t.get("lastRun")
        _tasks.run_task(task_id)
        out = {"triggered": True, "task": _tasks.brief(t),
               "previous_run": baseline}
        if wait:
            out["result"] = _tasks.wait_for(task_id, timeout_seconds,
                                            baseline_last_run=baseline)
            if out["result"].get("never_started"):
                out["note"] = out["result"]["note"]
            elif out["result"].get("timed_out"):
                out["note"] = (f"Still running after {timeout_seconds}s -- not a "
                               "failure. Poll nexus_get_task for progress.")
        return out

    @mcp.tool()
    def nexus_stop_task(task_id: str, confirm: bool = False) -> dict:
        """Stop a running task.

        Gated because stopping a half-finished compaction or cleanup leaves the
        blob store in a partially processed state.
        """
        _http.require_confirm(confirm, f"stopping task {task_id}")
        _http.call("POST", f"/v1/tasks/{task_id}/stop")
        return {"stopped": True, "task_id": task_id}

    @mcp.tool()
    def nexus_wait_task(task_id: str, timeout_seconds: int = 600) -> dict:
        """Poll a task until it finishes or the timeout expires.

        A timeout means "still running", not "failed".
        """
        return _tasks.wait_for(task_id, timeout_seconds)
