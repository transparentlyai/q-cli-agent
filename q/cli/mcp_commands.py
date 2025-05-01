"""
Command handlers for MCP-related operations.

This module provides command handlers for MCP server management,
including connecting to servers, disconnecting, listing tools,
and managing user-defined server configurations.
"""

import json
import os  # Added for handle_mcp_fix_command
import shlex
from typing import Any, Dict, List, Optional, Tuple

from q.cli.qconsole import q_console, show_error, show_success, show_warning
from q.core.logging import get_logger
from q.utils.mcp_servers import (
    save_user_mcp_servers,  # Added for handle_mcp_fix_command
)
from q.utils.mcp_servers import (
    USER_MCP_SERVERS_PATH,
    add_user_mcp_server,
    check_mcp_servers_file,
    get_all_mcp_servers,
    load_user_mcp_servers,
    remove_user_mcp_server,
)

# Import MCP client functions
try:
    from q.code.mcp import mcp_connect, mcp_disconnect, mcp_list_tools

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

logger = get_logger(__name__)


def handle_mcp_connect_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-connect command to connect to an MCP server.

    Args:
        args: The server name to connect to
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    if not MCP_AVAILABLE:
        show_error(
            "MCP functionality is not available. Make sure the 'mcp' package is installed."
        )
        return True  # Command was handled (though with an error)

    # Check if the MCP servers file is valid
    is_valid, error_msg = check_mcp_servers_file()
    if not is_valid:
        show_error(f"Error in MCP servers configuration: {error_msg}")
        q_console.print(f"Please fix the file at: {USER_MCP_SERVERS_PATH}")
        return True

    if not args:
        show_error("No server name provided. Usage: /mcp-connect <server_name>")

        # Show available servers
        all_servers = get_all_mcp_servers()
        if all_servers:
            q_console.print("[bold]Available MCP servers:[/bold]")
            for server_name, server_info in all_servers.items():
                command = server_info.get("command", "")
                args_str = " ".join(server_info.get("args", []))
                q_console.print(f"  [cyan]{server_name}[/cyan]: {command} {args_str}")
        else:
            q_console.print(
                "[yellow]No MCP servers defined. Use /mcp-add to add a server.[/yellow]"
            )

        return True  # Command was handled

    server_name = args.strip()
    all_servers = get_all_mcp_servers()

    if server_name not in all_servers:
        show_error(f"Server '{server_name}' not found in available MCP servers")

        # Show available servers
        if all_servers:
            q_console.print("[bold]Available MCP servers:[/bold]")
            for name, server_info in all_servers.items():
                command = server_info.get("command", "")
                args_str = " ".join(server_info.get("args", []))
                q_console.print(f"  [cyan]{name}[/cyan]: {command} {args_str}")

        return True  # Command was handled

    try:
        # Create the server connection dictionary in the format expected by mcp_connect
        server_connection = {server_name: all_servers[server_name]}

        # Connect to the server
        with q_console.status(
            f"[bold green]Connecting to MCP server '{server_name}'...[/]"
        ):
            result = mcp_connect(server_connection)

        if result.get("status") == "connected":
            tools_count = result.get("tools_count", 0)
            tools = result.get("tools", [])

            # Show success message
            show_success(
                f"Connected to MCP server '{server_name}' with {tools_count} tools available"
            )

            # Display available tools
            if tools:
                q_console.print("[bold]Available tools:[/bold]")
                for tool in tools:
                    name = tool.get("name", "")
                    description = tool.get("description", "")
                    q_console.print(f"  [cyan]{name}[/cyan]: {description}")
        else:
            error_msg = result.get("error", "Unknown error")
            show_error(f"Failed to connect to MCP server '{server_name}': {error_msg}")

        logger.info(f"MCP connect result: {result}")
    except Exception as e:
        show_error(f"Error connecting to MCP server '{server_name}': {str(e)}")
        logger.error(
            f"Error during MCP connection to {server_name}: {e}", exc_info=True
        )

    return True  # Command was handled


def handle_mcp_disconnect_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-disconnect command to disconnect from an MCP server.

    Args:
        args: The server name to disconnect from
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    if not MCP_AVAILABLE:
        show_error(
            "MCP functionality is not available. Make sure the 'mcp' package is installed."
        )
        return True  # Command was handled (though with an error)

    if not args:
        show_error("No server name provided. Usage: /mcp-disconnect <server_name>")
        return True  # Command was handled

    server_name = args.strip()

    try:
        # Disconnect from the server
        with q_console.status(
            f"[bold yellow]Disconnecting from MCP server '{server_name}'...[/]"
        ):
            result = mcp_disconnect(server_name)

        if result.get("status") == "disconnected":
            show_success(f"Disconnected from MCP server '{server_name}'")
        elif result.get("status") == "not_connected":
            show_warning(f"Not connected to MCP server '{server_name}'")
        else:
            error_msg = result.get("error", "Unknown error")
            show_error(
                f"Failed to disconnect from MCP server '{server_name}': {error_msg}"
            )

        logger.info(f"MCP disconnect result: {result}")
    except Exception as e:
        show_error(f"Error disconnecting from MCP server '{server_name}': {str(e)}")
        logger.error(
            f"Error during MCP disconnection from {server_name}: {e}", exc_info=True
        )

    return True  # Command was handled


def handle_mcp_list_tools_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-tools command to list available tools from MCP servers.

    Args:
        args: Optional server name to list tools from (if empty, lists tools from all servers)
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    if not MCP_AVAILABLE:
        show_error(
            "MCP functionality is not available. Make sure the 'mcp' package is installed."
        )
        return True  # Command was handled (though with an error)

    server_name = args.strip() if args else None

    try:
        # List tools
        with q_console.status(
            f"[bold blue]Listing MCP tools{' for ' + server_name if server_name else ''}...[/]"
        ):
            result = mcp_list_tools(server_name)

        if result.get("status") == "success":
            servers = result.get("servers", [])
            tools_by_server = result.get("tools", {})

            if not servers:
                show_warning("No active MCP server connections found")
                return True

            for srv in servers:
                tools = tools_by_server.get(srv, [])

                if isinstance(tools, dict) and "error" in tools:
                    show_error(
                        f"Error listing tools for server '{srv}': {tools['error']}"
                    )
                    continue

                q_console.print(f"[bold]Tools for MCP server '{srv}':[/bold]")

                if not tools:
                    q_console.print("  [yellow]No tools available[/yellow]")
                    continue

                for tool in tools:
                    name = tool.get("name", "")
                    description = tool.get("description", "")
                    q_console.print(f"  [cyan]{name}[/cyan]: {description}")

                q_console.print("")  # Add spacing between servers
        else:
            error_msg = result.get("error", "Unknown error")
            show_error(f"Failed to list MCP tools: {error_msg}")

        logger.info(f"MCP list tools result: {result}")
    except Exception as e:
        show_error(f"Error listing MCP tools: {str(e)}")
        logger.error(f"Error during MCP tool listing: {e}", exc_info=True)

    return True  # Command was handled


def handle_mcp_list_servers_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-servers command to list all available MCP servers.

    Args:
        args: Command arguments (unused)
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    # Check if the MCP servers file is valid
    is_valid, error_msg = check_mcp_servers_file()
    if not is_valid:
        show_error(f"Error in MCP servers configuration: {error_msg}")
        q_console.print(f"Please fix the file at: {USER_MCP_SERVERS_PATH}")
        return True

    # Get all servers (default + user-defined)
    all_servers = get_all_mcp_servers()

    # Get user-defined servers to distinguish them
    user_servers, user_error = load_user_mcp_servers()

    if user_error:
        show_warning(f"Warning loading user-defined servers: {user_error}")

    if not all_servers:
        show_warning("No MCP servers defined")
        q_console.print(
            f"You can add servers by creating a JSON file at: {USER_MCP_SERVERS_PATH}"
        )
        return True

    q_console.print("[bold]Available MCP servers:[/bold]")

    # Display user-defined servers
    q_console.print("\n[bold]User-defined servers:[/bold]")
    if user_servers:
        for server_name, server_info in user_servers.items():
            command = server_info.get("command", "")
            args_str = " ".join(server_info.get("args", []))
            env_vars = server_info.get("env", {})
            env_str = f" (env: {', '.join(env_vars.keys())})" if env_vars else ""
            q_console.print(
                f"  [cyan]{server_name}[/cyan]: {command} {args_str}{env_str}"
            )
    else:
        q_console.print("  [yellow]No user-defined servers[/yellow]")
        q_console.print(
            f"  You can add servers by creating a JSON file at: {USER_MCP_SERVERS_PATH}"
        )

    return True  # Command was handled


def handle_mcp_add_server_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-add command to add user-defined MCP server(s) from a JSON string.

    Args:
        args: JSON string defining one or more servers.
              Format: '{"server_name": {"command": "...", "args": [...], "env": {...}}, ...}'
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    if not args:
        show_error("No server definition provided. Usage: /mcp-add '<json_string>'")
        q_console.print(
            'Example: /mcp-add \'{"my-server": {"command": "npx", "args": ["-y", "@my/mcp-server@latest"], "env": {"API_KEY": "secret"}}}\''
        )
        return True

    try:
        # Parse the JSON string
        servers_to_add = json.loads(args)

        if not isinstance(servers_to_add, dict):
            show_error(
                "Invalid format. The argument must be a JSON string representing a dictionary of servers."
            )
            return True

        added_count = 0
        error_count = 0

        for server_name, server_config in servers_to_add.items():
            if not isinstance(server_config, dict):
                show_error(
                    f"Invalid configuration for server '{server_name}'. Must be a dictionary."
                )
                error_count += 1
                continue

            if "command" not in server_config:
                show_error(f"Missing 'command' field for server '{server_name}'.")
                error_count += 1
                continue

            # Ensure 'args' and 'env' exist and are of correct type, default if missing/wrong
            if not isinstance(server_config.get("args"), list):
                if "args" in server_config:
                    show_warning(
                        f"Invalid 'args' for server '{server_name}', expected a list. Using empty list."
                    )
                server_config["args"] = []
            if not isinstance(server_config.get("env"), dict):
                if "env" in server_config:
                    show_warning(
                        f"Invalid 'env' for server '{server_name}', expected a dictionary. Using empty dict."
                    )
                server_config["env"] = {}

            # Add the server
            success, error_msg = add_user_mcp_server(server_name, server_config)

            if success:
                show_success(f"Added MCP server '{server_name}'")
                added_count += 1
            else:
                show_error(f"Failed to add MCP server '{server_name}': {error_msg}")
                error_count += 1

        if added_count > 0:
            q_console.print(f"Successfully added {added_count} server(s).")
            q_console.print("You can now connect using: /mcp-connect <server_name>")
        if error_count > 0:
            q_console.print(f"Encountered errors while adding {error_count} server(s).")

    except json.JSONDecodeError as e:
        show_error(f"Invalid JSON provided: {str(e)}")
        logger.error(f"Error decoding JSON for /mcp-add: {e}", exc_info=True)
    except Exception as e:
        show_error(f"Error adding MCP server(s): {str(e)}")
        logger.error(f"Error adding MCP server(s): {e}", exc_info=True)

    return True  # Command was handled


def handle_mcp_remove_server_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-remove command to remove a user-defined MCP server.

    Args:
        args: Server name to remove
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    # Check if the MCP servers file is valid
    is_valid, error_msg = check_mcp_servers_file()
    if not is_valid:
        show_error(f"Error in MCP servers configuration: {error_msg}")
        q_console.print(f"Please fix the file at: {USER_MCP_SERVERS_PATH}")
        return True

    if not args:
        show_error("No server name provided. Usage: /mcp-remove <server_name>")
        return True

    server_name = args.strip()

    # Check if the server exists in user-defined servers
    user_servers, load_error = load_user_mcp_servers()

    if load_error:
        show_error(f"Error loading user-defined servers: {load_error}")
        return True

    if server_name not in user_servers:
        show_error(f"Server '{server_name}' not found in user-defined MCP servers")

        # Show available user-defined servers
        if user_servers:
            q_console.print("[bold]Available user-defined MCP servers:[/bold]")
            for name in user_servers:
                q_console.print(f"  [cyan]{name}[/cyan]")

        return True

    # Remove the server
    success, error_msg = remove_user_mcp_server(server_name)

    if success:
        show_success(f"Removed MCP server '{server_name}'")
    else:
        show_error(f"Failed to remove MCP server '{server_name}': {error_msg}")

    return True  # Command was handled


def handle_mcp_fix_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /mcp-fix command to fix a malformed MCP servers configuration file.

    Args:
        args: Command arguments (unused)
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop)
    """
    # Check if the file exists
    if not os.path.exists(USER_MCP_SERVERS_PATH):
        show_warning(f"MCP servers file does not exist: {USER_MCP_SERVERS_PATH}")
        q_console.print("Creating an empty configuration file...")

        # Create an empty configuration
        success, error_msg = save_user_mcp_servers({})

        if success:
            show_success("Created empty MCP servers configuration file")
        else:
            show_error(f"Failed to create MCP servers file: {error_msg}")

        return True

    # Check if the file is valid
    is_valid, error_msg = check_mcp_servers_file()
    if is_valid:
        show_success("MCP servers configuration file is valid")
        return True

    # Try to fix the file
    try:
        with open(USER_MCP_SERVERS_PATH, "r") as f:
            file_content = f.read().strip()

        q_console.print("[bold]Current content of MCP servers file:[/bold]")
        q_console.print(file_content)
        q_console.print("\n[bold yellow]The file contains invalid JSON.[/bold yellow]")

        # Ask the user if they want to reset the file
        q_console.print("\nOptions:")
        q_console.print(
            "  1. Reset to an empty configuration (all user-defined servers will be lost)"
        )
        q_console.print("  2. Cancel and manually edit the file")

        choice = input("\nEnter your choice (1 or 2): ").strip()

        if choice == "1":
            # Reset the file
            success, error_msg = save_user_mcp_servers({})

            if success:
                show_success("Reset MCP servers configuration to an empty file")
            else:
                show_error(f"Failed to reset MCP servers file: {error_msg}")
        else:
            q_console.print(
                f"\nPlease manually edit the file at: {USER_MCP_SERVERS_PATH}"
            )
            q_console.print("Make sure it contains valid JSON in the format:")
            q_console.print("""
{
  "server1": {
    "command": "command1",
    "args": ["arg1", "arg2"],
    "env": {"KEY": "VALUE"}
  },
  "server2": {
    "command": "command2",
    "args": ["arg1", "arg2"]
  }
}
""")

    except Exception as e:
        show_error(f"Error fixing MCP servers file: {str(e)}")
        logger.error(f"Error fixing MCP servers file: {e}", exc_info=True)

    return True  # Command was handled

