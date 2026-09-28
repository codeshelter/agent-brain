#!/usr/bin/env python3
"""
Shared task helpers.

Several "make the numbers reflect reality" operations are not endpoints at
all -- they are scheduled tasks you trigger and then wait on. Blob store
compaction is the main one. Both the task tools and the blob store tools need
to find, run and poll tasks, so that logic lives here rather than in either.
"""
from __future__ import annotations

import time

from . import _http


def list_tasks(task_type: str = "") -> list[dict]:
    d = _http.call("GET", "/v1/tasks", params={"type": task_type or None}) or {}
    return d.get("items") or []


def brief(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "type": t.get("type"),
        "state": t.get("currentState"),
        "last_run": t.get("lastRun"),
        "last_run_result": t.get("lastRunResult"),
        "next_run": t.get("nextRun"),
        "message": t.get("message"),
    }


def get_task(task_id: str) -> dict:
    return _http.call("GET", f"/v1/tasks/{task_id}") or {}


def run_task(task_id: str) -> None:
    _http.call("POST", f"/v1/tasks/{task_id}/run")


_RUNNING_STATES = ("RUNNING", "RUNNING_BLOCKED", "RUNNING_STARTING",
                   "RUNNING_CANCELED")


def wait_for(task_id: str, timeout_seconds: int = 900, poll_seconds: int = 5,
             baseline_last_run: str | None = None,
             start_grace_seconds: int = 60) -> dict:
    """Poll a task until the run identified by `baseline_last_run` completes.

    The naive version of this is wrong, and wrong in a way that silently
    reports success: a task you have just triggered still reads WAITING with
    the PREVIOUS run's lastRunResult until the scheduler picks it up. Treating
    that as "finished" returns an OK that belongs to an earlier run.

    So completion is judged by `lastRun` CHANGING from the value captured
    before the trigger -- not by state alone, and not by lastRunResult alone.

    baseline_last_run   the task's lastRun before it was triggered; pass None
                        to simply wait for any current run to finish
    start_grace_seconds how long to allow for the scheduler to pick the task
                        up before concluding it never started
    """
    deadline = time.time() + max(1, int(timeout_seconds))
    start = time.time()
    last = get_task(task_id)
    ever_ran = False

    while time.time() < deadline:
        last = get_task(task_id)
        state = (last.get("currentState") or "").upper()
        current_last_run = last.get("lastRun")

        if state in _RUNNING_STATES:
            ever_ran = True
            time.sleep(poll_seconds)
            continue

        if baseline_last_run is None:
            # No baseline to compare against: settled once it is not running.
            break

        if current_last_run and current_last_run != baseline_last_run:
            break      # a NEW run completed -- this is the real success case

        if not ever_ran and (time.time() - start) > start_grace_seconds:
            out = brief(last)
            out["timed_out"] = False
            out["never_started"] = True
            out["note"] = (
                f"The task was triggered but did not start within "
                f"{start_grace_seconds}s and lastRun is unchanged "
                f"({baseline_last_run}). Nexus accepted the run request without "
                "acting on it -- the task may be disabled, already queued behind "
                "another, or blocked by a concurrently running task.")
            return out

        time.sleep(poll_seconds)

    out = brief(last)
    out["timed_out"] = time.time() >= deadline
    out["completed_new_run"] = bool(
        baseline_last_run is not None
        and last.get("lastRun")
        and last.get("lastRun") != baseline_last_run)
    return out


def find_by_type(task_type: str, blobstore_name: str = "") -> list[dict]:
    """Tasks of a type, optionally narrowed to ones bound to a blob store."""
    found = [t for t in list_tasks() if t.get("type") == task_type]
    if blobstore_name:
        narrowed = []
        for t in found:
            # The task list does not always expose its properties, so match on
            # the name too -- Nexus names these "Compact <blobstore> - auto".
            blob = ((t.get("properties") or {}).get("blobstoreName")
                    or (t.get("properties") or {}).get("blobstore") or "")
            if blob == blobstore_name or blobstore_name in (t.get("name") or ""):
                narrowed.append(t)
        if narrowed:
            return narrowed
    return found
