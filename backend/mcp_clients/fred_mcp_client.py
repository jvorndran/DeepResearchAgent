"""
FRED MCP Client for DeepAgents

This module provides utilities to connect to the Federal Reserve Economic Data (FRED)
MCP server using langchain_mcp_adapters for DeepAgents integration.

The FRED MCP server provides tools for accessing macroeconomic series such as GDP,
CPI, interest rates, employment data, and more.

Uses stdio transport to avoid the HTTP GET stream reconnection loop that occurs with
the streamable_http transport when the server holds an idle SSE connection open.
Auth is passed to the subprocess via the FRED_API_KEY environment variable.

Tools: fred_browse, fred_search, fred_get_series
"""

import os
from typing import Optional, Dict, Any, List
from langchain_mcp_adapters.client import MultiServerMCPClient

# Default path to the pre-built FRED MCP server JS bundle (sibling project)
_DEFAULT_FRED_SERVER_PATH = os.path.expanduser("~/projects/fred-mcp-server/build/index.js")


def get_fred_mcp_config(server_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the FRED MCP server configuration for MultiServerMCPClient.

    Uses stdio transport to avoid HTTP GET stream reconnection noise.
    The FRED server is invoked as a Node.js subprocess; FRED_API_KEY is
    passed explicitly through the subprocess environment.

    Args:
        server_path: Path to the FRED MCP server JS bundle.
                     Defaults to FRED_MCP_SERVER_PATH env var or the
                     sibling project default path.

    Returns:
        Configuration dict for MultiServerMCPClient
    """
    path = server_path or os.getenv("FRED_MCP_SERVER_PATH", _DEFAULT_FRED_SERVER_PATH)
    fred_api_key = os.getenv("FRED_API_KEY", "")
    return {
        "fred": {
            "transport": "stdio",
            "command": "node",
            "args": [path],
            "env": {
                "FRED_API_KEY": fred_api_key,
            },
        }
    }


async def create_fred_mcp_client(server_path: Optional[str] = None) -> MultiServerMCPClient:
    """
    Create and initialize a FRED MCP client for DeepAgents.

    Args:
        server_path: Path to the FRED MCP server JS bundle (optional)

    Returns:
        Initialized MultiServerMCPClient with FRED tools
    """
    config = get_fred_mcp_config(server_path)
    return MultiServerMCPClient(config)


async def list_fred_tools(server_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all available tools from the FRED MCP server.

    Args:
        server_path: Path to the FRED MCP server JS bundle (optional)

    Returns:
        List of tool definitions with name and description
    """
    client = await create_fred_mcp_client(server_path)
    tools = await client.get_tools()
    return [{"name": t.name, "description": t.description} for t in tools]
