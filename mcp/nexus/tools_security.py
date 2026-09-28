#!/usr/bin/env python3
"""Security administration: users, roles, privileges, realms, selectors, TLS."""
from __future__ import annotations

import json

from . import _capabilities as caps
from . import _http


def _obj(raw: str, argname: str) -> dict:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{argname} is not valid JSON: {exc}") from None
    if not isinstance(d, dict):
        raise RuntimeError(f"{argname} must be a JSON object")
    return d


def _arr(raw: str, argname: str) -> list:
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{argname} is not valid JSON: {exc}") from None
    if not isinstance(d, list):
        raise RuntimeError(f"{argname} must be a JSON array")
    return d


def register(mcp):

    # --- users --------------------------------------------------------------

    @mcp.tool()
    def nexus_list_users(user_id: str = "", source: str = "") -> dict:
        """List user accounts, optionally filtered by id or source (default, LDAP)."""
        users = _http.call("GET", "/v1/security/users",
                           params={"userId": user_id, "source": source}) or []
        return {"count": len(users), "users": [
            {"userId": u.get("userId"),
             "name": f"{u.get('firstName', '')} {u.get('lastName', '')}".strip(),
             "email": u.get("emailAddress"), "source": u.get("source"),
             "status": u.get("status"), "roles": u.get("roles")}
            for u in users]}

    @mcp.tool()
    def nexus_update_user(user_id: str, config: str, confirm: bool = False) -> dict:
        """Update a user account.

        config replaces the record wholesale -- read nexus_list_users first and
        send the full object back, or fields silently revert to defaults.
        """
        _http.require_confirm(confirm, f"replacing the record for user {user_id!r}")
        _http.call("PUT", f"/v1/security/users/{user_id}", _obj(config, "config"))
        return {"updated": True, "userId": user_id}

    @mcp.tool()
    def nexus_delete_user(user_id: str, confirm: bool = False) -> dict:
        """Delete a user account."""
        _http.require_confirm(confirm, f"deleting user {user_id!r}")
        _http.call("DELETE", f"/v1/security/users/{user_id}")
        return {"deleted": True, "userId": user_id}

    @mcp.tool()
    def nexus_list_user_sources() -> dict:
        """Configured user sources (local, LDAP, and so on)."""
        return {"sources": _http.call("GET", "/v1/security/user-sources")}

    # --- roles and privileges ----------------------------------------------

    @mcp.tool()
    def nexus_list_roles(source: str = "") -> dict:
        """List roles and the privileges each grants."""
        roles = _http.call("GET", "/v1/security/roles",
                           params={"source": source}) or []
        return {"count": len(roles), "roles": [
            {"id": r.get("id"), "name": r.get("name"),
             "description": r.get("description"),
             "privileges": r.get("privileges"), "roles": r.get("roles")}
            for r in roles]}

    @mcp.tool()
    def nexus_create_role(role_id: str, name: str, description: str = "",
                          privileges: str = "[]", roles: str = "[]") -> dict:
        """Create a role. privileges and roles are JSON arrays of ids."""
        _http.call("POST", "/v1/security/roles", {
            "id": role_id, "name": name, "description": description,
            "privileges": _arr(privileges, "privileges"),
            "roles": _arr(roles, "roles"),
        })
        return {"created": True, "id": role_id}

    @mcp.tool()
    def nexus_update_role(role_id: str, config: str, confirm: bool = False) -> dict:
        """Update a role. config replaces the record wholesale."""
        _http.require_confirm(confirm, f"replacing role {role_id!r}")
        _http.call("PUT", f"/v1/security/roles/{role_id}", _obj(config, "config"))
        return {"updated": True, "id": role_id}

    @mcp.tool()
    def nexus_delete_role(role_id: str, confirm: bool = False) -> dict:
        """Delete a role. Users holding it lose those permissions immediately."""
        _http.require_confirm(confirm, f"deleting role {role_id!r}")
        _http.call("DELETE", f"/v1/security/roles/{role_id}")
        return {"deleted": True, "id": role_id}

    @mcp.tool()
    def nexus_list_privileges() -> dict:
        """List privileges defined on this instance."""
        privs = _http.call("GET", "/v1/security/privileges") or []
        return {"count": len(privs), "privileges": [
            {"name": p.get("name"), "type": p.get("type"),
             "description": p.get("description"), "readOnly": p.get("readOnly")}
            for p in privs]}

    @mcp.tool()
    def nexus_create_privilege(privilege_type: str, config: str) -> dict:
        """Create a privilege.

        privilege_type  application, repository-admin, repository-view,
                        repository-content-selector, script or wildcard
        config          JSON object; its shape depends on the type. See
                        nexus_api_capabilities(search="privileges").
        """
        t = privilege_type.strip().lower()
        path = f"/v1/security/privileges/{t}"
        if not caps.has_path(path):
            raise RuntimeError(f"Unknown privilege type {t!r} on this build")
        cfg = _obj(config, "config")
        _http.call("POST", path, cfg)
        return {"created": True, "type": t, "name": cfg.get("name")}

    @mcp.tool()
    def nexus_delete_privilege(name: str, confirm: bool = False) -> dict:
        """Delete a privilege."""
        _http.require_confirm(confirm, f"deleting privilege {name!r}")
        _http.call("DELETE", f"/v1/security/privileges/{name}")
        return {"deleted": True, "name": name}

    # --- realms and anonymous access ---------------------------------------

    @mcp.tool()
    def nexus_get_realms() -> dict:
        """Active and available authentication realms, in precedence order."""
        return {"active": _http.call("GET", "/v1/security/realms/active"),
                "available": _http.call("GET", "/v1/security/realms/available")}

    @mcp.tool()
    def nexus_set_realms(realm_ids: str, confirm: bool = False) -> dict:
        """Set the active realms. realm_ids is an ordered JSON array.

        Gated: dropping the realm this server authenticates through locks it
        out, and the order determines authentication precedence.
        """
        _http.require_confirm(confirm, "changing the active authentication realms")
        ids = _arr(realm_ids, "realm_ids")
        _http.call("PUT", "/v1/security/realms/active", ids)
        return {"active": ids}

    @mcp.tool()
    def nexus_get_anonymous_access() -> dict:
        """Whether anonymous access is enabled, and as which account."""
        return _http.call("GET", "/v1/security/anonymous") or {}

    @mcp.tool()
    def nexus_set_anonymous_access(enabled: bool, user_id: str = "anonymous",
                                   realm_name: str = "NexusAuthorizingRealm",
                                   confirm: bool = False) -> dict:
        """Enable or disable anonymous access.

        Gated: enabling it exposes every repository this instance serves to
        unauthenticated readers.
        """
        state = "enabled" if enabled else "disabled"
        _http.require_confirm(confirm, f"setting anonymous access to {state}")
        return _http.call("PUT", "/v1/security/anonymous", {
            "enabled": bool(enabled), "userId": user_id, "realmName": realm_name,
        }) or {"enabled": bool(enabled)}

    # --- content selectors --------------------------------------------------

    @mcp.tool()
    def nexus_list_content_selectors() -> dict:
        """Content selectors -- the CSEL expressions used to scope privileges."""
        sels = _http.call("GET", "/v1/security/content-selectors") or []
        return {"count": len(sels), "selectors": sels}

    @mcp.tool()
    def nexus_create_content_selector(name: str, expression: str,
                                      description: str = "") -> dict:
        """Create a content selector.

        expression is CSEL, e.g.  format == "maven2" and path =^ "/com/idemia/"
        """
        _http.call("POST", "/v1/security/content-selectors",
                   {"name": name, "description": description,
                    "expression": expression})
        return {"created": True, "name": name}

    @mcp.tool()
    def nexus_update_content_selector(name: str, expression: str,
                                      description: str = "",
                                      confirm: bool = False) -> dict:
        """Update a content selector's expression.

        Gated: selectors gate repository access, so widening one grants
        permissions that were previously withheld.
        """
        _http.require_confirm(confirm, f"changing content selector {name!r}")
        _http.call("PUT", f"/v1/security/content-selectors/{name}",
                   {"description": description, "expression": expression})
        return {"updated": True, "name": name}

    @mcp.tool()
    def nexus_delete_content_selector(name: str, confirm: bool = False) -> dict:
        """Delete a content selector."""
        _http.require_confirm(confirm, f"deleting content selector {name!r}")
        _http.call("DELETE", f"/v1/security/content-selectors/{name}")
        return {"deleted": True, "name": name}

    # --- LDAP ---------------------------------------------------------------

    @mcp.tool()
    def nexus_list_ldap_servers() -> dict:
        """Configured LDAP servers, in connection order."""
        servers = _http.call("GET", "/v1/security/ldap") or []
        return {"count": len(servers), "servers": [
            {"name": s.get("name"), "host": s.get("host"), "port": s.get("port"),
             "protocol": s.get("protocol"), "searchBase": s.get("searchBase"),
             "authScheme": s.get("authScheme")} for s in servers]}

    @mcp.tool()
    def nexus_ldap_clear_cache(confirm: bool = False) -> dict:
        """Clear the LDAP cache, forcing a re-read of users and groups."""
        _http.require_confirm(confirm, "clearing the LDAP cache")
        _http.call("DELETE", "/v1/security/ldap/cache")
        return {"cleared": True}

    # --- TLS ----------------------------------------------------------------

    @mcp.tool()
    def nexus_get_remote_certificate(host: str, port: int = 443) -> dict:
        """Fetch the TLS certificate a remote host presents.

        Use this before trusting an upstream that a proxy repository will pull
        from.
        """
        return _http.call("GET", "/v1/security/ssl",
                          params={"host": host, "port": str(int(port))}) or {}

    @mcp.tool()
    def nexus_list_truststore() -> dict:
        """Certificates in the Nexus truststore, with expiry dates."""
        certs = _http.call("GET", "/v1/security/ssl/truststore") or []
        return {"count": len(certs), "certificates": [
            {"id": c.get("id"), "subject": c.get("subjectCommonName"),
             "issuer": c.get("issuerCommonName"),
             "expiresOn": c.get("expiresOn"), "fingerprint": c.get("fingerprint")}
            for c in certs]}

    @mcp.tool()
    def nexus_delete_truststore_certificate(cert_id: str,
                                            confirm: bool = False) -> dict:
        """Remove a certificate from the truststore.

        Gated: removing a CA that a proxy repository depends on breaks that
        repository's upstream connection.
        """
        _http.require_confirm(
            confirm, f"removing certificate {cert_id} from the truststore")
        _http.call("DELETE", f"/v1/security/ssl/truststore/{cert_id}")
        return {"deleted": True, "id": cert_id}
