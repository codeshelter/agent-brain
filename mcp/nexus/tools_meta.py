#!/usr/bin/env python3
"""Identity, health, capability discovery, and the generic escape hatch."""
from __future__ import annotations

import json

from . import _capabilities as caps
from . import _http


def register(mcp):

    @mcp.tool()
    def nexus_whoami() -> dict:
        """Who the configured credentials authenticate as, and what they can do.

        Reports the auth mode in use, the account record if it is visible, and
        whether administrative endpoints actually answer -- which is a more
        honest privilege check than reading a role name.
        """
        out = {
            "url": _http.BASE,
            "auth_mode": _http.AUTH_MODE,
            "principal": _http.PRINCIPAL,
            "nexus_version": caps.version(),
        }
        try:
            users = _http.call("GET", "/v1/security/users",
                               params={"userId": _http.PRINCIPAL}) or []
            match = next((u for u in users
                          if u.get("userId") == _http.PRINCIPAL), None)
            if match:
                out["account"] = {
                    "userId": match.get("userId"),
                    "name": f"{match.get('firstName', '')} "
                            f"{match.get('lastName', '')}".strip(),
                    "email": match.get("emailAddress"),
                    "source": match.get("source"),
                    "status": match.get("status"),
                    "roles": match.get("roles"),
                }
            out["admin_endpoints_readable"] = True
        except _http.NexusError as exc:
            out["admin_endpoints_readable"] = False
            out["privilege_note"] = f"HTTP {exc.code} reading /v1/security/users"
        return out

    @mcp.tool()
    def nexus_status() -> dict:
        """Instance health: reachable, writable, and per-subsystem health checks."""
        out: dict = {"url": _http.BASE, "version": caps.version()}
        try:
            _http.call("GET", "/v1/status")
            out["available"] = True
        except _http.NexusError as exc:
            out["available"] = False
            out["error"] = str(exc)
            return out
        try:
            _http.call("GET", "/v1/status/writable")
            out["writable"] = True
        except _http.NexusError:
            out["writable"] = False
        try:
            checks = _http.call("GET", "/v1/status/check") or {}
            out["health_checks"] = {
                k: {"healthy": v.get("healthy"), "message": v.get("message")}
                for k, v in checks.items()
            }
            out["unhealthy"] = sorted(k for k, v in checks.items()
                                      if not v.get("healthy"))
        except _http.NexusError as exc:
            out["health_checks_error"] = str(exc)
        return out

    @mcp.tool()
    def nexus_api_capabilities(search: str = "", tag: str = "") -> dict:
        """What this exact Nexus build supports, read from its own OpenAPI spec.

        Use this before assuming a feature exists -- endpoints differ between
        versions and between Community and Pro. `search` matches path or
        summary text; `tag` filters to one API group.
        """
        ops = caps.operations()
        if tag:
            ops = [o for o in ops if any(tag.lower() in t.lower() for t in o["tags"])]
        if search:
            s = search.lower()
            ops = [o for o in ops
                   if s in o["path"].lower() or s in o["summary"].lower()]
        tags: dict[str, int] = {}
        for o in caps.operations():
            for t in o["tags"]:
                tags[t] = tags.get(t, 0) + 1
        return {
            "version": caps.version(),
            "total_operations": len(caps.operations()),
            "tags": dict(sorted(tags.items())),
            "matched": len(ops),
            "operations": ops[:200],
        }

    @mcp.tool()
    def nexus_api_call(method: str, path: str, body: str = "",
                       confirm: bool = False) -> dict:
        """Call any Nexus REST endpoint directly -- the escape hatch.

        For the long tail this server does not wrap in a typed tool (recovery
        mode, EULA, cipher, re-encryption, data-store, nodes, scripts). Check
        nexus_api_capabilities first for the exact path.

        method  GET, POST, PUT or DELETE
        path    relative to /service/rest, e.g. "/v1/status"
        body    JSON string; omit for GET
        confirm required True for anything other than GET, since a raw call
                bypasses every other guard in this server
        """
        m = method.strip().upper()
        if m not in ("GET", "POST", "PUT", "DELETE"):
            raise RuntimeError(f"Unsupported method {method!r}")
        if m != "GET":
            _http.require_confirm(confirm, f"raw {m} {path}")
        if not path.startswith("/"):
            path = "/" + path
        payload = None
        if body.strip():
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"body is not valid JSON: {exc}") from None
        result = _http.call(m, path, payload)
        return {"method": m, "path": path, "result": result}
