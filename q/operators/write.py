import difflib
import os
from pathlib import Path
from typing import Any, Dict

from rich.syntax import Syntax

from q.cli.approvals import request_approval
from q.cli.qconsole import (
    q_console,
    show_error,
    show_spinner,
    show_success,
    show_warning,
)
from q.core.config import config
from q.core.constants import (
    OPEARION_SPINNER_COMMAND_COLOR,
    OPEARION_SPINNER_MESSAGE_COLOR,
)
from q.core.logging import get_logger

logger = get_logger(__name__)

CODE_SYNTAX_THEME = getattr(config, "CODE_SYNTAX_THEME", "vim")


def write_file(file_path: str, content: str) -> Dict[str, Any]:
    """
    Write content to a file or create a new file if it doesn't exist.

    Args:
        file_path: The path to the file to write or create.
        content: The complete content to write to the file.

    Returns:
        A dictionary containing:
            - 'reply': A message with the operation result
            - 'error': Error message if an error occurred, None otherwise
    """
    logger.info(f"Requesting approval for write operation on: '{file_path}'")

    result = {"reply": "", "error": None}

    # if content starts with ``` and ends with ```, remove the first and last lines
    if content.startswith("```") and content.endswith("```"):
        content = "\n".join(content.splitlines()[1:-1])

    # remove double escaped new lines
    content = content.replace("\\n", "\n")
    # remove double escaped quotes
    content = content.replace('\\"', '"')
    # remove double escaped backslashes
    content = content.replace("\\\\", "\\")
    # remove double escaped single quotes
    content = content.replace("\\'", "'")
    # remove double escaped tabs
    content = content.replace("\\t", "\t")
    # remove double escaped carriage Returns
    content = content.replace("\\r", "\r")

    # Check if file exists to determine action message
    file_exists = os.path.exists(file_path)
    action = "Updating" if file_exists else "Creating"

    # If file exists, show diff preview
    if file_exists:
        show_diff_preview(file_path, content)
    else:
        show_content_preview(file_path, content)

    q_console.print("")

    # Request approval using the approvals module
    approval_status = request_approval(
        operation_type="write",
        operation_content=f"File: {file_path}",
    )

    logger.debug(f"Approval response received: {approval_status}")

    if isinstance(approval_status, dict) and "reason" in approval_status:
        reason = approval_status["reason"]
        show_warning(f"Write operation denied: {reason}")
        logger.warning(f"STOP:Write operation denied: {reason}")
        result["reply"] = "STOP:Write operation failed"
        result["error"] = reason
        return result
    elif approval_status == "cancelled":
        show_warning(f"Write operation cancelled: {file_path}")
        logger.warning(f"Write operation cancelled by user for path: '{file_path}'")
        result["reply"] = "STOP: Write operation cancelled"
        result["error"] = f"Write operation cancelled by user for path '{file_path}'."
        return result
    elif approval_status is not True:
        show_error(f"Unexpected approval status: {approval_status}")
        logger.warning(
            f"Unexpected approval status '{approval_status}' for write operation on '{file_path}'. Denying."
        )
        result["reply"] = "STOP:Write operation failed"
        result["error"] = f"Unexpected approval status '{approval_status}'."
        return result

    # Approval granted
    logger.debug(f"Approval granted for writing to file: {file_path}")
    show_success(f"Approval granted for writing to file: [purple]{file_path}[/]")

    try:
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

        with show_spinner(
            f"{OPEARION_SPINNER_MESSAGE_COLOR}{action} file{OPEARION_SPINNER_COMMAND_COLOR} {file_path}..."
        ):
            # Write the content to the file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            action_past = "updated" if file_exists else "created"
            show_success(f"Successfully {action_past} file: {file_path}")
            result["reply"] = f"Successfully {action_past} file: {file_path}"
            logger.debug(f"File {action_past}: {file_path}")

    except Exception as e:
        show_error(f"Error writing file: {e}")
        return handle_error(
            result,
            f"An unexpected error occurred: {e}",
            "Write operation failed",
            "error",
            exc_info=True,
        )

    return result


def show_content_preview(file_path: str, content: str) -> None:
    """
    Show a preview of content that will be written to a file.

    Args:
        file_path: Path to the file that will be created
        content: Content that will be written to the file
    """
    q_console.print(f"[bold]Preview of content for {file_path}:[/bold]")

    # Determine the language for syntax highlighting based on file extension
    file_ext = Path(file_path).suffix.lstrip(".")

    # Split content into lines for preview
    lines = content.splitlines()
    line_count = len(lines)

    # Define preview limits
    max_preview_lines = 30
    head_lines = 12
    tail_lines = 12

    # If content is too long, show beginning and end portions
    if line_count > max_preview_lines:
        preview_content = "\n".join(lines[:head_lines])
        preview_content += (
            f"\n\n[...{line_count - head_lines - tail_lines} more lines...]\n\n"
        )
        preview_content += "\n".join(lines[-tail_lines:])

        syntax = Syntax(
            preview_content,
            file_ext if file_ext else "text",
            line_numbers=False,
            background_color="black",
            theme=CODE_SYNTAX_THEME,
        )
        q_console.print(syntax)
        q_console.print(
            f"[dim](Showing {head_lines} lines from start and {tail_lines} lines from end of {line_count} total lines)[/dim]"
        )
    else:
        # Show full content for shorter files
        syntax = Syntax(
            content,
            file_ext if file_ext else "text",
            line_numbers=False,
            background_color="black",
            theme=CODE_SYNTAX_THEME,
        )
        q_console.print(syntax)


def show_diff_preview(file_path: str, new_content: str) -> None:
    """
    Show a diff preview between the existing file and the new content.

    Args:
        file_path: Path to the existing file
        new_content: New content to be written
    """
    try:
        # Read the existing file content
        with open(file_path, "r", encoding="utf-8") as f:
            old_content = f.read()

        # Skip diff if content is identical
        if old_content == new_content:
            q_console.print(
                "[bold yellow]No changes detected - file content is identical[/bold yellow]"
            )
            return

        # Generate diff
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        # Create a unified diff
        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"Current: {file_path}",
                tofile=f"New: {file_path}",
                lineterm="",
                n=3,  # Context lines
            )
        )

        if diff:
            q_console.print(f"[bold]Changes to {file_path}:[/bold]")

            # Format the diff output with syntax highlighting
            diff_text = "\n".join(diff)
            syntax = Syntax(
                diff_text, "diff", line_numbers=False, theme=CODE_SYNTAX_THEME
            )
            q_console.print(syntax)
        else:
            # This shouldn't happen if we already checked equality, but just in case
            q_console.print("[bold yellow]No changes detected in diff[/bold yellow]")

    except Exception as e:
        # If there's an error showing the diff, fall back to showing the new content
        q_console.print(f"[bold red]Error generating diff preview: {e}[/bold red]")
        show_content_preview(file_path, new_content)


def handle_error(
    result: Dict[str, Any],
    error_msg: str,
    reply_msg: str,
    log_level: str = "error",
    exc_info: bool = False,
) -> Dict[str, Any]:
    """Handle errors consistently and update the result dictionary."""
    log_func = getattr(logger, log_level)
    log_func(error_msg, exc_info=exc_info)

    result["reply"] = reply_msg
    result["error"] = error_msg
    return result


def handle_write(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle write operation from the router.

    Args:
        args: Dictionary containing operation arguments including 'path' and 'content'.

    Returns:
        Dict with status and message.
    """
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return {
            "reply": "Write operation failed",
            "error": "No path specified for write operation.",
        }

    return write_file(path, content)
