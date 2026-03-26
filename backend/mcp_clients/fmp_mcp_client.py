"""
FMP MCP Client for DeepAgents

This module provides utilities to connect to the Financial Modeling Prep (FMP)
MCP server using langchain_mcp_adapters for DeepAgents integration.

The FMP MCP server provides 250+ financial data tools via the Model Context Protocol.
"""

import os
import uuid
from typing import Optional, Dict, Any, List
from langchain_mcp_adapters.client import MultiServerMCPClient
import base64
import json


def get_fmp_mcp_config(
    api_token: Optional[str] = None,
    server_url: Optional[str] = None,
    use_hosted: bool = True,
    client_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get the FMP MCP server configuration for MultiServerMCPClient.

    Args:
        api_token: FMP API token. If not provided, will look for FMP_ACCESS_TOKEN env var
        server_url: URL of the FMP MCP server. Defaults to hosted instance if use_hosted=True
        use_hosted: Whether to use the hosted FMP MCP server (default: True)

    Returns:
        Configuration dict for MultiServerMCPClient

    Raises:
        ValueError: If FMP_ACCESS_TOKEN is not provided
    """
    api_token = api_token or os.getenv("FMP_ACCESS_TOKEN")
    if not api_token:
        raise ValueError(
            "FMP_ACCESS_TOKEN not provided. Please set it as an environment variable "
            "or pass it to the constructor. Get your API key from "
            "https://financialmodelingprep.com/developer/docs"
        )

    # Determine server URL
    if server_url:
        url = server_url
    elif use_hosted:
        url = "https://financial-modeling-prep-mcp-server-production.up.railway.app/mcp"
    else:
        url = "http://localhost:8080/mcp"

    # Encode configuration for the FMP server
    # The FMP MCP server expects the API token in session config
    session_config = {"FMP_ACCESS_TOKEN": api_token}
    config_base64 = base64.b64encode(json.dumps(session_config).encode()).decode()

    # Add config to URL as query parameter
    url_with_config = f"{url}?config={config_base64}"

    # mcp-client-id is required for session persistence on the hosted server.
    # Without it each request is anonymous (not cached) → "Session not found" errors.
    cid = client_id or str(uuid.uuid4())

    return {
        "fmp": {
            "transport": "streamable_http",
            "url": url_with_config,
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "mcp-client-id": cid,
            }
        }
    }


async def create_fmp_mcp_client(
    api_token: Optional[str] = None,
    server_url: Optional[str] = None,
    use_hosted: bool = True,
    client_id: Optional[str] = None,
) -> MultiServerMCPClient:
    """
    Create and initialize an FMP MCP client for DeepAgents.

    Usage:
        async def main():
        Initialized MultiServerMCPClient with FMP tools
    """
    config = get_fmp_mcp_config(api_token, server_url, use_hosted, client_id)
    client = MultiServerMCPClient(config)
    return client


async def list_fmp_tools(
    api_token: Optional[str] = None,
    server_url: Optional[str] = None,
    use_hosted: bool = True
) -> List[Dict[str, Any]]:
    """
    List all available tools from the FMP MCP server.

    Args:
        api_token: FMP API token (optional, uses env var if not provided)
        server_url: Custom server URL (optional)
        use_hosted: Whether to use hosted instance (default: True)

    Returns:
        List of tool definitions
    """
    client = await create_fmp_mcp_client(api_token, server_url, use_hosted)
    tools = await client.get_tools()

    return [
        {
            "name": tool.name,
            "description": tool.description,
        }
        for tool in tools
    ]
