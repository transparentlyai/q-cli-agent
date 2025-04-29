# MCP Servers in Q

Multi-Context Processing (MCP) servers provide additional tools and capabilities to Q through a standardized interface. This document explains how to use and configure MCP servers in Q.

## What are MCP Servers?

MCP servers are external processes that Q can connect to in order to access specialized tools. These tools can provide additional functionality like:

- Context-aware search
- Document processing
- Code analysis
- And more

Each MCP server exposes a set of tools that Q can use to enhance its capabilities.

## Built-in MCP Servers

Q comes with a default MCP server configuration:

- **context7**: A server that provides context-aware search and document processing capabilities

## Using MCP Servers

Here are the commands available for managing MCP servers:

### Connecting to a Server

To connect to an MCP server, use the `/mcp-connect` command followed by the server name:

```
/mcp-connect context7
```

This will start the server process and establish a connection. Once connected, Q will display the available tools.

### Listing Available Tools

To see what tools are available from connected MCP servers, use the `/mcp-tools` command:

```
/mcp-tools
```

You can also specify a server name to list tools from a specific server:

```
/mcp-tools context7
```

### Disconnecting from a Server

To disconnect from an MCP server, use the `/mcp-disconnect` command followed by the server name:

```
/mcp-disconnect context7
```

### Listing Available Servers

To see all available MCP servers (both built-in and user-defined), use the `/mcp-servers` command:

```
/mcp-servers
```

### Fixing Configuration Issues

If your MCP servers configuration file (`~/.config/q/mcp-servers.json`) becomes malformed or contains errors, Q will display a warning at startup. You can attempt to fix these issues using the `/mcp-fix` command:

```
/mcp-fix
```

This command will:
1. Check if the configuration file exists and is valid.
2. If there are issues, show you the current content and offer options to fix it.
3. Allow you to reset the file to an empty configuration or manually edit it.

## Adding Custom MCP Servers

You can add your own custom MCP servers in two ways:

### 1. Using the Command Line

Use the `/mcp-add` command followed by a **JSON string** defining one or more servers. The JSON string must represent a dictionary where keys are server names and values are server configuration objects (with `command`, optional `args`, and optional `env` fields).

```
/mcp-add '{"my-server": {"command": "npx", "args": ["-y", "@my/mcp-server@latest"], "env": {"API_KEY": "secret"}}}'
```

This method is useful for quickly adding servers from the command line, including specifying arguments and environment variables directly in the JSON.

### 2. Editing the Configuration File

You can also directly edit the configuration file at `~/.config/q/mcp-servers.json`. This file uses a JSON format to define custom servers:

```json
{
  "my-server": {
    "command": "npx",
    "args": ["-y", "@my/mcp-server@latest"]
  },
  "another-server": {
    "command": "python",
    "args": ["-m", "my_mcp_module"]
  },
  "server-with-env": {
    "command": "npx",
    "args": ["-y", "@some/mcp-server@latest"],
    "env": {
      "API_KEY": "your-api-key-here",
      "DEBUG": "true"
    }
  }
}
```

Each server definition must include:
- A unique name as the key
- A `command` field specifying the executable to run
- An optional `args` array with command-line arguments
- An optional `env` object with environment variables

### Environment Variables

Environment variables are crucial for many MCP servers, especially those that require API keys or other configuration. When you define a server with environment variables, Q will:

1. Start with a copy of the current environment
2. Add or override the variables specified in the server configuration
3. Pass this merged environment to the server process

This ensures that the server has access to both the system environment and any server-specific variables you define.

Example with environment variables:

```json
{
  "context7": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp@latest"],
    "env": {
      "CONTEXT7_API_KEY": "your-api-key-here",
      "CONTEXT7_DEBUG": "true"
    }
  }
}
```

## Removing Custom MCP Servers

To remove a custom MCP server, use the `/mcp-remove` command:

```
/mcp-remove my-server
```

Note that you can only remove user-defined servers, not the built-in ones.

## MCP Server Protocol

MCP servers communicate with Q using a standardized protocol based on JSON-RPC over stdio. If you're interested in developing your own MCP server, refer to the MCP protocol documentation.

## Troubleshooting

If you encounter issues with MCP servers:

1. Make sure the required packages are installed (Q will attempt to install them if needed).
2. Check that the command specified in the server configuration is valid and accessible.
3. Verify that any required environment variables are set correctly in the server configuration.
4. Look for error messages in the Q console when connecting to the server.

If a server fails to connect, Q will display an error message with details about what went wrong.

### Common Issues

1. **Missing API Keys**: Many MCP servers require API keys to function. Make sure you've added the necessary API keys in the `env` section of your server configuration.

2. **Command Not Found**: If the server command is not found, make sure the package or executable is installed and available in your PATH.

3. **Malformed Configuration**: If your `mcp-servers.json` file contains invalid JSON, Q will display a warning at startup. Use the `/mcp-fix` command to repair it.

4. **Connection Errors**: If the server process starts but fails to connect, check the server logs for more details. This could be due to network issues, missing dependencies, or configuration problems.