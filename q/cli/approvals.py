"""
Enhanced approval system for operations that require user confirmation.
Refactored to return reasons for rejections instead of boolean values.
"""

import datetime
import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from q.cli.qconsole import q_console
from q.core import constants
from q.core.config import config
from q.utils.command_analyzer import is_command_safe

# Configure logging for this module
logger = logging.getLogger(__name__)

# State variable for "Approve All" feature
_approve_all_until = None


def _ask_confirmation(
    prompt: str, custom_choice: Optional[Tuple[str, str]] = None
) -> str:
    """
    Uses rich.prompt.Prompt to ask the user for confirmation, allowing
    single-letter (case-insensitive) or full word input, plus an optional
    custom choice.

    Args:
        prompt: The base message to display to the user.
        custom_choice: An optional tuple (key, display_text) for a custom choice.

    Returns:
        The user's choice as a lowercase single-letter key ("y", "n", "c", "a",
        or the custom choice key).
    """
    # Define mappings for convenience (full word to key)
    mapping = {
        "yes": "y",
        "no": "n",
        "cancel": "c",
        "all": "a",
    }
    # Define the choices string for the prompt
    choices_display = "Yes[y]/No[n]/Cancel[c]/All[a]"

    # Add custom choice if provided
    custom_key = None
    if custom_choice:
        custom_key, custom_display = custom_choice
        # Map the full word part of the custom display text to the custom key
        full_word_part = custom_display.lower().split("[")[0]
        if full_word_part:  # Ensure there's a word part before the bracket
            mapping[full_word_part] = custom_key.lower()
        choices_display += f"/{custom_display}"

    # Update prompt to show options
    full_prompt = f"{prompt} ({choices_display})"

    while True:  # Loop until valid input is received
        try:
            # Ask without strict choices, handle validation manually
            raw_choice = Prompt.ask(
                full_prompt,
                default="No",  # Default to No for safety
                console=cast(Console, q_console),
                # No 'choices' argument here
            )
            choice = raw_choice.strip().lower()

            # Check against standard single-letter keys and custom key
            if choice in ("y", "n", "c", "a"):
                return choice
            # Check against full word mappings
            if choice in mapping:
                return mapping[choice]
            # Check against custom key if provided
            if custom_key and choice == custom_key.lower():
                return choice

            # Provide specific feedback on invalid input
            q_console.print(
                f"[prompt.invalid]Invalid input. Please enter one of: {choices_display}"
            )

        except Exception as e:
            # Log potential errors during confirmation (e.g., issues with stdin)
            logger.error(f"Failed to get user confirmation choice: {e}", exc_info=True)
            # Default to safety: treat errors as cancellation
            q_console.print(
                "[prompt.invalid]An error occurred during input. Cancelling operation."
            )
            return "c"  # Return cancel key


def _ask_duration(prompt: str, default: int) -> int:
    """
    Asks the user for a duration in minutes.

    Args:
        prompt: The message to display.
        default: The default duration in minutes.

    Returns:
        The duration in minutes entered by the user.
    """
    while True:
        try:
            duration = Prompt.ask(
                prompt,
                default=str(default),
                console=cast(Console, q_console),
            )
            # Validate if the input is an integer
            return int(duration)
        except ValueError:
            q_console.print("[prompt.invalid]Please enter a valid number of minutes.")
        except Exception as e:
            logger.error(f"Failed to get duration input: {e}", exc_info=True)
            q_console.print(
                f"[prompt.invalid]An error occurred. Using default value ({default} minutes)."
            )
            return default


def _handle_user_choice(
    user_choice_key: str, operation_desc: str, custom_choice_key: Optional[str] = None
) -> Union[bool, str, Dict[str, str]]:
    """
    Centralized handler for user choices to avoid code duplication.

    Args:
        user_choice_key: The user's choice as a lowercase single-letter key.
        operation_desc: Description of the operation for logging.
        custom_choice_key: The key for the optional custom choice.

    Returns:
        - True if approved (y, a)
        - Dict with reason if denied (n)
        - "cancelled" if cancelled (c)
        - The custom_choice_key string if the custom choice was selected.
    """
    global _approve_all_until

    # Handle custom choice first if provided
    if custom_choice_key and user_choice_key == custom_choice_key.lower():
        logger.info(
            f"User chose custom option '{custom_choice_key}' for: {operation_desc}"
        )
        return custom_choice_key

    match user_choice_key:
        case "y":
            logger.info(f"User approved: {operation_desc}")
            return True
        case "n":
            logger.warning(f"User denied: {operation_desc}")
            return {"reason": f"Operation was rejected by the user: {operation_desc}"}
        case "c":
            logger.warning(f"User cancelled: {operation_desc}")
            return "cancelled"
        case "a":
            logger.info(f"User chose 'Approve All' for: {operation_desc}")
            duration_minutes = _ask_duration(
                " Approve all subsequent operations for how many minutes",
                default=15,
            )
            if duration_minutes > 0:
                _approve_all_until = datetime.datetime.now() + datetime.timedelta(
                    minutes=duration_minutes
                )
                logger.info(f"'Approve All' activated until {_approve_all_until}")
                q_console.print(
                    f"\n[yellow]▶▶▶Auto-approval enabled for {duration_minutes} minutes.[/]\n"
                )
            else:
                logger.info(
                    "User entered 0 or negative duration for 'Approve All'. Not activating."
                )
                q_console.print("Auto-approval not enabled.")
            # Approve the current operation that triggered the 'All' choice
            return True
        case _:
            # This case should ideally not be reached if _ask_confirmation works correctly
            logger.error(
                f"Unexpected choice key '{user_choice_key}' received for: {operation_desc}"
            )
            return {"reason": f"Unexpected choice key '{user_choice_key}' received"}


def _display_command_safety_warning(command: str, analysis: Dict[str, Any]) -> None:
    """
    Display a warning about command safety issues.

    Args:
        command: The shell command string
        analysis: The analysis result from command_analyzer
    """
    danger_level = analysis["danger_level"]

    # Create a rich text object for the warning
    warning = Text()

    # Add header based on severity
    if danger_level == "critical":
        warning.append("CRITICAL RISK COMMAND \n\n", style="bold red")
    elif danger_level == "high":
        warning.append("HIGH RISK COMMAND \n\n", style="bold red")
    elif danger_level == "medium":
        warning.append("MEDIUM RISK COMMAND \n\n", style="bold yellow")
    else:
        warning.append("POTENTIAL RISK COMMAND \n\n", style="bold yellow")

    # Add the command
    warning.append("Command: ", style="bold")
    warning.append(command, style="cyan")
    warning.append("\n\n")

    # Add reasons
    warning.append("Detected risks:\n", style="bold")
    for reason in analysis["reasons"]:
        warning.append(f"• {reason}\n", style="italic")

    # Display the warning in a panel
    q_console.print(Panel(warning, title="Command Safety Warning", border_style="red"))


def _normalize_path_rule(p_str: str) -> Union[Path, str, None]:
    """
    Resolves absolute paths, keeps relative patterns/names as strings.
    Paths starting with '/' are treated as absolute. Others are patterns/names.
    """
    try:
        p_str = p_str.strip()
        if not p_str:
            return None
        if p_str.startswith("/"):
            # Resolve absolute paths fully
            return Path(p_str).resolve(
                strict=False
            )  # strict=False allows resolving non-existent paths for rules
        else:
            # Keep relative paths/patterns (like '.ssh/') as strings
            return p_str
    except Exception as e:
        logger.warning(
            f"Could not normalize path rule: '{p_str}'. Error: {e}", exc_info=True
        )
        return None


def _get_combined_rules(
    constants_attr: str, config_attr: str
) -> List[Union[Path, str]]:
    """
    Helper to combine rules from constants and config.

    Args:
        constants_attr: Attribute name in constants module
        config_attr: Attribute name in config module

    Returns:
        Combined list of rules
    """
    # Get defaults from constants
    defaults = getattr(constants, constants_attr, [])

    # Get user config values
    config_values = getattr(config, config_attr, [])

    # Ensure config values are lists
    if not isinstance(config_values, list):
        logger.warning(
            f"Config value for {config_attr} is not a list: {config_values}. Ignoring."
        )
        config_values = []

    # Combine and normalize
    combined = []
    for rule in defaults + config_values:
        norm_rule = _normalize_path_rule(rule) if isinstance(rule, str) else rule
        if norm_rule is not None:
            combined.append(norm_rule)

    return combined


def _check_read_rules(target_path: Path) -> Union[str, Dict[str, str]]:
    """
    Checks the target path against read approval rules (prohibited, restricted, outside home).

    Args:
        target_path: The absolute, resolved path to the file being read.

    Returns:
        "prohibited" with reason, "restricted", or "allowed".
    """
    try:
        home_dir = Path.home().resolve()
    except Exception as e:
        logger.error(
            f"Could not resolve home directory: {e}. Cannot apply 'outside home' rule.",
            exc_info=True,
        )
        # Fallback: treat as restricted if home dir is unknown
        return "restricted"

    # Load and combine rules
    all_prohibited = _get_combined_rules(
        "READ_PROHIBITED_FILES", "READ_PROHIBITED_FILES"
    )
    all_restricted = _get_combined_rules(
        "READ_RESTRICTED_FILES", "READ_RESTRICTED_FILES"
    )

    # Check Prohibited Rules
    for rule in all_prohibited:
        try:
            if isinstance(rule, Path):  # Absolute path rule (file or dir)
                if rule.is_dir():
                    # Check if target_path is the directory itself or inside it
                    if target_path == rule or target_path.is_relative_to(rule):
                        logger.debug(
                            f"Read check: Path {target_path} is within or matches prohibited directory {rule}"
                        )
                        return {
                            "reason": f"Reading from path '{target_path}' is prohibited (matches rule: {rule})"
                        }
                else:  # Absolute file rule
                    if target_path == rule:
                        logger.debug(
                            f"Read check: Path {target_path} matches prohibited file {rule}"
                        )
                        return {
                            "reason": f"Reading from path '{target_path}' is prohibited (matches rule: {rule})"
                        }
            elif isinstance(rule, str):  # Relative pattern/name rule (e.g., '.ssh/')
                pattern = rule.strip("/")
                # Check if pattern matches a directory/file name in the path parts
                # Use Path.parts for robust checking of components
                if any(part == pattern for part in target_path.parts):
                    logger.debug(
                        f"Read check: Path {target_path} contains prohibited component '{pattern}'"
                    )
                    return {
                        "reason": f"Reading from path '{target_path}' is prohibited (contains component: {pattern})"
                    }
                # Also check if the target filename itself matches (for patterns like '.bash_history')
                if target_path.name == pattern:
                    logger.debug(
                        f"Read check: Path {target_path} filename matches prohibited pattern '{pattern}'"
                    )
                    return {
                        "reason": f"Reading from path '{target_path}' is prohibited (filename matches: {pattern})"
                    }
        except Exception as e:
            logger.warning(
                f"Error checking prohibited rule '{rule}' against path '{target_path}': {e}"
            )
            # Skip the rule on error
            continue

    # Check Restricted Rules (similar logic to prohibited)
    for rule in all_restricted:
        try:
            if isinstance(rule, Path):  # Absolute path rule
                if rule.is_dir():
                    if target_path == rule or target_path.is_relative_to(rule):
                        logger.debug(
                            f"Read check: Path {target_path} is within or matches restricted directory {rule}"
                        )
                        return "restricted"
                else:  # Absolute file rule
                    if target_path == rule:
                        logger.debug(
                            f"Read check: Path {target_path} matches restricted file {rule}"
                        )
                        return "restricted"
            elif isinstance(rule, str):  # Relative pattern/name rule
                pattern = rule.strip("/")
                if any(part == pattern for part in target_path.parts):
                    logger.debug(
                        f"Read check: Path {target_path} contains restricted component '{pattern}'"
                    )
                    return "restricted"
                if target_path.name == pattern:
                    logger.debug(
                        f"Read check: Path {target_path} filename matches restricted pattern '{pattern}'"
                    )
                    return "restricted"
        except Exception as e:
            logger.warning(
                f"Error checking restricted rule '{rule}' against path '{target_path}': {e}"
            )
            continue  # Skip rule on error

    # Check Outside Home Directory (Default Restricted)
    try:
        # Check if home_dir was resolved successfully earlier
        if home_dir and not (
            target_path == home_dir or target_path.is_relative_to(home_dir)
        ):
            logger.debug(
                f"Read check: Path {target_path} is outside home directory {home_dir}"
            )
            return "restricted"
    except Exception as e:  # Catch potential permission errors comparing paths
        logger.warning(
            f"Error checking if {target_path} is relative to home {home_dir}: {e}. Treating as restricted."
        )
        return "restricted"

    # Default Allowed
    logger.debug(f"Read check: Path {target_path} passed all checks, allowing.")
    return "allowed"


def _check_write_rules(target_path: Path) -> Union[str, Dict[str, str]]:
    """
    Checks the target path against write approval rules.

    Args:
        target_path: The absolute, resolved path to the file being written.

    Returns:
        "prohibited" with reason, "always_approved", or "needs_approval".
    """
    try:
        # Load and combine rules
        all_prohibited = _get_combined_rules(
            "DEFAULT_PROHIBITED_WRITE_PATTERNS", "PROHIBITED_WRITE_PATTERNS"
        )
        all_always_approved = _get_combined_rules(
            "DEFAULT_ALWAYS_APPROVED_WRITE_PATTERNS", "ALWAYS_APPROVED_WRITE_PATTERNS"
        )

        # Check Prohibited Patterns
        for pattern in all_prohibited:
            if isinstance(pattern, str):
                expanded_pattern = pattern
                if pattern.startswith("~"):
                    expanded_pattern = pattern.replace("~", str(Path.home()), 1)

                if fnmatch.fnmatch(str(target_path), expanded_pattern):
                    logger.debug(
                        f"Write check: Path {target_path} matches prohibited pattern '{pattern}'"
                    )
                    return {
                        "reason": f"Writing to path '{target_path}' is prohibited (matches pattern: {pattern})"
                    }

        # Check Always Approved Patterns
        for pattern in all_always_approved:
            if isinstance(pattern, str) and fnmatch.fnmatch(str(target_path), pattern):
                logger.debug(
                    f"Write check: Path {target_path} matches always approved pattern '{pattern}'"
                )
                return "always_approved"

        # Default to needing approval
        logger.debug(f"Write check: Path {target_path} requires approval.")
        return "needs_approval"

    except Exception as e:
        logger.error(
            f"Error checking write rules for path '{target_path}': {e}",
            exc_info=True,
        )
        # Be safe on errors
        return "needs_approval"


def _check_approve_all() -> bool:
    """
    Check if "Approve All" is active and valid.

    Returns:
        True if "Approve All" is active, False otherwise
    """
    global _approve_all_until

    # Check if --all flag was used
    if getattr(config, "ALLOW_ALL_COMMANDS", False):
        logger.info("Operation automatically approved due to --all flag")
        return True

    if _approve_all_until:
        if datetime.datetime.now() < _approve_all_until:
            logger.info(
                f"Operation automatically approved due to 'Approve All' until {_approve_all_until}"
            )
            return True
        else:
            logger.info("'Approve All' period has expired.")
            _approve_all_until = None  # Reset expired timer

    return False


def _check_shell_command(
    command: str,
) -> Union[bool, str, Dict[str, str], Tuple[bool, Dict[str, Any]]]:
    """
    Check if a shell command is allowed, prohibited, or needs approval.

    Args:
        command: The shell command to check

    Returns:
        - True if automatically approved
        - Dict with reason if prohibited
        - Tuple (False, analysis) if needs approval with safety analysis
        - "needs_approval" if safe but requires explicit approval
    """
    # Load and combine rules
    all_prohibited = _get_combined_rules(
        "DEFAULT_PROHIBITED_COMMANDS", "PROHIBITED_COMMANDS"
    )
    all_approved = _get_combined_rules("DEFAULT_APPROVED_COMMANDS", "APPROVED_COMMANDS")

    # Check Prohibited Commands
    for pattern in all_prohibited:
        if isinstance(pattern, str) and fnmatch.fnmatch(command, pattern):
            logger.warning(
                f"Operation denied: Command '{command}' matches prohibited pattern '{pattern}'."
            )
            return {
                "reason": f"Command '{command}' is prohibited (matches pattern: {pattern})"
            }

    # Check Approved Commands
    for pattern in all_approved:
        if isinstance(pattern, str) and fnmatch.fnmatch(command, pattern):
            logger.debug(
                f"Operation automatically approved: Command '{command}' matches pattern '{pattern}'."
            )
            return True

    # Enhanced analysis using command_analyzer
    is_safe, analysis = is_command_safe(command)

    # If --all flag is set and command is safe, auto-approve
    if getattr(config, "ALLOW_ALL_COMMANDS", False) and is_safe:
        logger.info(
            f"Command '{command}' auto-approved due to --all flag (safe command)"
        )
        return True

    if not is_safe:
        # Return the analysis for further processing
        return (False, analysis)

    # Command needs approval but is considered safe
    return "needs_approval"


def is_auto_approve_active() -> bool:
    """
    Public function to check if the auto-approval ('Approve All' or --all flag)
    is currently active.

    Returns:
        True if auto-approval is active, False otherwise.
    """
    # Reuse the internal check logic
    return _check_approve_all()


def request_approval(
    operation_type: str,
    operation_content: str,
    custom_choice: Optional[Tuple[str, str]] = None,
) -> Union[bool, str, Dict[str, str]]:
    """
    Checks if an operation requires approval based on predefined constants
    and requests user confirmation if the operation is restricted.
    Handles "Approve All" state and cancellation.

    Args:
        operation_type: The type of operation (e.g., "shell", "read", "write", "fetch").
        operation_content: The specific content (command, path, URL).
        custom_choice: An optional tuple (key, display_text) for a custom choice
                       to present to the user.

    Returns:
        True if the operation is approved (automatically, by user, or via Approve All).
        Dict with reason if the operation is prohibited or denied by the user.
        "cancelled" if the user explicitly cancels the operation.
        The custom_choice key string if the custom choice was selected.
    """
    logger.debug(
        f"Requesting approval for type='{operation_type}', content='{operation_content[:100]}...'"
    )

    # Check "Approve All" status first
    if _check_approve_all():
        return True

    # --- Specific logic for operation types ---
    if operation_type == "shell":
        command = operation_content.strip()
        if not command:
            logger.warning("Empty shell command received for approval check.")
            return {"reason": "Empty shell command received"}

        # Check command against rules and safety analysis
        check_result = _check_shell_command(command)

        # Handle different check results
        if check_result is True:
            # Automatically approved
            return True
        elif isinstance(check_result, dict) and "reason" in check_result:
            # Prohibited with reason
            return check_result
        elif isinstance(check_result, tuple) and len(check_result) == 2:
            # Command needs approval with safety analysis
            _, analysis = check_result

            # Display warning about the command
            if analysis["danger_level"] in ["medium", "high", "critical"]:
                _display_command_safety_warning(command, analysis)

                # For critical commands, require additional confirmation
                if analysis["danger_level"] == "critical":
                    q_console.print(
                        "[bold red]This command could cause severe system damage![/bold red]"
                    )
                    q_console.print(
                        "Type the command again to confirm you understand the risks:"
                    )
                    confirmation = q_console.input("> ")
                    if confirmation.strip() != command.strip():
                        q_console.print(
                            "[yellow]Confirmation failed. Command execution cancelled.[/yellow]"
                        )
                        return "cancelled"

                    # Create a reason string from the analysis reasons
                    # risk_reasons = ", ".join(analysis["reasons"])
                    # risk_message = f"Command has {analysis['danger_level']} risk level: {risk_reasons}"
                    # Note: risk_message is not currently used after confirmation

        # Define custom choice for shell if needed (e.g., Modify)
        shell_custom_choice = ("m", "Modify[m]")
        shell_custom_choice_key = shell_custom_choice[0]

        # Ask for user approval, including the custom choice
        q_console.print(f"[bold yellow]▶ Approve command:[/]\n[purple]{command}[/]")
        user_choice_key = _ask_confirmation("", custom_choice=shell_custom_choice)
        q_console.print("")

        # Handle the user's choice, passing the custom choice key
        return _handle_user_choice(
            user_choice_key,
            f"command '{command}'",
            custom_choice_key=shell_custom_choice_key,
        )

    elif operation_type == "read":
        path_str = operation_content.strip()
        if not path_str:
            logger.warning("Empty path received for read approval check.")
            return {"reason": "Empty path received for read operation"}

        try:
            # Resolve the path relative to CWD (or absolute if given)
            target_path = Path(path_str).resolve(strict=False)
        except Exception as e:
            logger.error(
                f"Error resolving path '{path_str}' for read approval: {e}",
                exc_info=True,
            )
            return {"reason": f"Error resolving path '{path_str}': {e}"}

        # Check rules using the helper function
        read_check_result = _check_read_rules(target_path)

        if isinstance(read_check_result, dict) and "reason" in read_check_result:
            logger.warning(
                f"Operation denied: Reading path '{target_path}' is prohibited: {read_check_result['reason']}"
            )
            return read_check_result
        elif read_check_result == "allowed":
            logger.debug(
                f"Operation automatically approved: Reading path '{target_path}' is allowed."
            )
            return True
        elif read_check_result == "restricted":
            logger.info(
                f"Reading path '{target_path}' is restricted. Requesting confirmation."
            )
            # Ask user for confirmation
            prompt = f"▷ Approve reading restricted path: [bold cyan]{target_path}[/bold cyan]"
            user_choice_key = _ask_confirmation(prompt)

            return _handle_user_choice(user_choice_key, f"reading path '{target_path}'")
        else:
            # Should not happen
            logger.error(
                f"Unexpected result '{read_check_result}' from _check_read_rules for path '{target_path}'. Denying."
            )
            return {
                "reason": f"Unexpected result '{read_check_result}' from read rules check"
            }

    elif operation_type == "write":
        # Extract the file path from the operation content
        content_lines = operation_content.strip().split("\n")
        path_str = content_lines[0]

        # If the content starts with "File: ", extract the path
        if path_str.startswith("File: "):
            path_str = path_str[6:].strip()

        if not path_str:
            logger.warning("Empty path received for write approval check.")
            return {"reason": "Empty path received for write operation"}

        try:
            # Resolve the path relative to CWD (or absolute if given)
            target_path = Path(path_str).resolve(strict=False)
        except Exception as e:
            logger.error(
                f"Error resolving path '{path_str}' for write approval: {e}",
                exc_info=True,
            )
            return {"reason": f"Error resolving path '{path_str}': {e}"}

        # Check write rules
        write_check_result = _check_write_rules(target_path)

        if isinstance(write_check_result, dict) and "reason" in write_check_result:
            logger.warning(
                f"Operation denied: Writing to path '{target_path}' is prohibited: {write_check_result['reason']}"
            )
            q_console.print(
                f"[bold red]Denied:[/bold red] {write_check_result['reason']}"
            )
            return write_check_result

        elif write_check_result == "always_approved":
            logger.debug(
                f"Operation automatically approved: Writing to path '{target_path}' is always approved."
            )
            return True

        elif write_check_result == "needs_approval":
            logger.info(
                f"Writing to path '{target_path}' requires approval. Requesting confirmation."
            )

            # Show a preview of the content if available
            if len(content_lines) > 1:
                # Show a condensed preview (first few lines)
                preview_lines = content_lines[1:6]  # Show up to 5 lines
                if len(content_lines) > 6:
                    preview_lines.append("...")
                preview = "\n".join(preview_lines)
                q_console.print(f"[dim]Preview of content to write:[/dim]\n{preview}\n")

            # Ask user for confirmation
            prompt = f" ▶Approve writing to path: [bold cyan]{target_path}[/bold cyan]"
            user_choice_key = _ask_confirmation(prompt)

            return _handle_user_choice(
                user_choice_key, f"writing to path '{target_path}'"
            )
        else:
            # Should not happen
            logger.error(
                f"Unexpected result '{write_check_result}' from _check_write_rules for path '{target_path}'. Denying."
            )
            return {
                "reason": f"Unexpected result '{write_check_result}' from write rules check"
            }

    # --- Placeholder logic for other operation types ---
    elif operation_type == "fetch":
        url = operation_content
        logger.info(
            f"Approval check for fetch '{url}' not yet implemented. Defaulting to approved."
        )
        # TODO: Add fetch rules
        return True  # Placeholder
    else:
        logger.error(f"Operation denied: Unknown operation type '{operation_type}'.")
        return {"reason": f"Unknown operation type '{operation_type}'"}