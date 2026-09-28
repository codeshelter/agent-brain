#!/usr/bin/env python3
"""
Repository administration and content deletion.

This build exposes 179 repository endpoints -- 24 formats times hosted/proxy/
group, plus the shared operations. Wrapping each as its own tool would add
nothing but noise, because they differ only in the JSON body they accept. So
create/update take format and type as arguments and validate the pair against
the instance's own OpenAPI document, which keeps the tool correct across
upgrades that add new formats.
"""
from __future__ import annotations

import json

from . import _capabilities as caps
from . import _http


def _parse_config(raw: str) -> dict:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"config is not valid JSON: {exc}") from None
    if not isinstance(d, dict):
        raise RuntimeError("config must be a JSON object")
    return d


def _known_format_types() -> dict[str, list[str]]:
    """Format -> repository types this instance actually supports."""
    out: dict[str, list[str]] = {}
    for op in caps.operations():
        parts = op["path"].strip("/").split("/")
        # /v1/repositories/{format}/{type}
        if (len(parts) == 4 and parts[0] == "v1" and parts[1] == "repositories"
                and not parts[2].startswith("{") and not parts[3].startswith("{")):
            out.setdefault(parts[2], [])
            if parts[3] not in out[parts[2]]:
                out[parts[2]].append(parts[3])
    return {k: sorted(v) for k, v in sorted(out.items())}


def register(mcp):

    @mcp.tool()
    def nexus_repository_formats() -> dict:
        """Which repository formats and types this instance can create.

        Read from the instance's own API document, so it stays accurate when an
        upgrade adds a format.
        """
        ft = _known_format_types()
        return {"version": caps.version(), "formats": ft,
                "count": sum(len(v) for v in ft.values())}

    @mcp.tool()
    def nexus_create_repository(format: str, type: str, config: str) -> dict:
        """Create a repository.

        format  maven, raw, npm, nuget, pypi, docker, apt, yum, helm, go, r,
                conan, conda, cargo, terraform, swift, pub, huggingface, ...
                (nexus_repository_formats lists what this build supports)
        type    hosted, proxy or group
        config  JSON object. Minimum for a hosted repo:
                {"name": "my-repo",
                 "online": true,
                 "storage": {"blobStoreName": "default",
                             "strictContentTypeValidation": true,
                             "writePolicy": "ALLOW"}}
                A proxy also needs "proxy": {"remoteUrl": "..."}; a group needs
                "group": {"memberNames": [...]}.

        Note maven repositories use format "maven" on this endpoint even though
        components report format "maven2".
        """
        f, t = format.strip().lower(), type.strip().lower()
        path = f"/v1/repositories/{f}/{t}"
        if not caps.has_path(path):
            raise RuntimeError(
                f"This Nexus build has no {f}/{t} repository endpoint. "
                f"Supported: {json.dumps(_known_format_types())}")
        cfg = _parse_config(config)
        _http.call("POST", path, cfg)
        return {"created": True, "name": cfg.get("name"), "format": f, "type": t}

    @mcp.tool()
    def nexus_update_repository(format: str, type: str, name: str,
                                config: str, confirm: bool = False) -> dict:
        """Update a repository's configuration.

        Gated: the body replaces the existing configuration wholesale, so a
        partial config silently drops settings. Read nexus_get_repository
        first, edit that, and send the whole thing back.
        """
        f, t = format.strip().lower(), type.strip().lower()
        path = f"/v1/repositories/{f}/{t}/{{repositoryName}}"
        if not caps.has_path(path):
            raise RuntimeError(f"This Nexus build has no {f}/{t} repository endpoint")
        _http.require_confirm(
            confirm, f"replacing the configuration of repository {name!r}")
        _http.call("PUT", f"/v1/repositories/{f}/{t}/{name}", _parse_config(config))
        return {"updated": True, "name": name, "format": f, "type": t}

    @mcp.tool()
    def nexus_delete_repository(name: str, confirm: bool = False) -> dict:
        """Delete a repository and everything in it."""
        _http.require_confirm(
            confirm, f"deleting repository {name!r} and all of its contents")
        _http.call("DELETE", f"/v1/repositories/{name}")
        return {"deleted": True, "name": name,
                "note": "Disk space is not freed until the blob store is "
                        "compacted -- see nexus_blobstore_compact."}

    @mcp.tool()
    def nexus_invalidate_cache(name: str) -> dict:
        """Invalidate a proxy repository's cache of upstream content."""
        _http.call("POST", f"/v1/repositories/{name}/invalidate-cache")
        return {"invalidated": True, "repository": name}

    @mcp.tool()
    def nexus_rebuild_index(name: str) -> dict:
        """Rebuild a repository's search index.

        The fix when search results disagree with what the repository actually
        contains.
        """
        _http.call("POST", f"/v1/repositories/{name}/rebuild-index")
        return {"rebuild_scheduled": True, "repository": name}

    @mcp.tool()
    def nexus_repository_health_check(name: str, enable: bool,
                                      confirm: bool = False) -> dict:
        """Enable or disable the remote health check on a proxy repository."""
        if enable:
            _http.call("POST", f"/v1/repositories/{name}/health-check")
        else:
            _http.require_confirm(
                confirm, f"disabling the health check on {name!r}")
            _http.call("DELETE", f"/v1/repositories/{name}/health-check")
        return {"repository": name, "health_check_enabled": bool(enable)}

    # --- content deletion ---------------------------------------------------

    @mcp.tool()
    def nexus_delete_component(component_id: str, confirm: bool = False) -> dict:
        """Delete one component and all of its assets."""
        _http.require_confirm(confirm, f"deleting component {component_id}")
        _http.call("DELETE", f"/v1/components/{component_id}")
        return {"deleted": True, "component_id": component_id,
                "note": "Space is reclaimed only after nexus_blobstore_compact."}

    @mcp.tool()
    def nexus_delete_asset(asset_id: str, confirm: bool = False) -> dict:
        """Delete one asset (a single file within a component)."""
        _http.require_confirm(confirm, f"deleting asset {asset_id}")
        _http.call("DELETE", f"/v1/assets/{asset_id}")
        return {"deleted": True, "asset_id": asset_id,
                "note": "Space is reclaimed only after nexus_blobstore_compact."}
