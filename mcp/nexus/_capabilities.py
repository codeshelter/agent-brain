#!/usr/bin/env python3
"""
Capability discovery.

Nexus publishes its own OpenAPI document at /service/rest/swagger.json. That
document is the authoritative list of what THIS build supports, so the server
reads it instead of hardcoding an endpoint list that goes stale on the next
upgrade. Two things depend on it:

  * nexus_api_capabilities -- shows the operator what this instance can do
  * the typed tools -- ask has_path() before calling a version-gated endpoint,
    so an unsupported feature reports "not available on this instance" rather
    than an opaque 404.

Fetched lazily on first use and cached for the life of the process; the spec
cannot change without a restart of Nexus itself.
"""
from __future__ import annotations

from . import _http

_spec: dict | None = None
_paths: set[str] | None = None


def spec() -> dict:
    """The instance's OpenAPI document, fetched once."""
    global _spec, _paths
    if _spec is None:
        _spec = _http.call("GET", "/swagger.json") or {}
        _paths = set((_spec.get("paths") or {}).keys())
    return _spec


def version() -> str:
    """Nexus version string, e.g. '3.92.0-03'.

    Taken from the OpenAPI info block. /v1/system/information does not exist
    on 3.92 (404), so this is the reliable source.
    """
    return (spec().get("info") or {}).get("version") or "unknown"


def has_path(path: str) -> bool:
    """Does this instance expose the given API path template?"""
    spec()
    return path in (_paths or set())


def require_path(path: str, feature: str) -> None:
    """Fail with an explanation, not a 404, when a feature is not on this build."""
    if not has_path(path):
        raise RuntimeError(
            f"{feature} is not available on this Nexus instance "
            f"(version {version()}; endpoint {path} is absent from its API). "
            "Run nexus_api_capabilities to see what this build does support.")


def operations() -> list[dict]:
    """Flatten the spec into one row per operation, for capability listings."""
    out = []
    for path, ops in sorted((spec().get("paths") or {}).items()):
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            out.append({
                "method": method.upper(),
                "path": path,
                "tags": op.get("tags") or [],
                "summary": op.get("summary") or op.get("operationId") or "",
            })
    return out
