#!/usr/bin/env python3
"""
HTTP + auth layer for the Nexus MCP server.

Written in-house for the same reason redmine_mcp.py was: the credentials
reach an instance that hosts real release artifacts, so they only ever go
to code we can read. Standard library only -- no third-party HTTP client.

Config via environment:
    NEXUS_URL          e.g. https://nexus.example.internal

    Authentication -- pick ONE. NEXUS_AUTH_TYPE forces a mode; leave it
    unset to auto-detect (user token wins if one is present).

    NEXUS_AUTH_TYPE    "basic" or "token"; optional
    -- basic mode (ordinary Nexus login) --
    NEXUS_USERNAME     Nexus account name
    NEXUS_PASSWORD     that account's password
    -- token mode (Nexus user token: Account -> User Token) --
    NEXUS_USER_TOKEN         the token name part
    NEXUS_USER_TOKEN_PASS    the token pass part

    Both modes end as an HTTP Basic header -- that is how Nexus user tokens
    are actually presented -- so switching later is a config edit, not a
    rewrite.

    NEXUS_CA_BUNDLE    optional PEM bundle, if the corporate CA is not
                       already in the system trust store. Confirmed NOT
                       needed when the server certificate validates
                       against the system trust store.
    NEXUS_SSL_VERIFY   escape hatch only; "false" disables certificate
                       checking. Prefer NEXUS_CA_BUNDLE if trust ever breaks.
    NEXUS_TIMEOUT      per-request timeout in seconds (default 60)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("NEXUS_URL", "").rstrip("/")
if not BASE:
    raise SystemExit("NEXUS_URL must be set")

API = BASE + "/service/rest"
TIMEOUT = float(os.environ.get("NEXUS_TIMEOUT", "60"))
VERIFY = os.environ.get("NEXUS_SSL_VERIFY", "true").lower() not in ("false", "0", "no")

_AUTH_TYPE = os.environ.get("NEXUS_AUTH_TYPE", "").strip().lower()
_USERNAME = os.environ.get("NEXUS_USERNAME", "")
_PASSWORD = os.environ.get("NEXUS_PASSWORD", "")
_TOKEN = os.environ.get("NEXUS_USER_TOKEN", "")
_TOKEN_PASS = os.environ.get("NEXUS_USER_TOKEN_PASS", "")


def _resolve_auth() -> tuple[str, str, str]:
    """Return (mode, principal, Basic header value).

    Resolved once at import so a misconfiguration fails loudly at startup
    rather than as a 401 on the first tool call. Presence is tested on the
    stripped value, so a whitespace-only placeholder in the MCP config counts
    as "not set" and does not half-arm a mode; the secret itself is sent
    unstripped, because a password may legitimately end in a space.
    """
    has_login = bool(_USERNAME.strip() and _PASSWORD.strip())
    has_token = bool(_TOKEN.strip() and _TOKEN_PASS.strip())

    if _AUTH_TYPE == "basic":
        if not has_login:
            raise SystemExit(
                "NEXUS_AUTH_TYPE=basic requires both NEXUS_USERNAME and NEXUS_PASSWORD")
        mode, user, secret = "basic", _USERNAME.strip(), _PASSWORD
    elif _AUTH_TYPE in ("token", "usertoken"):
        if not has_token:
            raise SystemExit(
                f"NEXUS_AUTH_TYPE={_AUTH_TYPE} requires both NEXUS_USER_TOKEN and "
                "NEXUS_USER_TOKEN_PASS")
        mode, user, secret = "token", _TOKEN.strip(), _TOKEN_PASS
    elif _AUTH_TYPE:
        raise SystemExit(
            f"NEXUS_AUTH_TYPE must be 'basic' or 'token', got {_AUTH_TYPE!r}")
    elif has_token:
        mode, user, secret = "token", _TOKEN.strip(), _TOKEN_PASS
    elif has_login:
        mode, user, secret = "basic", _USERNAME.strip(), _PASSWORD
    else:
        raise SystemExit(
            "No Nexus credentials found. Set NEXUS_USERNAME and NEXUS_PASSWORD "
            "for login auth, or NEXUS_USER_TOKEN and NEXUS_USER_TOKEN_PASS for "
            "user-token auth. Force a mode with NEXUS_AUTH_TYPE=basic|token.")

    pair = f"{user}:{secret}".encode()
    return mode, user, "Basic " + base64.b64encode(pair).decode("ascii")


AUTH_MODE, PRINCIPAL, _AUTH_HEADER = _resolve_auth()

_CTX = ssl.create_default_context(cafile=os.environ.get("NEXUS_CA_BUNDLE") or None)
if not VERIFY:
    # Last resort. Leaves the connection open to interception; only reachable
    # by explicitly setting NEXUS_SSL_VERIFY=false.
    import sys as _sys
    print("WARNING: Nexus TLS verification disabled (NEXUS_SSL_VERIFY=false)",
          file=_sys.stderr)
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


class NexusError(RuntimeError):
    """An HTTP error from Nexus, with the response body attached."""

    def __init__(self, method: str, path: str, code: int, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"Nexus {method} {path} -> HTTP {code}: {detail}")


def _request(method: str, url: str, data: bytes | None = None,
             content_type: str | None = None,
             accept: str = "application/json") -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _AUTH_HEADER)
    # Not every endpoint speaks JSON -- /v1/lifecycle/phase returns text/plain
    # and answers 406 to a JSON-only Accept header.
    req.add_header("Accept", accept)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, context=_CTX, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        shown = url[len(API):] if url.startswith(API) else url
        raise NexusError(method, shown, exc.code, detail) from None


def call(method: str, path: str, payload=None, params: dict | None = None):
    """One JSON call against /service/rest. Returns None for empty bodies.

    `path` is relative to /service/rest, e.g. "/v1/repositories".
    """
    url = API + path
    if params:
        clean = {k: v for k, v in params.items() if v not in ("", None)}
        if clean:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
    data = json.dumps(payload).encode() if payload is not None else None
    _, body = _request(method, url, data, "application/json" if data else None)
    text = body.decode(errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:2000]}


def call_bytes(method: str, path_or_url: str) -> bytes:
    """Fetch raw bytes -- asset downloads, which are not JSON."""
    url = path_or_url if path_or_url.startswith("http") else API + path_or_url
    _, body = _request(method, url, accept="*/*")
    return body


def call_text(method: str, path: str, payload: str | None = None) -> str:
    """Call an endpoint that speaks text/plain rather than JSON.

    Nexus is not uniform here: the lifecycle endpoints take and return a bare
    phase name as plain text, and reject a JSON-only Accept header with 406.
    """
    data = payload.encode() if payload is not None else None
    _, body = _request(method, API + path, data,
                       "text/plain" if data else None, accept="text/plain")
    return body.decode(errors="replace").strip()


def paged(path: str, params: dict | None = None, limit: int = 100,
          item_key: str = "items") -> list:
    """Follow Nexus continuationToken paging until `limit` items or exhaustion.

    Nexus pages at a fixed server-side size and the token is opaque. We stop
    as soon as we have enough, so a limit of 20 against a 90k-component repo
    costs one or two calls, not a full walk.
    """
    out: list = []
    token = None
    seen: set[str] = set()
    while True:
        p = dict(params or {})
        if token:
            p["continuationToken"] = token
        d = call("GET", path, params=p) or {}
        items = d.get(item_key) or []
        out.extend(items)
        token = d.get("continuationToken")
        if not token or len(out) >= limit or not items:
            break
        if token in seen:      # defensive: never loop on a repeated token
            break
        seen.add(token)
    return out[:limit]


def multipart(path: str, fields: dict[str, str],
              files: list[tuple[str, str, bytes]], params: dict | None = None):
    """POST a multipart/form-data body (component upload).

    fields -- plain form fields, e.g. {"raw.directory": "/x",
              "raw.asset1.filename": "a.txt"}
    files  -- list of (field_name, filename, content)
    """
    boundary = "----NexusMCP" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode())
    for name, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    url = API + path
    if params:
        clean = {k: v for k, v in params.items() if v not in ("", None)}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    status, resp = _request("POST", url, body,
                            f"multipart/form-data; boundary={boundary}")
    text = resp.decode(errors="replace").strip()
    return {"status": status, "response": text[:1000] if text else "(empty)"}


def human_bytes(n) -> str:
    """Render a byte count the way an operator reads it."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return str(n)
    sign = "-" if v < 0 else ""
    v = abs(v)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if v < 1024 or unit == "PiB":
            return f"{sign}{v:.0f} B" if unit == "B" else f"{sign}{v:.1f} {unit}"
        v /= 1024
    return f"{sign}{v:.1f} PiB"


def require_confirm(confirm: bool, action: str) -> None:
    """Gate every irreversible operation.

    Full admin rights were granted deliberately, but a mis-parsed instruction
    should not be able to delete artifacts. Destructive tools route through
    here rather than trusting the caller.
    """
    if not confirm:
        raise RuntimeError(
            f"Refused: {action} is destructive and requires confirm=True. "
            "Re-issue with confirm=True once you have verified the target.")
