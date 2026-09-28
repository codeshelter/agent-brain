#!/usr/bin/env python3
"""Read side: repositories, components, assets, search, download."""
from __future__ import annotations

import hashlib
import json
import os

from . import _capabilities as caps
from . import _http


def _asset_brief(a: dict) -> dict:
    """Trim an asset to the fields worth spending context on."""
    checks = a.get("checksum") or {}
    return {
        "id": a.get("id"),
        "path": a.get("path"),
        "repository": a.get("repository"),
        "format": a.get("format"),
        "size": a.get("fileSize"),
        "size_human": _http.human_bytes(a.get("fileSize")),
        "last_modified": a.get("lastModified"),
        "last_downloaded": a.get("lastDownloaded"),
        "sha1": checks.get("sha1"),
        "downloadUrl": a.get("downloadUrl"),
    }


def _component_brief(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "group": c.get("group"),
        "name": c.get("name"),
        "version": c.get("version"),
        "repository": c.get("repository"),
        "format": c.get("format"),
        "assets": [_asset_brief(a) for a in (c.get("assets") or [])],
    }


def register(mcp):

    # --- repositories -------------------------------------------------------

    @mcp.tool()
    def nexus_list_repositories(format: str = "", type: str = "") -> dict:
        """List repositories. Optionally filter by format (maven2, raw, npm...)
        or type (hosted, proxy, group)."""
        repos = _http.call("GET", "/v1/repositories") or []
        if format:
            repos = [r for r in repos
                     if (r.get("format") or "").lower() == format.lower()]
        if type:
            repos = [r for r in repos
                     if (r.get("type") or "").lower() == type.lower()]
        return {
            "count": len(repos),
            "repositories": [
                {"name": r.get("name"), "format": r.get("format"),
                 "type": r.get("type"), "url": r.get("url"),
                 "attributes": r.get("attributes")}
                for r in sorted(repos, key=lambda r: (r.get("format") or "",
                                                      r.get("name") or ""))
            ],
        }

    @mcp.tool()
    def nexus_get_repository(name: str) -> dict:
        """Full configuration of one repository: storage, cleanup, proxy settings."""
        return _http.call("GET", f"/v1/repositories/{name}") or {}

    @mcp.tool()
    def nexus_browse_repository(name: str) -> dict:
        """Browse a repository's tree as the UI shows it."""
        caps.require_path("/v1/repositories/{repositoryName}/browse",
                          "Repository browse")
        return {"repository": name,
                "browse": _http.call("GET", f"/v1/repositories/{name}/browse")}

    # --- components and assets ---------------------------------------------

    @mcp.tool()
    def nexus_list_components(repository: str, limit: int = 50) -> dict:
        """List components in one repository. Paging is handled internally."""
        items = _http.paged("/v1/components", {"repository": repository},
                            limit=int(limit))
        return {"repository": repository, "returned": len(items),
                "components": [_component_brief(c) for c in items]}

    @mcp.tool()
    def nexus_get_component(component_id: str) -> dict:
        """One component by its Nexus id, with all of its assets."""
        return _component_brief(_http.call("GET", f"/v1/components/{component_id}") or {})

    @mcp.tool()
    def nexus_list_assets(repository: str, limit: int = 50) -> dict:
        """List assets (individual files) in one repository."""
        items = _http.paged("/v1/assets", {"repository": repository},
                            limit=int(limit))
        return {"repository": repository, "returned": len(items),
                "assets": [_asset_brief(a) for a in items]}

    @mcp.tool()
    def nexus_get_asset(asset_id: str) -> dict:
        """One asset by its Nexus id, including checksums and download URL."""
        a = _http.call("GET", f"/v1/assets/{asset_id}") or {}
        out = _asset_brief(a)
        out["checksums"] = a.get("checksum")
        out["content_type"] = a.get("contentType")
        out["uploader"] = a.get("uploader")
        out["blobCreated"] = a.get("blobCreated")
        return out

    # --- search -------------------------------------------------------------

    @mcp.tool()
    def nexus_search_components(q: str = "", repository: str = "", format: str = "",
                                group: str = "", name: str = "", version: str = "",
                                prerelease: str = "", sha1: str = "",
                                sort: str = "", direction: str = "",
                                extra_params: str = "", limit: int = 50) -> dict:
        """Search components across repositories.

        q            free-text keyword
        sort         group, name, version, repository or, by default, relevance
        direction    asc or desc
        extra_params JSON object of format-specific filters, e.g.
                     {"maven.artifactId": "commons-io", "maven.extension": "jar"}
        """
        params = {"q": q, "repository": repository, "format": format,
                  "group": group, "name": name, "version": version,
                  "prerelease": prerelease, "sha1": sha1,
                  "sort": sort, "direction": direction}
        params.update(_parse_extra(extra_params))
        items = _http.paged("/v1/search", params, limit=int(limit))
        return {"returned": len(items),
                "components": [_component_brief(c) for c in items]}

    @mcp.tool()
    def nexus_search_assets(q: str = "", repository: str = "", format: str = "",
                            group: str = "", name: str = "", version: str = "",
                            sha1: str = "", sort: str = "", direction: str = "",
                            extra_params: str = "", limit: int = 50) -> dict:
        """Search individual assets (files) rather than components."""
        params = {"q": q, "repository": repository, "format": format,
                  "group": group, "name": name, "version": version, "sha1": sha1,
                  "sort": sort, "direction": direction}
        params.update(_parse_extra(extra_params))
        items = _http.paged("/v1/search/assets", params, limit=int(limit))
        return {"returned": len(items), "assets": [_asset_brief(a) for a in items]}

    @mcp.tool()
    def nexus_search_suggest(q: str) -> dict:
        """Autocomplete-style suggestions for a partial search term."""
        caps.require_path("/v1/search/suggest", "Search suggest")
        return {"query": q, "suggestions": _http.call("GET", "/v1/search/suggest",
                                                      params={"q": q})}

    # --- download -----------------------------------------------------------

    @mcp.tool()
    def nexus_download_asset(dest_path: str, asset_id: str = "",
                             download_url: str = "") -> dict:
        """Download one asset to a local file.

        Give either asset_id (preferred -- the checksum is then verified
        against what Nexus recorded) or a direct download_url.
        """
        if not asset_id and not download_url:
            raise RuntimeError("Give either asset_id or download_url")
        expected_sha1 = None
        if asset_id:
            a = _http.call("GET", f"/v1/assets/{asset_id}") or {}
            download_url = a.get("downloadUrl") or ""
            expected_sha1 = (a.get("checksum") or {}).get("sha1")
            if not download_url:
                raise RuntimeError(f"Asset {asset_id} has no downloadUrl")

        content = _http.call_bytes("GET", download_url)
        parent = os.path.dirname(os.path.abspath(dest_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest_path, "wb") as fh:
            fh.write(content)

        got = hashlib.sha1(content).hexdigest()
        out = {"path": os.path.abspath(dest_path), "bytes": len(content),
               "size_human": _http.human_bytes(len(content)), "sha1": got,
               "source": download_url}
        if expected_sha1:
            out["sha1_verified"] = (got == expected_sha1)
            if got != expected_sha1:
                out["warning"] = (f"sha1 mismatch: Nexus recorded {expected_sha1}, "
                                  f"downloaded bytes hash to {got}")
        return out


def _parse_extra(extra_params: str) -> dict:
    """Format-specific search filters, supplied as a JSON object string."""
    if not extra_params.strip():
        return {}
    try:
        d = json.loads(extra_params)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"extra_params is not valid JSON: {exc}") from None
    if not isinstance(d, dict):
        raise RuntimeError("extra_params must be a JSON object")
    return {str(k): str(v) for k, v in d.items()}
