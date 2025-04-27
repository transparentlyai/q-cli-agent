"""
MCP (Model Context Protocol) client implementation for Q.
Provides functionality to connect to MCP servers and interact with their tools.
"""

import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# Global state to track active connections
_connections = {}
_exit_stacks = {}
_event_loop = None

def _get_event_loop():
    """
    Get or create an event loop for MCP operations.
    
    Returns:
        An asyncio event loop
    """
    global _event_loop
    if _event_loop is None or _event_loop.is_closed():
        _event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_event_loop)
        logger.debug("Created new event loop for MCP operations")
    return _event_loop

async def _async_connect(server_name: str, connection_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronously connect to an MCP server.
    
    Args:
        server_name: Name identifier for the server
        connection_info: Dictionary with connection parameters
        
    Returns:
        Dictionary with connection details
    """
    if server_name in _connections:
        logger.warning(f"Connection to {server_name} already exists. Disconnecting first.")
        await _async_disconnect(server_name)
    
    command = connection_info.get("command")
    args = connection_info.get("args", [])
    env = connection_info.get("env")
    
    if not command:
        raise ValueError("Server connection info must include 'command'")
    
    server_params = StdioServerParameters(
        command=command,
        args=args,
        env=env
    )
    
    # Create a new exit stack for this connection
    exit_stack = AsyncExitStack()
    _exit_stacks[server_name] = exit_stack
    
    try:
        stdio_transport = await exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport
        
        session = await exit_stack.enter_async_context(ClientSession(stdio, write))
        await session.initialize()
        
        # Store connection info
        _connections[server_name] = {
            "session": session,
            "stdio": stdio,
            "write": write,
            "connection_info": connection_info
        }
        
        # Get available tools with their schemas
        tools_response = await session.list_tools()
        tools = []
        
        for tool in tools_response.tools:
            tool_info = {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.inputSchema if hasattr(tool, 'inputSchema') else None
            }
            tools.append(tool_info)
        
        return {
            "status": "connected",
            "server": server_name,
            "tools_count": len(tools),
            "tools": tools
        }
    except Exception as e:
        # Clean up if connection fails
        await exit_stack.aclose()
        if server_name in _exit_stacks:
            del _exit_stacks[server_name]
        raise RuntimeError(f"Failed to connect to MCP server: {str(e)}") from e


async def _async_disconnect(server_name: str) -> Dict[str, Any]:
    """
    Asynchronously disconnect from an MCP server.
    
    Args:
        server_name: Name of the server to disconnect from
        
    Returns:
        Status dictionary
    """
    if server_name not in _connections:
        return {"status": "not_connected", "server": server_name}
    
    try:
        # Close the exit stack which will clean up all resources
        if server_name in _exit_stacks:
            await _exit_stacks[server_name].aclose()
            del _exit_stacks[server_name]
        
        # Remove the connection
        del _connections[server_name]
        
        return {"status": "disconnected", "server": server_name}
    except Exception as e:
        logger.error(f"Error disconnecting from {server_name}: {str(e)}")
        return {"status": "error", "server": server_name, "error": str(e)}


async def _async_list_tools(server_name: str = None) -> Dict[str, Any]:
    """
    Asynchronously list all available tools from an MCP server.
    
    Args:
        server_name: Optional name of the server to list tools from.
                    If None, lists tools from all connected servers.
                    
    Returns:
        Dictionary with tools information
    """
    results = {}
    
    if server_name:
        # List tools for a specific server
        if server_name not in _connections:
            return {"status": "error", "error": f"No connection to server: {server_name}"}
        
        try:
            session = _connections[server_name]["session"]
            response = await session.list_tools()
            tools = []
            
            for tool in response.tools:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description,
                    "schema": tool.inputSchema if hasattr(tool, 'inputSchema') else None
                }
                tools.append(tool_info)
                
            results[server_name] = tools
        except Exception as e:
            return {"status": "error", "server": server_name, "error": str(e)}
    else:
        # List tools for all connected servers
        for srv_name, connection in _connections.items():
            try:
                session = connection["session"]
                response = await session.list_tools()
                tools = []
                
                for tool in response.tools:
                    tool_info = {
                        "name": tool.name,
                        "description": tool.description,
                        "schema": tool.inputSchema if hasattr(tool, 'inputSchema') else None
                    }
                    tools.append(tool_info)
                    
                results[srv_name] = tools
            except Exception as e:
                results[srv_name] = {"error": str(e)}
    
    return {
        "status": "success",
        "servers": list(results.keys()),
        "tools": results
    }


async def _async_call_tool(server_name: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronously call a tool on an MCP server.
    
    Args:
        server_name: Name of the server
        tool_name: Name of the tool to call
        args: Arguments to pass to the tool
        
    Returns:
        Tool execution results
    """
    if server_name not in _connections:
        return {"status": "error", "error": f"No connection to server: {server_name}"}
    
    try:
        session = _connections[server_name]["session"]
        response = await session.call_tool(tool_name, args)
        return {
            "status": "success",
            "content": response.content
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def mcp_connect(server: Dict[str, Any]) -> Dict[str, Any]:
    """
    Connect to an MCP server.
    
    Args:
        server: Dictionary with server connection information
               Format: {"server_name": {"command": "...", "args": [...]}}
               
    Returns:
        Dictionary with connection status and available tools
    """
    if not server or len(server) != 1:
        return {"status": "error", "error": "Server info must be a dictionary with a single key-value pair"}
    
    server_name = list(server.keys())[0]
    connection_info = server[server_name]
    
    try:
        # Get or create an event loop
        loop = _get_event_loop()
        
        # Run the async connection function
        result = loop.run_until_complete(_async_connect(server_name, connection_info))
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


def mcp_disconnect(server: str) -> Dict[str, Any]:
    """
    Disconnect from an MCP server.
    
    Args:
        server: Name of the server to disconnect from
        
    Returns:
        Dictionary with disconnection status
    """
    try:
        # Get or create an event loop
        loop = _get_event_loop()
        
        # Run the async disconnection function
        result = loop.run_until_complete(_async_disconnect(server))
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


def mcp_list_tools(server: str = None) -> Dict[str, Any]:
    """
    List all available tools from an MCP server.
    
    Args:
        server: Optional name of the server to list tools from.
               If None, lists tools from all connected servers.
               
    Returns:
        Dictionary with tools information
    """
    try:
        # Get or create an event loop
        loop = _get_event_loop()
        
        # Run the async list tools function
        result = loop.run_until_complete(_async_list_tools(server))
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


def mcp_call_tool(server: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call a tool on an MCP server.
    
    Args:
        server: Name of the server
        tool_name: Name of the tool to call
        args: Arguments to pass to the tool
        
    Returns:
        Tool execution results
    """
    try:
        # Get or create an event loop
        loop = _get_event_loop()
        
        # Run the async call tool function
        result = loop.run_until_complete(_async_call_tool(server, tool_name, args))
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}