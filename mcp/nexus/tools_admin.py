#!/usr/bin/env python3
"""
Instance administration: capabilities, routing rules, lifecycle, support,
firewall integration, malware findings, and usage metrics.
"""
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


def register(mcp):

    # --- capabilities -------------------------------------------------------

    @mcp.tool()
    def nexus_list_capabilities() -> dict:
        """Configured capabilities -- the pluggable features enabled on this
        instance (audit, outreach, index scheduling, and so on)."""
        items = _http.call("GET", "/v1/capabilities") or []
        return {"count": len(items), "capabilities": [
            {"id": c.get("id"), "type": c.get("type"), "enabled": c.get("enabled"),
             "active": c.get("active"), "notes": c.get("notes")} for c in items]}

    @mcp.tool()
    def nexus_capability_types() -> dict:
        """Capability types this build offers, with what each is for."""
        types = _http.call("GET", "/v1/capabilities/types") or []
        return {"count": len(types), "types": [
            {"id": t.get("id"), "name": t.get("name"), "about": t.get("about")}
            for t in types]}

    @mcp.tool()
    def nexus_create_capability(config: str) -> dict:
        """Create a capability.

        config is a JSON object with at least
        {"type": "...", "enabled": true, "properties": {...}}.
        """
        return {"created": _http.call("POST", "/v1/capabilities",
                                      _obj(config, "config"))}

    @mcp.tool()
    def nexus_update_capability(capability_id: str, config: str,
                                confirm: bool = False) -> dict:
        """Update a capability. config replaces it wholesale."""
        _http.require_confirm(confirm, f"replacing capability {capability_id}")
        return {"updated": _http.call("PUT", f"/v1/capabilities/{capability_id}",
                                      _obj(config, "config"))}

    @mcp.tool()
    def nexus_delete_capability(capability_id: str, confirm: bool = False) -> dict:
        """Delete a capability."""
        _http.require_confirm(confirm, f"deleting capability {capability_id}")
        _http.call("DELETE", f"/v1/capabilities/{capability_id}")
        return {"deleted": True, "id": capability_id}

    # --- routing rules ------------------------------------------------------

    @mcp.tool()
    def nexus_list_routing_rules() -> dict:
        """Routing rules -- the allow/block path filters applied to proxies."""
        rules = _http.call("GET", "/v1/routing-rules") or []
        return {"count": len(rules), "rules": rules}

    @mcp.tool()
    def nexus_create_routing_rule(name: str, mode: str, matchers: str,
                                  description: str = "") -> dict:
        """Create a routing rule.

        mode      BLOCK or ALLOW
        matchers  JSON array of regex strings matched against request paths
        """
        try:
            m = json.loads(matchers)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"matchers is not valid JSON: {exc}") from None
        if not isinstance(m, list):
            raise RuntimeError("matchers must be a JSON array")
        _http.call("POST", "/v1/routing-rules",
                   {"name": name, "description": description,
                    "mode": mode.upper(), "matchers": m})
        return {"created": True, "name": name, "mode": mode.upper()}

    @mcp.tool()
    def nexus_delete_routing_rule(name: str, confirm: bool = False) -> dict:
        """Delete a routing rule.

        Gated: removing a BLOCK rule immediately re-exposes the paths it was
        holding back.
        """
        _http.require_confirm(confirm, f"deleting routing rule {name!r}")
        _http.call("DELETE", f"/v1/routing-rules/{name}")
        return {"deleted": True, "name": name}

    # --- lifecycle ----------------------------------------------------------

    @mcp.tool()
    def nexus_get_lifecycle_phase() -> dict:
        """Current lifecycle phase.

        On this build, read-only mode is expressed as a lifecycle phase rather
        than through the older /v1/read-only endpoints, which are absent.
        """
        return {"phase": _http.call_text("GET", "/v1/lifecycle/phase")}

    @mcp.tool()
    def nexus_set_lifecycle_phase(phase: str, confirm: bool = False) -> dict:
        """Move the instance to a lifecycle phase.

        Heavily gated: phases such as OFF or STORAGE take Nexus out of service
        for every client using it, not just this session.
        """
        _http.require_confirm(
            confirm, f"moving this Nexus instance to lifecycle phase {phase!r} "
                     "(affects every user of the server)")
        _http.call_text("PUT", "/v1/lifecycle/phase", phase)
        return {"phase": phase}

    @mcp.tool()
    def nexus_bounce_lifecycle(phase: str, confirm: bool = False) -> dict:
        """Bounce the instance down to a phase and back up. Service-affecting."""
        _http.require_confirm(
            confirm, f"bouncing this Nexus instance through phase {phase!r} "
                     "(interrupts service for every user)")
        _http.call_text("PUT", "/v1/lifecycle/bounce", phase)
        return {"bounced_through": phase}

    # --- support ------------------------------------------------------------

    @mcp.tool()
    def nexus_support_zip(options: str = "") -> dict:
        """Generate a support zip on the server and return its path.

        options is a JSON object, e.g. {"systemInformation": true, "log": true,
        "metrics": true, "configuration": true, "limitFileSizes": true}.
        The result contains configuration and log contents -- treat it as
        sensitive and do not copy it somewhere less protected.
        """
        opts = _obj(options, "options") if options.strip() else {
            "systemInformation": True, "threadDump": True, "metrics": True,
            "configuration": True, "log": True, "limitFileSizes": True,
            "limitZipSize": True,
        }
        return {"support_zip": _http.call("POST", "/v1/support/supportzippath", opts),
                "note": "Contains configuration and logs -- handle as sensitive."}

    # --- firewall / IQ ------------------------------------------------------

    @mcp.tool()
    def nexus_iq_status() -> dict:
        """Sonatype Repository Firewall (IQ Server) integration status."""
        return {"configuration": _http.call("GET", "/v1/iq"),
                "capabilities": _http.call("GET", "/v1/iq/capabilities")}

    @mcp.tool()
    def nexus_iq_verify_connection() -> dict:
        """Test the configured IQ Server connection."""
        return {"result": _http.call("POST", "/v1/iq/verify-connection")}

    @mcp.tool()
    def nexus_iq_set_enabled(enabled: bool, confirm: bool = False) -> dict:
        """Enable or disable the firewall integration.

        Gated: disabling it stops policy enforcement on proxied components.
        """
        _http.require_confirm(
            confirm, f"{'enabling' if enabled else 'disabling'} the Repository "
                     "Firewall integration")
        _http.call("POST", "/v1/iq/enable" if enabled else "/v1/iq/disable")
        return {"firewall_enabled": bool(enabled)}

    # --- malicious risk on disk --------------------------------------------

    @mcp.tool()
    def nexus_malicious_risk() -> dict:
        """Malware risk summary for components already stored on this instance.

        This build scans what is on disk, not only what passes through a proxy,
        so findings here are artifacts you are currently hosting.
        """
        caps.require_path("/v1/malicious-risk/risk-on-disk", "Malicious Risk On Disk")
        return {
            "risk_on_disk": _http.call("GET", "/v1/malicious-risk/risk-on-disk"),
            "enabled_registries": _http.call("GET",
                                             "/v1/malicious-risk/enabledRegistries"),
        }

    @mcp.tool()
    def nexus_malicious_findings(limit: int = 50) -> dict:
        """Active malware findings, and the components they attach to."""
        caps.require_path("/v1/malicious-risk/active-findings",
                          "Malicious Risk On Disk")
        return {
            "active_findings": _http.call("GET",
                                          "/v1/malicious-risk/active-findings"),
            "components": _http.call("GET", "/v1/malicious-risk/components",
                                     params={"limit": str(int(limit))}),
        }

    @mcp.tool()
    def nexus_malicious_acknowledge(finding_id: str, confirm: bool = False) -> dict:
        """Acknowledge a malware finding, marking it reviewed.

        Gated: acknowledging suppresses the alert without removing the
        artifact, so it should be a deliberate decision, not a tidy-up.
        """
        caps.require_path("/v1/malicious-risk/acknowledge/{id}",
                          "Malicious Risk On Disk")
        _http.require_confirm(
            confirm, f"acknowledging malware finding {finding_id} "
                     "(suppresses the alert; the artifact stays on disk)")
        _http.call("POST", f"/v1/malicious-risk/acknowledge/{finding_id}")
        return {"acknowledged": True, "id": finding_id}

    @mcp.tool()
    def nexus_malicious_remediate(payload: str = "{}",
                                  confirm: bool = False) -> dict:
        """Remediate malware findings -- this removes the offending components.

        Check nexus_api_capabilities(search="malicious-risk") for the payload
        shape this build expects.
        """
        caps.require_path("/v1/malicious-risk/remediate", "Malicious Risk On Disk")
        _http.require_confirm(
            confirm,
            "remediating malware findings (deletes the affected components)")
        return {"result": _http.call("POST", "/v1/malicious-risk/remediate",
                                     _obj(payload, "payload"))}

    # --- metrics and configuration -----------------------------------------

    @mcp.tool()
    def nexus_usage_metrics() -> dict:
        """Usage history and monthly metrics -- request volume, component counts."""
        out: dict = {}
        for key, path in (("monthly_metrics", "/v1/monthly-metrics"),
                          ("usage_history", "/v1/usage-history")):
            try:
                out[key] = _http.call("GET", path)
            except _http.NexusError as exc:
                out[key] = f"unavailable (HTTP {exc.code})"
        return out

    @mcp.tool()
    def nexus_instance_configuration() -> dict:
        """Instance-level configuration this build exposes over REST."""
        caps.require_path("/v1/configuration", "Instance configuration")
        return _http.call("GET", "/v1/configuration") or {}

    @mcp.tool()
    def nexus_email_settings() -> dict:
        """SMTP configuration used for notifications."""
        return _http.call("GET", "/v1/email") or {}
