# q/__init__.py

# Define the package version.
# This is used by setup.py and can be accessed at runtime via q.__version__.
__version__ = "0.2.20"

# Import core components for easier access
from .core.config import load_config, get_config
from .core.context import Context
from .core.session import Session
from .core.llm import LLM
from .core.prompt import Prompt
from .core.logging import get_logger
from .core.constants import Q_DIR, CONFIG_FILE, SESSION_FILE, AUTO_SAVE_FILE, MCP_SERVERS_FILE, DEFAULT_CONFIG, DEFAULT_MCP_SERVERS

# Import CLI components
from .cli.qconsole import q_console
from .cli.qprompt import QPrompt
from .cli.commands import register_command, handle_command, get_command_help

# Import utility functions
from .utils.helpers import show_error, show_warning, show_success, show_info, show_status, strip_ansi_codes, is_within_project_dir, find_project_root, display_markdown_content
from .utils.command_analyzer import analyze_command
from .utils.config_updater import update_config_file
from .utils.llm_helpers import count_tokens, estimate_token_cost
from .utils.mcp_servers import load_mcp_servers, save_mcp_servers, add_mcp_server, remove_mcp_server, fix_mcp_servers_config

# Import operators
from .operators.router import route_operation
from .operators.shell import execute_shell_command
from .operators.read import read_file
from .operators.write import write_file
from .operators.fetch import fetch_url

# Define __all__ for explicit exports
__all__ = [
    "__version__",
    "load_config",
    "get_config",
    "Context",
    "Session",
    "LLM",
    "Prompt",
    "get_logger",
    "Q_DIR",
    "CONFIG_FILE",
    "SESSION_FILE",
    "AUTO_SAVE_FILE",
    "MCP_SERVERS_FILE",
    "DEFAULT_CONFIG",
    "DEFAULT_MCP_SERVERS",
    "q_console",
    "QPrompt",
    "register_command",
    "handle_command",
    "get_command_help",
    "show_error",
    "show_warning",
    "show_success",
    "show_info",
    "show_status",
    "strip_ansi_codes",
    "is_within_project_dir",
    "find_project_root",
    "display_markdown_content",
    "analyze_command",
    "update_config_file",
    "count_tokens",
    "estimate_token_cost",
    "load_mcp_servers",
    "save_mcp_servers",
    "add_mcp_server",
    "remove_mcp_server",
    "fix_mcp_servers_config",
    "route_operation",
    "execute_shell_command",
    "read_file",
    "write_file",
    "fetch_url",
]