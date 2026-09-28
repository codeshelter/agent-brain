#!/usr/bin/env python3
"""
Nexus Repository MCP server (stdio) -- entrypoint.

Thin by design: all behaviour lives in the `nexus` package beside this file,
so the MCP client config never changes when tools are added or regrouped.
See nexus/_http.py for the environment variables this expects.

Registered by the agent-brain plugin (.mcp.json at the plugin root); credentials
come from the plugin's userConfig (`/plugin configure agent-brain`).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nexus.server import run  # noqa: E402

if __name__ == "__main__":
    run()
