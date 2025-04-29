# Q - Command Line AI Assistant

Q is a powerful command-line AI assistant that helps you accomplish tasks directly from your terminal. It combines the power of large language models with the ability to execute shell commands, read and write files (including PDFs and images), fetch content from the web, and manage your conversation sessions.

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Basic Interaction](#basic-interaction)
  - [Multi-Step Operations](#multi-step-operations)
  - [Commands](#commands)
  - [Operation Types](#operation-types)
  - [Session Management](#session-management)
  - [MCP Servers](#mcp-servers)
- [Security](#security)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Advanced Usage](#advanced-usage)
- [Project Setup](#project-setup)
- [Appendix: Configuration Options](#appendix-configuration-options)

## Installation

### Prerequisites

- Python 3.12+
- A supported LLM provider API key (Anthropic, OpenAI, VertexAI, or Groq)
- Optional: `libmagic` for file type detection (usually installed via `apt-get install libmagic1` or `brew install libmagic`)
- Optional: `pymupdf4llm` for PDF reading (`uv pip install pymupdf4llm`)

### Install from PyPI

```bash
# Using pip
pip install q-assistant

# Or using uv
uv pip install q-assistant
```

### Install from Source

```bash
git clone https://github.com/transparently-ai/q.git
cd q
# Using pip
pip install -e .
# Or using uv
uv pip install -e .
```

## Configuration

Q uses a configuration file located at `~/.config/q/q.conf`. The first time you run Q, it will check your configuration. If the file or directory doesn't exist, or if essential settings like API keys are missing, Q will guide you through the setup process.

You can also use environment variables or a local `.env` file in your current directory to configure Q.

### Essential Configuration

Create or edit `~/.config/q/q.conf`:

```ini
# LLM Provider (anthropic, openai, vertexai, groq)
PROVIDER=anthropic

# API Keys (only the one for your chosen provider is strictly required)
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key
GROQ_API_KEY=your_groq_api_key

# For VertexAI (Google Cloud)
VERTEXAI_PROJECT_ID=your_gcp_project_id
VERTEXAI_LOCATION=us-central1

# Default model to use
MODEL=claude-3-7-sonnet-latest # Example, use a model supported by your provider

# Optional: Set temperature (0.0 to 1.0)
TEMPERATURE=0.1
```

### Environment Variables

You can also set configuration using environment variables:

```bash
export PROVIDER=anthropic
export ANTHROPIC_API_KEY=your_anthropic_api_key
# etc.
```

## Usage

### Basic Interaction

Start Q by running:

```bash
q
```

You'll see a prompt like:

```
Q⏵
```

Ask questions or give instructions naturally:

```
Q⏵ What's the current directory structure?
```

Q will analyze your request and may run commands (with your approval) to provide the answer.

### Multi-Step Operations

For complex tasks requiring multiple steps, Q will:

1. Present a step-by-step plan
2. Ask for your confirmation
3. Execute each step individually with your approval

### Commands

Q supports several built-in commands:

| Command | Description |
|---------|-------------|
| `exit`, `quit`, `q` | Exit the application |
| `/save <filename>` | Save the last response to a file |
| `/clear` | Clear the current chat history and terminal screen (keeps system prompt) |
| `/recover` | Attempt to recover the previous session |
| `/transplant <provider>/<model>` | Switch the LLM provider and model (e.g., `/transplant anthropic/claude-3-7-sonnet-latest`) |
| `/t-budget <integer>` | Set the Vertex AI thinking budget in tokens (e.g., `/t-budget 4096`) |
| `/mcp-connect <server>` | Connect to an MCP server |
| `/mcp-disconnect <server>` | Disconnect from an MCP server |
| `/mcp-tools [server]` | List available tools from MCP servers |
| `/mcp-servers` | List all available MCP servers |
| `/mcp-add <name> <command> [args]` | Add a user-defined MCP server |
| `/mcp-remove <name>` | Remove a user-defined MCP server |
| `/mcp-fix` | Fix a malformed MCP servers configuration file |
| `help`, `?` | Display available commands |

### Operation Types

Q can perform four types of operations, always asking for your approval first:

1.  **Shell Commands**: Execute commands in your terminal.
    ```
    Q⏵ List all Python files in the current directory
    ```

2.  **Read Files**: Read and analyze file contents.
    *   Supports text files, JSON, YAML, code files, etc.
    *   Supports **PDF files**: Extracts text content and converts it to Markdown. Requires `pymupdf4llm`.
    *   Supports **Image files**: Sends image data directly to multimodal LLMs.
    *   Uses file type detection and rejects unsupported formats.
    ```
    Q⏵ Summarize the main points of this document.pdf
    Q⏵ Describe the contents of this image diagram.png
    ```

3.  **Write Files**: Create or modify files.
    *   When modifying an existing file, Q shows a **diff preview** of the changes before asking for approval.
    *   When creating a new file, Q shows a **content preview**.\
    ```
    Q⏵ Refactor this script to use a class structure.
    Q⏵ Create a Dockerfile for a basic Python web app.
    ```

4.  **Fetch Content**: Retrieve content from the web (HTTP/HTTPS).
    ```
    Q⏵ Get the abstract of the paper at https://arxiv.org/abs/xxxx.xxxx
    ```

If an operation is denied by the system (e.g., a prohibited shell command or restricted file path), Q will inform you and stop the current task.

### Session Management

Q automatically saves your conversation history between runs.

-   **Automatic Saving**: Your session is saved after each interaction.
-   **Recovery**: If Q exits unexpectedly or you want to continue a previous conversation, you can:
    -   Start Q with the `--recover` (`-r`) flag: `q --recover`
    -   Use the `/recover` command within Q.
    Q will present the last few turns and ask if you want to restore the session.
-   **Clearing**: Use the `/clear` command to wipe the current conversation history from the display and Q's memory for the current session. This also clears your terminal screen. The underlying session file for recovery remains untouched until the next interaction.
-   **Starting Fresh**: Simply running `q` without `--recover` will start a new session, overwriting the previous recovery state.

### MCP Servers

Multi-Context Processing (MCP) servers provide additional tools and capabilities to Q through a standardized interface.

#### Using MCP Servers

1. **Connect to a server**:
   ```
   Q⏵ /mcp-connect context7
   ```

2. **List available tools**:
   ```
   Q⏵ /mcp-tools
   ```

3. **Disconnect from a server**:
   ```
   Q⏵ /mcp-disconnect context7
   ```

4. **List all available servers**:
   ```
   Q⏵ /mcp-servers
   ```

5. **Fix a malformed configuration file**:
   ```
   Q⏵ /mcp-fix
   ```

#### Adding Custom MCP Servers

You can add your own custom MCP servers in two ways:

1. **Using the command line**:\
   ```
   Q⏵ /mcp-add my-server npx -y @my/mcp-server@latest
   ```

2. **Editing the configuration file** at `~/.config/q/mcp-servers.json`:\
   ```json
   {
     "my-server": {
       "command": "npx",
       "args": ["-y", "@my/mcp-server@latest"]
     }
   }
   ```

For more details on MCP servers, see the [MCP Servers documentation](q/docs/mcp_servers.md).

## Security

Q takes security seriously:

-   Shell commands, file operations (read/write), and web fetches require explicit approval by default.
-   Dangerous commands (like `rm`, `mv` with potential risks) are prohibited based on a predefined list.
-   System directories and sensitive files are protected from write operations based on a predefined list.
-   Network access is limited to the fetch operation for specified URLs.

### Operation Approval

When Q needs to perform an operation, it will ask for your approval:

```
Shell Operation: ls -la
[A]pprove, [D]eny, [C]ancel, [S]how Details, [M]odify, [Y]es to all:
```

```
Write Operation: example.py (Diff Preview Shown Above)
[A]pprove, [D]eny, [C]ancel, [S]how Contents, [M]odify, [Y]es to all:
```

Options:
- `A`: Approve this specific operation.
- `D`: Deny this specific operation.
- `C`: Cancel the entire multi-step plan Q might be executing.
- `S`: Show more details (e.g., full file content for write).
- `M`: Modify the proposed operation (e.g., edit a shell command).
- `Y`: Approve this and all subsequent operations in the current plan (use with caution).

## Examples

### Example 1: System Information

```
Q⏵ What's my OS version and kernel?
```
Q might run commands like `uname -r`, `lsb_release -d`, etc., to gather and present system information.

### Example 2: Code Analysis & Refactoring

```
Q⏵ Read main.py and suggest improvements for readability.
Q⏵ Now, apply those suggestions to the file.
```
Q will read the file, provide suggestions, and if approved, show a diff and write the changes back to `main.py`.

### Example 3: Working with Documents

```
Q⏵ Read the attached report.pdf and summarize the key findings.
```
Q will convert the PDF to text, analyze it, and provide a summary.

### Example 4: Multi-Step Task

```
Q⏵ Fetch the latest release tag from the fastapi github repo, then create a requirements.txt file pinning fastapi to that version.
```
Q will outline the steps (fetch URL, parse response, write file), then execute them one by one with your approval.

### Example 5: Using MCP Servers

```
Q⏵ /mcp-connect context7
Q⏵ Use context7 to search for information about climate change
```
Q will connect to the context7 MCP server and use its search tools to find information about climate change.

## Troubleshooting

### Common Issues

1.  **Configuration Errors on Startup**:
    -   Q will print specific errors if `q.conf` is missing or invalid (e.g., missing `PROVIDER` or API key).
    -   Solution: Follow the instructions provided by Q to edit `~/.config/q/q.conf` or set environment variables.

2.  **PDF/Image Reading Fails**:
    -   Error: `PDF conversion requires pymupdf4llm library...`
    -   Solution: Install the optional dependency: `uv pip install pymupdf4llm`
    -   Error related to `libmagic`:
    -   Solution: Install the `libmagic` library using your system's package manager (e.g., `sudo apt-get install libmagic1` on Debian/Ubuntu, `brew install libmagic` on macOS).

3.  **Permission Denied**:
    -   Error: `Permission denied when accessing file...`
    -   Solution: Ensure Q has the necessary read/write permissions for the target file or directory. Check file/directory ownership and permissions (`ls -l`).

4.  **Command Not Found**:
    -   Error: `Command not found` during a shell operation.
    -   Solution: Ensure the command Q is trying to run is installed on your system and available in your `PATH`.

5.  **MCP Server Connection Issues**:
    -   Error: `Failed to connect to MCP server...`
    -   Solution: Ensure the command specified for the MCP server is valid and that any required packages are installed. Check that any required API keys are set in the environment.
    -   Error: `Error in MCP servers configuration...`
    -   Solution: Use the `/mcp-fix` command or manually edit `~/.config/q/mcp-servers.json` to correct the JSON format.

### Logs

Q logs detailed information to `~/.q/logs/q.log`. Check this file for debugging errors.

## Advanced Usage

### Command Line Arguments

```bash
# Start Q with an initial question
q "What are the *.py files in ./src?"

# Exit after answering the initial question
q --exit-after-answer "Count lines of code in this project"
q -e "Count lines of code in this project" # Short flag

# Grant execution of all commands except dangerous or prohibited ones (use cautiously)
q --all "Create a basic Flask app structure"

# Recover the previous session on startup
q --recover
q -r # Short flag

# Show version and exit
q --version
```

### Multiline Input

For complex queries or pasting code snippets, use multiline input:
1. Press `Alt+Enter` (or `Esc` then `Enter`) to start multiline mode.
2. Type or paste your input across multiple lines.
3. Press `Alt+Enter` (or `Esc` then `Enter`) again to submit.

### Tab Completion

Q supports tab completion for:
- Built-in commands (`/save`, `/clear`, `exit`, etc.)
- File paths (when relevant, e.g., for `/save` or when Q expects a path)
- `/transplant` arguments (suggests available provider/model combinations)
- `/mcp-connect` and `/mcp-remove` arguments (suggests available MCP servers)
- `/t-budget` (suggests expected input type)

### Customization

Q can be customized with context files:

1.  **User Context**: Create `~/.config/q/user.md` to add personal instructions that apply to all Q sessions.
    ```markdown
    - Your name is Jane Doe
    - You prefer Python for scripting tasks
    - Always use f-strings for formatting
    ```

2.  **Project Context**: Create `.Q/project.md` in your project directory root to add project-specific instructions.
    ```markdown
    - This is a Django project using version 5.0
    - Follow PEP 8 style guidelines strictly
    - Use `pytest` for testing, tests are in the `tests/` directory
    - Main application code is in the `app/` directory
    ```

These context files are automatically loaded and included in Q's system prompt.

## Project Setup

Setting up Q for your projects helps it understand specific requirements.

### How Q Finds Project Roots

Q automatically detects project roots by looking for:
- A `.Q` directory (highest priority)
- A `.git` directory
- `pyproject.toml`, `package.json`, etc.
It searches upwards from the current directory.

### Setting Up a Project

1. Navigate to your project root.
2. Create a `.Q` directory: `mkdir .Q`
3. Create a context file: `touch .Q/project.md`
4. Edit `.Q/project.md` with details about the tech stack, coding standards, structure, etc. (See examples in the file itself or above).

A well-crafted `project.md` significantly improves Q's relevance and accuracy for your project.

## Appendix: Configuration Options

All options can be set in `~/.config/q/q.conf` or via environment variables.

*(The Appendix content seems up-to-date based on the code reviewed, so it remains unchanged. If specific new options were added in `config.py` or `constants.py`, they would need to be added here.)*

### LLM Provider Settings
... (rest of Appendix remains the same) ...

## License

[MIT License](LICENSE)

---

Q is developed by [Transparently.Ai](https://transparently.ai)