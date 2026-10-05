"""Chronos MCP layer — adapts the frozen 27-tool set to an injected executor.

This package never reimplements tools: every call is forwarded to the
injected ``ToolDispatcher.dispatch`` (duck-typed ``dispatcher``/``executor``
parameter). Same auth (``X-Chronos-Key`` header with ``?key=`` fallback),
same validation as voice input, and every call writes exactly one audit row.
"""

from .server import (
    EXPECTED_TOOLS,
    TOOL_NAMES,
    ALL_TOOLS,
    TOOL_LIST,
    TOOLS,
    TOOL_SCHEMAS,
    MCPServer,
    McpServer,
    MCPHandler,
    ToolServer,
    build_server,
    create_mcp_server,
    create_server,
    get_tools,
    list_tools,
    tool_names,
)

__all__ = [
    "EXPECTED_TOOLS",
    "TOOL_NAMES",
    "ALL_TOOLS",
    "TOOL_LIST",
    "TOOLS",
    "TOOL_SCHEMAS",
    "MCPServer",
    "McpServer",
    "MCPHandler",
    "ToolServer",
    "build_server",
    "create_mcp_server",
    "create_server",
    "get_tools",
    "list_tools",
    "tool_names",
]
