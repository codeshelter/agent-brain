#!/usr/bin/env python3
"""
Component upload.

Nexus describes its own upload contract at /v1/formats/upload-specs: for every
format it supports, which component-level fields and which per-asset fields it
expects, and which of them are required. This module reads that contract and
builds the multipart body from it, rather than hardcoding a format list that
would go stale the next time a format is added.

The wire convention Nexus expects:
    component field   ->  "<format>.<fieldName>"        e.g. raw.directory
    asset file        ->  "<format>.asset<N>"           e.g. raw.asset1
    asset field       ->  "<format>.asset<N>.<field>"   e.g. raw.asset1.filename

Not every format can be uploaded this way. Docker in particular has no REST
upload -- images must be pushed with `docker push` to the repository's connector
port. The tools below say so plainly instead of failing with a bare 400.
"""
from __future__ import annotations

import json
import os

from . import _http

_specs_cache: list | None = None

# Formats that exist as repositories but that the components API cannot accept
# an upload for. Sourced from the upload-specs document itself: any format with
# no entry there is push-only.
_PUSH_ONLY_HINT = {
    "docker": "use `docker push` against the repository's connector port",
    "cocoapods": "proxy-only format; upstream publishes it",
    "p2": "proxy-only format; upstream publishes it",
    "composer": "proxy-only format; upstream publishes it",
    "cargo": "publish with `cargo publish`",
    "gitlfs": "pushed by the git-lfs client",
}


def _specs() -> list:
    global _specs_cache
    if _specs_cache is None:
        _specs_cache = _http.call("GET", "/v1/formats/upload-specs") or []
    return _specs_cache


def _spec_for(fmt: str) -> dict:
    for s in _specs():
        if (s.get("format") or "").lower() == fmt.lower():
            return s
    known = sorted(s.get("format") for s in _specs() if s.get("format"))
    hint = _PUSH_ONLY_HINT.get(fmt.lower())
    extra = f" {fmt} cannot be uploaded through the REST API -- {hint}." if hint else ""
    raise RuntimeError(
        f"This Nexus instance accepts no REST upload for format {fmt!r}.{extra} "
        f"Formats it does accept: {', '.join(known)}")


def _check_required(spec: dict, fmt: str, component_fields: dict,
                    assets: list[dict]) -> None:
    """Validate against the server's own contract, so errors name the field."""
    missing = [f["name"] for f in (spec.get("componentFields") or [])
               if not f.get("optional") and f["name"] not in component_fields]
    if missing:
        raise RuntimeError(
            f"Missing required component field(s) for {fmt}: {', '.join(missing)}. "
            f"Run nexus_upload_specs(format='{fmt}') for the full contract.")
    # FILE-typed asset fields are the uploaded file itself, carried as the
    # multipart file part rather than as a text field, so they are satisfied by
    # file_path and must not be demanded in `fields`.
    required_asset = [f["name"] for f in (spec.get("assetFields") or [])
                      if not f.get("optional")
                      and (f.get("type") or "").upper() != "FILE"]
    for i, a in enumerate(assets, 1):
        absent = [n for n in required_asset if n not in (a.get("fields") or {})]
        if absent:
            raise RuntimeError(
                f"Asset {i} is missing required field(s) for {fmt}: "
                f"{', '.join(absent)}")


def _upload(repository: str, fmt: str, component_fields: dict,
            assets: list[dict]) -> dict:
    spec = _spec_for(fmt)
    if len(assets) > 1 and not spec.get("multipleUpload"):
        raise RuntimeError(f"Format {fmt} accepts only one asset per upload")
    _check_required(spec, fmt, component_fields, assets)

    fields: dict[str, str] = {f"{fmt}.{k}": str(v)
                              for k, v in component_fields.items()}
    files: list[tuple[str, str, bytes]] = []
    for i, a in enumerate(assets, 1):
        path = a["file_path"]
        if not os.path.isfile(path):
            raise RuntimeError(f"No such file: {path}")
        with open(path, "rb") as fh:
            content = fh.read()
        files.append((f"{fmt}.asset{i}", os.path.basename(path), content))
        for k, v in (a.get("fields") or {}).items():
            fields[f"{fmt}.asset{i}.{k}"] = str(v)

    result = _http.multipart("/v1/components", fields, files,
                             params={"repository": repository})
    return {
        "uploaded": result["status"] in (200, 201, 204),
        "http_status": result["status"],
        "repository": repository,
        "format": fmt,
        "component_fields": component_fields,
        "assets": [{"file": os.path.basename(a["file_path"]),
                    "bytes": os.path.getsize(a["file_path"]),
                    "fields": a.get("fields") or {}} for a in assets],
        "response": result["response"],
    }


def _parse_json_arg(raw: str, argname: str, default):
    if not raw.strip():
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{argname} is not valid JSON: {exc}") from None


def register(mcp):

    @mcp.tool()
    def nexus_upload_specs(format: str = "") -> dict:
        """What this instance accepts on upload, per format.

        Call this before nexus_upload_component to see the exact field names
        and which are required. With no argument, lists every supported format.
        """
        if not format:
            return {
                "formats": sorted(s.get("format") for s in _specs() if s.get("format")),
                "note": "Call again with a format to see its required fields. "
                        "Formats absent from this list cannot be uploaded over "
                        "REST -- docker needs `docker push`, cargo needs "
                        "`cargo publish`, and proxy-only formats are published "
                        "upstream.",
            }
        spec = _spec_for(format)

        def shape(fs):
            return [{"name": f.get("name"), "type": f.get("type"),
                     "required": not f.get("optional"),
                     "description": f.get("description")} for f in (fs or [])]

        return {
            "format": spec.get("format"),
            "multiple_assets_allowed": spec.get("multipleUpload"),
            "component_fields": shape(spec.get("componentFields")),
            "asset_fields": shape(spec.get("assetFields")),
        }

    @mcp.tool()
    def nexus_upload_component(repository: str, format: str,
                               component_fields: str = "{}",
                               assets: str = "[]") -> dict:
        """Upload a component of any REST-uploadable format.

        Driven by the server's own upload contract, so it works for every
        format this instance supports -- including ones added by a later
        upgrade.

        component_fields  JSON object, e.g. {"directory": "/builds/2026"}
                          or {"groupId": "com.idemia", "artifactId": "hsm",
                              "version": "1.2.0"}
        assets            JSON array of {"file_path": "...", "fields": {...}},
                          e.g. [{"file_path": "C:/tmp/a.jar",
                                 "fields": {"extension": "jar"}}]

        Run nexus_upload_specs(format=...) first if unsure of the field names.
        """
        cf = _parse_json_arg(component_fields, "component_fields", {})
        av = _parse_json_arg(assets, "assets", [])
        if not isinstance(cf, dict):
            raise RuntimeError("component_fields must be a JSON object")
        if not isinstance(av, list) or not av:
            raise RuntimeError("assets must be a non-empty JSON array")
        for a in av:
            if not isinstance(a, dict) or "file_path" not in a:
                raise RuntimeError("each asset needs a file_path")
        return _upload(repository, format.lower(), cf, av)

    @mcp.tool()
    def nexus_upload_raw(repository: str, file_path: str, directory: str = "/",
                         filename: str = "") -> dict:
        """Upload one file to a raw repository. Convenience wrapper.

        directory is the destination path inside the repository; filename
        defaults to the local file's own name.
        """
        return _upload(repository, "raw", {"directory": directory},
                       [{"file_path": file_path,
                         "fields": {"filename": filename or os.path.basename(file_path)}}])

    @mcp.tool()
    def nexus_upload_maven(repository: str, file_path: str, group_id: str,
                           artifact_id: str, version: str, extension: str = "",
                           classifier: str = "", packaging: str = "",
                           generate_pom: bool = False) -> dict:
        """Upload one artifact to a maven2 repository. Convenience wrapper.

        extension defaults to the local file's suffix (jar, pom, war...).
        """
        ext = extension or os.path.splitext(file_path)[1].lstrip(".")
        if not ext:
            raise RuntimeError("Cannot infer extension; pass extension explicitly")
        component: dict = {"groupId": group_id, "artifactId": artifact_id,
                           "version": version}
        if packaging:
            component["packaging"] = packaging
        if generate_pom:
            component["generate-pom"] = "true"
        asset_fields: dict = {"extension": ext}
        if classifier:
            asset_fields["classifier"] = classifier
        return _upload(repository, "maven2", component,
                       [{"file_path": file_path, "fields": asset_fields}])
