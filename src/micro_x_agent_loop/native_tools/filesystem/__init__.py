"""Native in-process filesystem tools (port of the TypeScript filesystem
MCP server). See ADR-025.

Built in phases; F1 = the PathPolicy foundation (paths.py). Tools are
added in later phases and registered via build_filesystem_tools().
"""

from __future__ import annotations
