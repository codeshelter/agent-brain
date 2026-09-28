#!/usr/bin/env python3
"""
Assembles the Nexus MCP server from its tool modules.

Modules register onto one shared FastMCP instance. The registry below is
deliberately tolerant: a module that is absent is skipped with a note on
stderr rather than taking the whole server down, so a partial install still
gives you every tool it does have.
"""
from __future__ import annotations

import importlib
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nexus")

# Order is presentational only -- it groups related tools together.
_MODULES = (
    "tools_meta",        # identity, health, capability discovery, escape hatch
    "tools_browse",      # repositories, components, assets, search, download
    "tools_upload",      # spec-driven component upload
    "tools_repoadmin",   # repository lifecycle, cache/index, content deletion
    "tools_blobstore",   # blob stores, quota, compaction, reconciliation
    "tools_tasks",       # scheduled tasks
    "tools_security",    # users, roles, privileges, realms, selectors, TLS
    "tools_admin",       # capabilities, routing, lifecycle, firewall, metrics
)

LOADED: list[str] = []
MISSING: list[str] = []

for name in _MODULES:
    try:
        mod = importlib.import_module(f".{name}", __package__)
    except ImportError:
        MISSING.append(name)
        print(f"nexus-mcp: module {name} not installed; its tools are unavailable",
              file=sys.stderr)
        continue
    mod.register(mcp)
    LOADED.append(name)


def run() -> None:
    mcp.run()
