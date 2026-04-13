"""
FRED MCP Client for DeepAgents

This module provides utilities to connect to the Federal Reserve Economic Data (FRED)
MCP server using langchain_mcp_adapters for DeepAgents integration.

The FRED MCP server provides tools for accessing macroeconomic series such as GDP,
CPI, interest rates, employment data, and more. Auth is handled server-side via the
FRED_API_KEY environment variable on the Node.js process — not in the HTTP request.

Tools: fred_browse, fred_search, fred_get_series
"""

import os
from typing import Optional, Dict, Any, List
from langchain_mcp_adapters.client import MultiServerMCPClient


def get_fred_mcp_config(server_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the FRED MCP server configuration for MultiServerMCPClient.

    Args:
        server_url: URL of the FRED MCP server. Defaults to FRED_MCP_URL env var
                    or http://localhost:3000/mcp

    Returns:
        Configuration dict for MultiServerMCPClient
    """
    url = server_url or os.getenv("FRED_MCP_URL", "http://localhost:3000/mcp")
    return {
        "fred": {
            "transport": "streamable_http",
            "url": url,
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            },
            "timeout": 10,          # local server — fail fast if unreachable (seconds)
            "sse_read_timeout": 60, # FRED API calls are faster than FMP (seconds)
            "terminate_on_close": False, # Prevents 400 errors on session close
        }
    }


async def create_fred_mcp_client(server_url: Optional[str] = None) -> MultiServerMCPClient:
    """
    Create and initialize a FRED MCP client for DeepAgents.

    Args:
        server_url: URL of the FRED MCP server (optional, uses env var if not provided)

    Returns:
        Initialized MultiServerMCPClient with FRED tools
    """
    config = get_fred_mcp_config(server_url)
    return MultiServerMCPClient(config)


async def list_fred_tools(server_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all available tools from the FRED MCP server.

    Args:
        server_url: Custom server URL (optional)

    Returns:
        List of tool definitions with name and description
    """
    client = await create_fred_mcp_client(server_url)
    tools = await client.get_tools()
    return [{"name": t.name, "description": t.description} for t in tools]
