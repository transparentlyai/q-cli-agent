"""
Shell operator for executing shell commands.
"""

# pyright: basic, reportReturnType=false, reportAssignmentType=false

import json
import subprocess
from typing import Any, Dict, Literal, TypedDict, Union

# Import prompt from prompt_toolkit
from prompt_toolkit import prompt as prompt_toolkit_prompt

from q.cli.approvals import request_approval
from q.cli.qconsole import (
    q_console,
    show_error,
    show_spinner,
    show_success,
    show_warning,
)
from q.core.constants import (
    OPEARION_SPINNER_COMMAND_COLOR,
    OPEARION_SPINNER_MESSAGE_COLOR,
)
from q.core.logging import get_logger

# Removed HTML import as it's no longer needed for the prompt string


logger = get_logger(__name__)


# Define type for approval status return
class ApprovalDeniedDict(TypedDict):
    reason: str


# Include str for custom choices like 'm'
ApprovalStatus = Union[bool, str, ApprovalDeniedDict]


def _execute_shell(command: str) -> dict:
    """
    Executes a shell command and captures its output. (Internal use)

    Args:
        command: The shell command string to execute.

    Returns:
        A dictionary containing:
            - 'command': The original command string.
            - 'stdout': The standard output as a string.
            - 'stderr': The standard error as a string.
            - 'exit_code': The exit code of the command.
    """
    logger.debug(f"Executing shell command: {command}")
    result = {"command": command, "stdout": "", "stderr": "", "exit_code": None}
    try:
        # Using subprocess.run for simplicity and capturing output
        process = subprocess.run(
            command,
            shell=True,  # Execute command through the shell
            capture_output=True,  # Capture stdout and stderr
            text=True,  # Decode stdout/stderr as text
            check=False,  # Do not raise exception on non-zero exit code
        )
        result["stdout"] = process.stdout.strip()
        result["stderr"] = process.stderr.strip()
        result["exit_code"] = process.returncode
        logger.debug(f"Command finished with exit code: {process.returncode}")
        if process.stdout:
            logger.debug(f"Stdout:\n{process.stdout.strip()}")
        if process.stderr:
            logger.warning(f"Stderr:\n{process.stderr.strip()}")

    except Exception as e:
        logger.error(f"Failed to execute command '{command}': {e}", exc_info=True)
        result["stderr"] = str(e)
        result["exit_code"] = -1  # Indicate an execution error

    return result


def run_shell(command: str) -> Dict[str, Any]:
    """
    Requests approval (Yes/No/Cancel/All/Modify), executes a shell command if approved,
    and returns the results in a structured format. Allows modification if requested.

    Args:
        command: The shell command string to execute.

    Returns:
        A dictionary containing:
            - 'reply': A message with command execution details as a JSON string
            - 'error': Error message if an error occurred, None otherwise
    """
    logger.info(f"Attempting to run shell command: '{command}'")
    result = {"reply": "", "error": None}

    original_command = command  # Store the original command
    current_command = command  # Use a variable that can be modified
    modification_reason = None  # Variable to store the reason

    while True:  # Loop for approval and potential modification
        logger.info(f"Requesting approval for shell command: '{current_command}'")
        # Pass the command that might have been modified
        approval_status = check_approval(current_command, result)

        if approval_status is True:
            # Approved, break loop and proceed to execution
            break
        elif (
            isinstance(approval_status, str) and approval_status == "m"
        ):  # Handle custom 'modify' choice
            show_warning("User chose to modify the command.")
            # Use prompt_toolkit.prompt with the current command as default
            try:
                # Use a plain string for the prompt to avoid HTML parsing issues
                new_command = prompt_toolkit_prompt(
                    " Enter modified command: ",
                    default=current_command,
                ).strip()

                # Prompt for the reason for modification
                if (
                    new_command != current_command
                ):  # Only ask for reason if command actually changed
                    modification_reason = prompt_toolkit_prompt(
                        " Reason for modification: ",
                        default="",  # Start with empty default
                    ).strip()
                    if not modification_reason:
                        logger.warning("No reason provided for command modification.")
                        # Optionally handle empty reason, for now just log and continue

            except EOFError:  # Handle Ctrl+D
                show_warning("Input cancelled. Cancelling operation.")
                result["reply"] = "STOP: Command modification cancelled (input EOF)"
                result["error"] = "Command modification cancelled (input EOF)"
                return result
            except KeyboardInterrupt:  # Handle Ctrl+C
                show_warning("Input interrupted. Cancelling operation.")
                result["reply"] = (
                    "STOP: Command modification cancelled (input interrupt)"
                )
                result["error"] = "Command modification cancelled (input interrupt)"
                return result

            if not new_command:
                show_warning("No command entered. Cancelling operation.")
                result["reply"] = "STOP: Command modification cancelled (empty command)"
                result["error"] = "Command modification cancelled (empty command)"
                return result  # Cancel if empty command is entered after modify
            current_command = new_command  # Update command and loop again for approval
            continue  # Go back to the start of the loop
        elif isinstance(approval_status, dict) and "reason" in approval_status:
            # Denied with reason (check_approval already updated result)
            return result
        elif approval_status == "cancelled":
            # Cancelled by user (check_approval already updated result)
            return result
        else:
            # Unexpected status
            show_error(f"Unexpected approval status: {approval_status}")
            logger.warning(
                f"Unexpected approval status '{approval_status}' for shell operation on '{current_command}'. Denying."
            )
            result["reply"] = "STOP: Command execution failed"
            result["error"] = f"Unexpected approval status '{approval_status}'."
            return result

    # If we break out of the loop, the command is approved (approval_status is True)
    # Execute the *current_command* (which might be the original or modified)
    try:
        # Execute the command with a spinner
        with show_spinner(
            f"[{OPEARION_SPINNER_MESSAGE_COLOR}]Running command:[/] [{OPEARION_SPINNER_COMMAND_COLOR}]{current_command}[/]"
        ):
            shell_result = _execute_shell(current_command)  # Execute current_command

        # Create a command result dictionary
        command_result = {
            "command": shell_result["command"],
            "stdout": shell_result["stdout"],
            "stderr": shell_result["stderr"],
            "exit_code": shell_result["exit_code"],
        }

        # Add modification info if the command was changed
        if current_command != original_command:
            command_result["modified_from"] = original_command
            if modification_reason:  # Add reason only if provided
                command_result["modification_reason"] = modification_reason
            logger.info(
                f"Command was modified from '{original_command}' to '{current_command}' before execution."
            )

        # Handle the result based on exit code
        if shell_result["exit_code"] == 0:
            show_success(f"Command executed successfully: [purple]{current_command}[/]")

            # Convert to JSON string
            result["reply"] = f"Command execution result:\n{json.dumps(command_result)}"
        else:
            error_message = (
                shell_result["stderr"]
                if shell_result["stderr"]
                else f"Command exited with non-zero status: {shell_result['exit_code']}"
            )
            show_error(f"Command failed: [purple]{error_message}[/]")

            # Convert to JSON string
            result["reply"] = (
                f"STOP: Command execution result:\n{json.dumps(command_result)}"
            )
            result["error"] = error_message

    except Exception as e:
        show_error(f"Error executing command: {e}")
        return handle_error(
            result,
            f"An unexpected error occurred: {e}",
            "STOP: Command execution failed",
            "error",
            exc_info=True,
        )

    return result


def check_approval(
    command: str, result: Dict[str, Any]
) -> Union[bool, str, Dict[str, Any]]:
    """
    Check if the shell operation is approved.

    Args:
        command: The shell command to check
        result: The result dictionary to update

    Returns:
        True if approved, the custom choice key string ('m'),
        or the updated result dictionary if denied/cancelled
    """
    # Pass the custom_choice to request_approval
    approval_status: ApprovalStatus = request_approval(
        operation_type="shell",
        operation_content=command,
        custom_choice=("m", "Modify[m]"),
    )

    # The return value from request_approval is directly returned by this function
    # if it's not True, a dict, or 'cancelled'. This allows 'm' to be passed back.
    if isinstance(approval_status, dict) and "reason" in approval_status:
        reason = approval_status["reason"]
        show_warning(f"Command execution denied: {reason}")
        logger.warning(f"Shell operation denied: {reason}")
        result["reply"] = f"STOP: Command execution failed"
        result["error"] = reason
        return result
    elif approval_status == "cancelled":
        show_warning(f"Command execution cancelled: {command}")
        logger.warning(f"Shell operation cancelled by user for command: '{command}'")
        result["reply"] = f"STOP: Command execution cancelled"
        result["error"] = f"Shell operation cancelled by user for command '{command}'."
        return result
    elif (
        approval_status is not True and approval_status != "m"
    ):  # Explicitly check for 'm' not being handled here
        show_error(f"Unexpected approval status: {approval_status}")
        logger.warning(
            f"Unexpected approval status '{approval_status}' for shell operation on '{command}'. Denying."
        )
        result["reply"] = f"STOP: Command execution failed"
        result["error"] = f"Unexpected approval status '{approval_status}'."
        return result
    elif approval_status == "m":
        # If 'm' is returned, we don't update the result dictionary here.
        # The calling function (run_shell) will handle the modification prompt.
        logger.debug(f"User chose to modify shell command: {command}")
        return "m"  # Return the custom choice key

    # If none of the above, it must be True (approved)
    logger.debug(f"Approval granted for shell command: {command}")
    return True


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
