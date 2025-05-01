"""
Utility module for loading and managing MCP server configurations.

This module handles loading MCP server configurations from the user's custom
configuration file at ~/.config/q/mcp-servers.json.
"""

import json
import os
import logging
from typing import Dict, Any, Tuple, Optional

# Removed import of MCP_SERVERS from q.core.constants

logger = logging.getLogger(__name__)

# Path to user's custom MCP servers configuration file
USER_MCP_SERVERS_PATH = os.path.expanduser("~/.config/q/mcp-servers.json")


def get_all_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """
    Get all available MCP servers from the user-defined configuration file.

    Returns:
        Dictionary mapping server names to their configuration details.
        Returns an empty dictionary if the file doesn't exist or is invalid.
    """
    # Load user-defined servers
    user_servers, _ = load_user_mcp_servers() # Ignore the error message for this function
    return user_servers


def load_user_mcp_servers() -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """
    Load user-defined MCP servers from the configuration file.

    Returns:
        Tuple containing:
        - Dictionary mapping server names to their configuration details,
          or an empty dictionary if the file doesn't exist or is invalid.
        - Error message if there was a problem loading the file, or None if successful.
    """
    if not os.path.exists(USER_MCP_SERVERS_PATH):
        logger.debug(f"User MCP servers file not found: {USER_MCP_SERVERS_PATH}")
        return {}, None

    try:
        with open(USER_MCP_SERVERS_PATH, 'r') as f:
            file_content = f.read().strip()
            if not file_content:
                logger.warning(f"Empty MCP servers file: {USER_MCP_SERVERS_PATH}")
                return {}, "MCP servers file is empty"

            try:
                user_servers = json.loads(file_content)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON in MCP servers file: {str(e)}"
                logger.warning(error_msg)
                return {}, error_msg

        # Validate the structure
        if not isinstance(user_servers, dict):
            error_msg = f"Invalid format in {USER_MCP_SERVERS_PATH}: expected a dictionary"
            logger.warning(error_msg)
            return {}, error_msg

        # Validate each server configuration
        valid_servers = {}
        invalid_servers = []

        for server_name, config in user_servers.items():
            if not isinstance(config, dict):
                invalid_servers.append(f"{server_name} (not a dictionary)")
                continue

            if "command" not in config:
                invalid_servers.append(f"{server_name} (missing 'command' field)")
                continue

            # Add the valid server configuration
            valid_servers[server_name] = config

        if invalid_servers:
            error_msg = f"Invalid server configurations: {', '.join(invalid_servers)}"
            logger.warning(error_msg)
            if valid_servers:
                # Some servers were valid, so return them with a warning
                return valid_servers, error_msg
            else:
                # No valid servers found
                return {}, error_msg

        logger.info(f"Loaded {len(valid_servers)} user-defined MCP servers")
        return valid_servers, None

    except Exception as e:
        error_msg = f"Error loading user MCP servers: {e}"
        logger.error(error_msg)
        return {}, error_msg


def save_user_mcp_servers(servers: Dict[str, Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """
    Save user-defined MCP servers to the configuration file.

    Args:
        servers: Dictionary mapping server names to their configuration details

    Returns:
        Tuple containing:
        - Boolean indicating success or failure
        - Error message if there was a problem, or None if successful
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(USER_MCP_SERVERS_PATH), exist_ok=True)

        with open(USER_MCP_SERVERS_PATH, 'w') as f:
            json.dump(servers, f, indent=2)

        logger.info(f"Saved {len(servers)} user-defined MCP servers to {USER_MCP_SERVERS_PATH}")
        return True, None
    except Exception as e:
        error_msg = f"Error saving user MCP servers: {e}"
        logger.error(error_msg)
        return False, error_msg


def add_user_mcp_server(server_name: str, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Add or update a user-defined MCP server.

    Args:
        server_name: Name of the server
        config: Server configuration dictionary (must include 'command')

    Returns:
        Tuple containing:
        - Boolean indicating success or failure
        - Error message if there was a problem, or None if successful
    """
    if "command" not in config:
        error_msg = f"Invalid configuration for server '{server_name}': missing 'command' field"
        logger.warning(error_msg)
        return False, error_msg

    # Load existing servers
    user_servers, error_msg = load_user_mcp_servers()

    # If there was an error but we got some servers, we can still proceed
    # If there was an error and no servers, create a new dictionary
    if not user_servers and error_msg:
        user_servers = {}

    # Add or update the server
    user_servers[server_name] = config

    # Save the updated servers
    return save_user_mcp_servers(user_servers)


def remove_user_mcp_server(server_name: str) -> Tuple[bool, Optional[str]]:
    """
    Remove a user-defined MCP server.

    Args:
        server_name: Name of the server to remove

    Returns:
        Tuple containing:
        - Boolean indicating success or failure
        - Error message if there was a problem, or None if successful
    """
    # Load existing servers
    user_servers, error_msg = load_user_mcp_servers()

    # Check if the server exists
    if not user_servers:
        if error_msg:
            return False, error_msg
        else:
            return False, f"No user-defined MCP servers found"

    if server_name not in user_servers:
        return False, f"Server '{server_name}' not found in user-defined MCP servers"

    # Remove the server
    del user_servers[server_name]

    # Save the updated servers
    return save_user_mcp_servers(user_servers)


def check_mcp_servers_file() -> Tuple[bool, Optional[str]]:
    """
    Check if the MCP servers file exists and is valid.

    Returns:
        Tuple containing:
        - Boolean indicating if the file is valid
        - Error message if there was a problem, or None if the file is valid or doesn't exist.
        Returns True, None if the file does not exist.
    """
    if not os.path.exists(USER_MCP_SERVERS_PATH):
        return True, None  # File doesn't exist, which is fine

    try:
        with open(USER_MCP_SERVERS_PATH, 'r') as f:
            file_content = f.read().strip()
            if not file_content:
                return False, "MCP servers file is empty"

            try:
                json.loads(file_content)
                return True, None  # File is valid JSON
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON in MCP servers file: {str(e)}"
    except Exception as e:
        return False, f"Error reading MCP servers file: {str(e)}"