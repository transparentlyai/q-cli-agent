# pyright: basic, reportAttributeAccessIssue=false
"""
Command registry and handlers for the Q CLI.

This module centralizes the handling of all CLI commands like exit, quit, and /save.
Commands are registered in a registry and can be easily added or modified.
"""

import os
import platform
import shlex
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from q import __version__
from q.cli.qconsole import q_console, show_error, show_success, show_warning
from q.core import constants
from q.core.config import config
from q.core.logging import get_logger
from q.core.session import (
    get_session_summary,  # Import get_session_summary for load-session
)
from q.core.session import (  # Import new functions
    handle_recovery_ui,
    load_conversation_pickle,
    save_conversation_pickle,
)
from q.utils import llm_helpers  # Import for transplant command
from q.utils.config_updater import update_config_provider_model
from q.utils.helpers import get_current_model, save_response_to_file
from q.utils.mcp_servers import check_mcp_servers_file, get_all_mcp_servers

# Import MCP client
try:
    from q.cli.mcp_commands import (
        handle_mcp_add_server_command,
        handle_mcp_connect_command,
        handle_mcp_disconnect_command,
        handle_mcp_fix_command,
        handle_mcp_list_servers_command,
        handle_mcp_list_tools_command,
        handle_mcp_remove_server_command,
    )
    from q.code.mcp import mcp_connect, mcp_disconnect, mcp_list_tools

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Import rich.markdown for displaying README
try:
    from rich.markdown import Markdown
    RICH_MARKDOWN_AVAILABLE = True
except ImportError:
    RICH_MARKDOWN_AVAILABLE = False


# Initialize logger
logger = get_logger(__name__)

# Type definition for command handlers
CommandHandler = Callable[[str, Any], bool]

# Command registry to store all available commands
# Format: {command_name: (handler_function, description)}
command_registry: Dict[str, Tuple[CommandHandler, str]] = {}


def register_command(name: str, handler: CommandHandler, description: str) -> None:
    """
    Register a command in the command registry.

    Args:
        name: The command name (what the user types)
        handler: The function that handles the command
        description: A short description of what the command does
    """
    command_registry[name] = (handler, description)
    logger.debug(f"Registered command: {name}")


def is_command(input_text: str) -> bool:
    """
    Check if the input text starts with a registered command.

    Args:
        input_text: The user input text

    Returns:
        True if the input starts with a registered command, False otherwise
    """
    # Extract the potential command part (first word)
    stripped_input = input_text.strip()
    if not stripped_input:
        return False
    command_parts = stripped_input.split(maxsplit=1)
    command = command_parts[0].lower()

    # Check if it's a registered command
    return command in command_registry


def handle_command(input_text: str, context: Optional[Dict[str, Any]] = None) -> Any:
    """
    Process a command if it matches a registered command, otherwise return the input.

    Args:
        input_text: The user input text
        context: Optional context data needed by command handlers

    Returns:
        False if it was an exit command and the loop should break.
        None if the command was handled successfully.
        input_text if it was not a command and should be sent to the LLM.
    """
    stripped_input = input_text.strip()
    if not stripped_input:
        return None  # No input, but command handling is "done" (do nothing, continue loop)

    # Check if the input starts with a registered command *before* parsing
    potential_command_parts = stripped_input.split(maxsplit=1)
    potential_command = potential_command_parts[0].lower()

    if potential_command not in command_registry:
        # Input does not start with a known command, treat as prompt for LLM
        return input_text

    # --- Input starts with a known command, proceed with parsing and execution ---
    try:
        # Use shlex to handle potential quotes in arguments ONLY for commands
        command_parts = shlex.split(stripped_input)
    except ValueError as e:
        # Handle potential parsing errors within command arguments, e.g., unmatched quotes
        show_error(f"Invalid command syntax: {e}")
        logger.warning(f"Command parsing error for input '{stripped_input}': {e}")
        return None  # Continue loop after showing error

    # Command is already confirmed to be in registry from the check above
    command = command_parts[0].lower()

    # Get arguments if any
    args = " ".join(command_parts[1:]) if len(command_parts) > 1 else ""

    # Get the handler and execute it
    handler, _ = command_registry[command]
    logger.debug(f"Executing command: {command} with args: '{args}'")
    # The handler returns True if it handled the command (and loop continues),
    # or False if it's an exit command.
    result = handler(args, context or {})
    return False if result is False else None  # Convert True to None for handled command


def list_commands() -> None:
    """Display a list of all available commands with their descriptions."""
    q_console.print("\n[bold]Available Commands:[/bold]")

    for cmd, (_, description) in sorted(command_registry.items()):
        q_console.print(f"  [cyan]{cmd}[/cyan]: {description}")

    q_console.print("")


def get_all_commands() -> List[Tuple[str, str]]:
    """
    Get all registered commands with their descriptions.

    Returns:
        List of tuples containing (command_name, description)
    """
    return [(cmd, desc) for cmd, (_, desc) in sorted(command_registry.items())]


def get_slash_commands() -> List[Tuple[str, str]]:
    """
    Get all slash commands with their descriptions.

    Returns:
        List of tuples containing (command_name, description) for slash commands
    """
    return [
        (cmd, desc)
        for cmd, (_, desc) in sorted(command_registry.items())
        if cmd.startswith("/")
    ]


def clear_terminal_screen():
    """
    Clear the terminal screen in a cross-platform way.
    """
    # Check the operating system and use the appropriate command
    if platform.system() == "Windows":
        os.system("cls")
    else:  # For Linux and macOS
        os.system("clear")

    logger.debug("Terminal screen cleared")


class CommandCompleter(Completer):
    """
    Completer for Q commands and their arguments.
    """

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterator[Completion]:
        text = document.text_before_cursor
        stripped_text = text.lstrip()
        words = stripped_text.split()
        word_count = len(words)
        on_space = text.endswith(" ")

        # === Case 1: No input or only whitespace ===
        if not stripped_text:
            for cmd, description in get_all_commands():
                yield Completion(
                    cmd, start_position=0, display=cmd, display_meta=description
                )
            return

        # === Case 2: Typing the first word (command) ===
        # Suggest commands if we are typing the first word and not immediately after a space
        if word_count == 1 and not on_space:
            word = words[0]
            start_pos = -len(word)
            is_slash_command_context = word.startswith("/")
            # Check if cursor is at the end of the word being typed
            # Use original text length for cursor position check
            is_start_of_line = document.cursor_position == len(text)

            if is_slash_command_context:
                for cmd, description in get_slash_commands():
                    if cmd.startswith(word):
                        yield Completion(
                            cmd,
                            start_position=start_pos,
                            display=cmd,
                            display_meta=description,
                        )
            # Only suggest non-slash commands if it's the very first word
            elif document.cursor_position <= len(
                word
            ):  # Ensure we are completing the first word
                for cmd, description in get_all_commands():
                    if cmd.startswith(word) and not cmd.startswith("/"):
                        yield Completion(
                            cmd,
                            start_position=start_pos,
                            display=cmd,
                            display_meta=description,
                        )
            return  # Finished suggesting commands

        # === Case 3: After a command, potentially typing arguments ===
        # Trigger if: we have more than 1 word OR we have exactly 1 word and are on a space
        if word_count > 1 or (word_count == 1 and on_space):
            command = words[0].lower()

            # --- Argument completion for /transplant ---\n
            if command == "/transplant":
                # Argument is the word being typed, or empty if just after space
                current_arg = words[1] if word_count > 1 and not on_space else ""
                # Replace current arg or insert at cursor(0)
                start_pos = -len(current_arg) if word_count > 1 and not on_space else 0

                for model_info in constants.MODELS:
                    provider = model_info["provider"]
                    model_name = model_info["model"]
                    description = model_info["description"]
                    full_model_str = f"{provider}/{model_name}"

                    # Suggest if the model string starts with what user typed
                    if full_model_str.startswith(current_arg):
                        yield Completion(
                            full_model_str,
                            start_position=start_pos,
                            display=full_model_str,
                            display_meta=description,
                        )
                return  # Handled /transplant args

            # --- Argument completion for /mcp-connect ---\n
            if command == "/mcp-connect" and MCP_AVAILABLE:
                # Argument is the word being typed, or empty if just after space
                current_arg = words[1] if word_count > 1 and not on_space else ""
                # Replace current arg or insert at cursor(0)
                start_pos = -len(current_arg) if word_count > 1 and not on_space else 0

                # Check if the MCP servers file is valid
                is_valid, _ = check_mcp_servers_file()
                if is_valid:
                    for server_name in get_all_mcp_servers().keys():
                        # Suggest if the server name starts with what user typed
                        if server_name.startswith(current_arg):
                            yield Completion(
                                server_name,
                                start_position=start_pos,
                                display=server_name,
                                display_meta=f"MCP Server: {server_name}",
                            )
                return  # Handled /mcp-connect args

            # --- Argument completion for /mcp-remove ---\n
            if command == "/mcp-remove" and MCP_AVAILABLE:
                # Argument is the word being typed, or empty if just after space
                current_arg = words[1] if word_count > 1 and not on_space else ""
                # Replace current arg or insert at cursor(0)
                start_pos = -len(current_arg) if word_count > 1 and not on_space else 0

                # Only show user-defined servers for removal
                from q.utils.mcp_servers import load_user_mcp_servers

                user_servers, _ = load_user_mcp_servers()
                for server_name in user_servers.keys():
                    # Suggest if the server name starts with what user typed
                    if server_name.startswith(current_arg):
                        yield Completion(
                            server_name,
                            start_position=start_pos,
                            display=server_name,
                            display_meta=f"User-defined MCP Server: {server_name}",
                        )
                return  # Handled /mcp-remove args

            # --- Argument completion for /save-last-response, /save-session, /load-session ---\n
            # These commands expect a file path, which is handled by PathCompleter in qprompt.py
            # We don't need to yield specific completions here, but we stop processing.\n
            if command in ["/save-last-response", "/save-session", "/load-session"]:
                return

            # --- Argument completion for /t-budget ---\n
            if command == "/t-budget":
                # We expect an integer argument. We can't suggest specific integers,\n
                # but we can indicate that an integer is expected.\n
                # If the user has already typed something, don't suggest anything,\n
                # let them type the number.\n
                if word_count == 1 or (word_count == 2 and not on_space):
                    # Suggest a placeholder or hint if no number is started\n
                    if not words[-1].isdigit():
                        yield Completion(
                            " ",
                            start_position=0 if word_count == 1 else -len(words[-1]),
                            display="",
                            display_meta="Thinking budget in tokens",
                        )
                return  # Handled /t-budget args

            # --- Add other command argument completions here ---\n
            # Example:\n
            # if command == "/some_other_command":\n
            #    # yield completions for its arguments\n
            #    return\n

        # Default: No specific completions found for this state\n
        yield from []  # Explicitly yield nothing


# Command handlers


def handle_t_budget_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /t-budget command to change the Vertex AI thinking budget.

    Args:
        args: The integer value for the thinking budget.
        context: Context containing the conversation instance.

    Returns:
        True to indicate the command was handled successfully (continue loop).
    """
    conversation = context.get("conversation")
    if not conversation:
        show_error("No active conversation instance found.")
        return True

    if conversation.provider != "vertexai":
        show_error(
            f"Thinking budget can only be set for Vertex AI models. Current provider is {conversation.provider}."
        )
        return True

    if not args:
        # Show current budget if no argument is provided
        current_budget = getattr(
            conversation,
            "_vertexai_thinking_budget",
            constants.VERTEXAI_THINKING_BUDGET,
        )
        show_success(f"Current Vertex AI thinking budget is: {current_budget}")
        return True

    try:
        new_budget = int(args.strip())
        if new_budget < 0:
            show_error("Thinking budget must be a non-negative integer.")
            return True
        if new_budget > 24575:
            show_error("Thinking budget cannot exceed 24575 tokens.")
            return True

        conversation.set_thinking_budget(new_budget)
        show_success(f"Vertex AI thinking budget set to: {new_budget}")
        return True

    except ValueError:
        # Corrected usage message
        show_error("Invalid argument. Usage: /t-budget ")
        return True
    except Exception as e:
        show_error(f"An unexpected error occurred: {e}")
        logger.error(f"Error handling /t-budget command: {e}", exc_info=True)
        return True


def handle_exit_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the exit/quit command.

    Args:
        args: Command arguments (unused)
        context: Command context (unused)

    Returns:
        False to indicate the command was handled and the app should exit.
    """
    logger.info("Exit command received")
    return False  # Signal exit


def handle_save_last_response_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /save-last-response command to save the last model response to a file.

    Args:
        args: The file path where to save the response.
        context: Context containing the latest_response.

    Returns:
        True to indicate the command was handled successfully (continue loop).
    """
    if not args:
        # Corrected usage message
        show_error("No file path provided. Usage: /save-last-response ")
        return True

    # Expecting 'latest_response' to be present in the context dictionary
    latest_response = context.get("latest_response", "")
    if not latest_response:
        show_warning("No previous model response to save.")
        return True

    success, message = save_response_to_file(latest_response, args)
    if success:
        show_success(message)
    else:
        show_error(message)

    return True


def handle_list_commands(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the help command to display available commands.

    Args:
        args: Command arguments (unused)
        context: Command context (unused)

    Returns:
        True to indicate the command was handled successfully (continue loop).\n
    """
    list_commands()
    return True  # Command was handled


def handle_help_question_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /help command.
    If no arguments are provided, display the README.md content.
    If arguments are provided, answer the question using README.md as context via the LLM.

    Args:
        args: The user's question or empty string.
        context: Context containing the conversation instance and status function.

    Returns:
        True to indicate the command was handled successfully (continue loop).
    """
    readme_path = "README.md"
    readme_content = ""
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            readme_content = f.read()
        logger.debug(f"Successfully read {readme_path}")
    except FileNotFoundError:
        show_error(f"Error: {readme_path} not found.")
        logger.error(f"{readme_path} not found for /help command.")
        return True
    except Exception as e:
        show_error(f"Error reading {readme_path}: {e}")
        logger.error(
            f"Error reading {readme_path} for /help command: {e}", exc_info=True
        )
        return True

    if not args:
        # No arguments provided, display README content
        q_console.print("\n[bold]Q Documentation (README.md):[/bold]\n")
        if RICH_MARKDOWN_AVAILABLE:
            markdown_content = Markdown(readme_content)
            q_console.print(markdown_content)
        else:
            # Fallback to plain print if rich.markdown is not available
            q_console.print(readme_content)
        q_console.print("")  # Add a newline at the end
        return True

    # Arguments provided, use LLM to answer the question
    conversation = context.get("conversation")
    status_func = context.get("status_func")

    if not conversation:
        show_error("No active conversation instance found.")
        return True

    if not status_func:
        show_error("Internal error: Status function not available.")
        logger.error(
            "handle_help_question_command called without status_func in context"
        )
        return True

    # Construct the prompt for the LLM
    prompt = f"""
You are Q, a command-line AI assistant. The user is asking a question about your functionality.
Below is the content of your README.md file, which describes your features, commands, and usage.
Use this README content as your primary source of information to answer the user's question.
If the answer is not explicitly in the README, state that you cannot find the information there.
Do not use external knowledge beyond the provided README content and your inherent understanding of being an AI assistant.

--- README.md Content ---
{readme_content}
--- End README.md Content ---

Based on the README.md content provided above, answer the following question:

{args}
"""

    # Send the prompt to the LLM
    try:
        with status_func("Thinking..."):
            # Send the constructed prompt. Note: This adds the prompt to the conversation history.
            # For a pure "help" command that doesn't affect the main conversation flow,
            # we might consider a separate LLM call that doesn't modify history,
            # but the current LLMConversation class is designed around history.
            # For now, adding it to history is acceptable.
            response = conversation.send_message(prompt)

        # Display the response
        q_console.print(f"\n[bold]Help Response:[/bold]\n{response}\n")

    except Exception as e:
        show_error(f"An error occurred while getting help from the model: {e}")
        logger.error(f"Error getting help response from LLM: {e}", exc_info=True)

    return True


def handle_clear_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /clear command to clear the chat history and terminal screen.

    Args:
        args: Command arguments (unused)
        context: Context containing the conversation instance

    Returns:
        True to indicate the command was handled successfully (continue loop).\n
    """
    # First clear the terminal screen
    clear_terminal_screen()

    # Then clear the conversation history
    conversation = context.get("conversation")
    if not conversation:
        show_warning("No active conversation to clear.")
        return True  # Command was handled\n

    # Clear the conversation history but keep the system prompt
    conversation.clear_conversation(keep_system_prompt=True)

    # Show the Q version and model info again (similar to startup)
    # Pass conversation to get potentially updated model info
    q_console.print(
        f"[#666666]Q ver:{__version__} - brain:{get_current_model(conversation)}[/#666666]"  # Pass conversation
    )

    # Show success message
    show_success("Context cleared.")

    return True  # Command was handled


def handle_recover_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /recover command to recover a previous session.

    Args:
        args: Command arguments (unused)
        context: Command context containing the conversation instance and status function

    Returns:
        True to indicate the command was handled successfully (continue loop).\n
    """
    conversation = context.get("conversation")
    status_func = context.get("status_func")  # Get status function from context

    if not conversation:
        show_error("No active conversation to recover into.")
        return True  # Command was handled\n

    if not status_func:
        show_error("Internal error: Status function not available for recovery.")
        logger.error("handle_recover_command called without status_func in context")
        return True

    # Use the shared recovery UI handler
    handle_recovery_ui(conversation, q_console, status_func)

    return True  # Command was handled


def handle_transplant_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /transplant command to switch the LLM provider and model.

    Args:
        args: The provider/model string (e.g., "anthropic/claude-3-7-sonnet-latest")
        context: Context containing the conversation instance

    Returns:
        True to indicate the command was handled successfully (continue loop).\n
    """
    conversation = context.get("conversation")  # Get conversation early

    if not args:
        # Corrected usage message
        show_error("No provider/model specified. Usage: /transplant /")

        # Show currently active model
        if conversation:
            # Use the helper function to get the current model from the conversation object
            current_model_str = get_current_model(conversation)
            # Need provider too for the display string
            current_provider = conversation.provider
            q_console.print(
                f"[bold yellow]Currently using:[/bold yellow] [cyan]{current_provider}/{current_model_str}[/cyan]"
            )
        else:
            q_console.print(
                "[yellow]Could not determine the currently active model.[/yellow]"
            )

        # Show available models
        q_console.print("[bold]Available brains:[/bold]")
        for model_info in constants.MODELS:
            q_console.print(
                f"  [cyan]{model_info['provider']}/{model_info['model']}[/cyan]: {model_info['description']}"
            )
        return True  # Command was handled (though with an error)\n

    # Validate format
    if "/" not in args:
        # Corrected usage message
        show_error("Invalid format. Use: /transplant /")
        return True  # Command was handled\n

    target_provider, target_model = args.split("/", 1)
    target_provider = target_provider.lower()

    # Find the model in constants
    found_model = None
    for model_info in constants.MODELS:
        if (
            model_info["provider"] == target_provider
            and model_info["model"] == target_model
        ):
            found_model = model_info
            break

    if not found_model:
        show_error(f"Model '{args}' not found or not supported.")
        # Show available models again for convenience
        q_console.print("[bold]Available models:[/bold]")
        for model_info in constants.MODELS:
            q_console.print(
                f"  [cyan]{model_info['provider']}/{model_info['model']}[/cyan]: {model_info['description']}"
            )
        return True  # Command was handled\n

    # Check if conversation object exists (should always exist here if called from main loop)
    if not conversation:
        show_error("Internal error: No active conversation instance found.")
        logger.error("handle_transplant_command called without conversation in context")
        return True  # Command was handled\n

    # Check if already using the target model
    # Use get_current_model to handle potential prefix inconsistencies if needed, though direct comparison should work
    if (
        conversation.provider == target_provider
        and get_current_model(conversation) == target_model
    ):
        show_warning(f"Already using model '{args}'. No change made.")
        return True  # Command was handled\n

    try:
        logger.info(
            f"Attempting transplant to provider={target_provider}, model={target_model}"
        )

        # Update conversation attributes BEFORE setup
        conversation.provider = target_provider
        conversation.model = target_model

        # Re-run provider setup to update API keys, env vars, etc.
        # This might raise errors if keys are missing for the new provider
        conversation._setup_provider_config()

        # Update other parameters based on new provider defaults
        # We use _get_provider_config which checks config first, then provider defaults
        conversation.temperature = conversation._get_provider_config(
            "TEMPERATURE", constants.DEFAULT_TEMPERATURE
        )
        conversation.max_tokens = conversation._get_provider_config(
            "MAX_TOKENS", constants.DEFAULT_MAX_TOKENS
        )
        new_tokens_per_min = conversation._get_provider_config(
            "TOKENS_PER_MIN",
            llm_helpers.get_default_tokens_per_min(conversation.provider),
        )

        # Update the rate limiter
        if hasattr(conversation, "rate_limiter") and conversation.rate_limiter:
            conversation.rate_limiter.update_tokens_per_min(new_tokens_per_min)
            conversation.tokens_per_min = (
                new_tokens_per_min  # Also update the conversation attribute
            )
            logger.debug(f"Updated rate limiter to {new_tokens_per_min} tokens/min")
        else:
            logger.warning(
                "Rate limiter not found on conversation object during transplant"
            )

        # Update the configuration file for future sessions
        config_updated = update_config_provider_model(target_provider, target_model)
        if config_updated:
            logger.info(f"Updated configuration file with new provider/model: {args}")
        else:
            logger.warning(
                f"Failed to update configuration file with new provider/model: {args}"
            )

        # Update the header/info line - pass conversation object
        q_console.print(
            f"[#666666]Q ver:{__version__} - brain:{get_current_model(conversation)}[/#666666]"  # Pass conversation
        )

        success_message = f"Successfully transplanted brain to: [purple]{target_provider}/{target_model}[/]"
        if config_updated:
            success_message += " (configuration updated for future sessions)"

        show_success(success_message)
        logger.info(
            f"Transplant successful. New model: {conversation.model}, Provider: {conversation.provider}"
        )
        logger.debug(
            f"New temp: {conversation.temperature}, max_tokens: {conversation.max_tokens}, tpm: {conversation.tokens_per_min}"
        )

    except Exception as e:
        show_error(f"Failed to transplant brain: {e}")
        logger.error(f"Error during transplant to {args}: {e}", exc_info=True)
        # TODO: Consider reverting conversation.provider/model on error?\n

    return True  # Command was handled


# --- New command handlers for session save/load ---


def handle_save_session_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /save-session command to save the current conversation history to a file.

    Args:
        args: The file path where to save the session.
        context: Context containing the conversation instance.

    Returns:
        True to indicate the command was handled successfully (continue loop).
    """
    if not args:
        # Corrected usage message
        show_error("No file path provided. Usage: /save-session ")
        return True

    conversation = context.get("conversation")
    if not conversation:
        show_error("No active conversation instance found.")
        return True

    # Expand user path (~/)
    file_path = os.path.expanduser(args.strip())

    success, message = save_conversation_pickle(conversation, file_path)

    if success:
        show_success(message)
    else:
        show_error(message)

    return True


def handle_load_session_command(args: str, context: Dict[str, Any]) -> bool:
    """
    Handle the /load-session command to load conversation history from a file.

    Args:
        args: The file path of the session file.
        context: Context containing the conversation instance and status function.

    Returns:
        True to indicate the command was handled successfully (continue loop).
    """
    conversation = context.get("conversation")
    status_func = context.get("status_func")  # Get status function from context

    if not conversation:
        show_error("No active conversation instance found.")
        return True

    if not status_func:
        show_error("Internal error: Status function not available for loading.")
        logger.error(
            "handle_load_session_command called without status_func in context"
        )
        return True

    if not args:
        show_error("No file path provided. Usage: /load-session ")
        return True

    # Expand user path (~/)
    file_path = os.path.expanduser(args.strip())

    success, message, loaded_messages = load_conversation_pickle(
        conversation, file_path
    )

    if success:
        show_success(message)
        # Display summary if messages were loaded
        if loaded_messages is not None and len(loaded_messages) > 0:
            # Get a summary of the loaded conversation
            with status_func("Generating summary..."):
                summary = get_session_summary(
                    conversation
                )  # Use the conversation object with loaded messages

            # Print the summary
            q_console.print("\n[bold]Conversation Summary:[/bold]")

            # Use the rich.markdown.Markdown class if available in the caller's context
            try:
                from rich.markdown import Markdown

                markdown_response = Markdown(summary)
                q_console.print(markdown_response)
            except (ImportError, NameError):
                # Fallback if Markdown is not available
                q_console.print(summary)

            q_console.print("")

    else:
        show_error(message)

    return True


# Register built-in commands
# Note: exit/quit/q handlers now return False to signal exit
register_command("exit", handle_exit_command, "Exit the application")
register_command("quit", handle_exit_command, "Exit the application")
# Register the new command to save the last response
register_command(
    "/save-last-response",
    handle_save_last_response_command,
    "Save the last model response to a file",
)
register_command(
    "/save-session",
    handle_save_session_command,
    "Save the current conversation session to a pickle file",
)
register_command(
    "/load-session",
    handle_load_session_command,
    "Load a conversation session from a pickle file",
)
# Register the new /help command for asking questions with README context
register_command(
    "/help",
    handle_help_question_command,
    "Display README.md or answer a question about Q (e.g., /help how do I save a session?)",
)
register_command(
    "/clear", handle_clear_command, "Clear the chat history and terminal screen"
)
register_command(
    "/recover",
    handle_recover_command,
    "Recover a previous session (last N turns) from the auto-save file",
)
register_command(
    "/transplant",
    handle_transplant_command,
    "Switch the LLM provider and model (e.g., /transplant anthropic/claude-3-7-sonnet-latest)",
)
register_command(
    "/t-budget",
    handle_t_budget_command,
    "Set the Vertex AI thinking budget in tokens (e.g., /t-budget 4096)",
)


# Register MCP commands if available
if MCP_AVAILABLE:
    register_command(
        "/mcp-connect",
        handle_mcp_connect_command,
        "Connect to an MCP server (e.g., /mcp-connect context7)",
    )
    register_command(
        "/mcp-disconnect",
        handle_mcp_disconnect_command,
        "Disconnect from an MCP server (e.g., /mcp-disconnect context7)",
    )
    register_command(
        "/mcp-tools",
        handle_mcp_list_tools_command,
        "List available tools from MCP servers (e.g., /mcp-tools context7)",
    )
    register_command(
        "/mcp-servers",
        handle_mcp_list_servers_command,
        "List all available MCP servers (default and user-defined)",
    )
    register_command(
        "/mcp-add",
        handle_mcp_add_server_command,
        'Add user-defined MCP server(s) from a JSON string (e.g., /mcp-add \'{"my-server": {"command": "npx", "args": ["-y", "@my/mcp-server@latest"]}}\')',
    )
    register_command(
        "/mcp-remove",
        handle_mcp_remove_server_command,
        "Remove a user-defined MCP server (e.g., /mcp-remove my-server)",
    )
    register_command(
        "/mcp-fix",
        handle_mcp_fix_command,
        "Fix a malformed MCP servers configuration file",
    )

# Remove the redundant is_command function registration if it exists
# (It was likely added for testing/debugging and is not a user command)
if "is_command" in command_registry:
    del command_registry["is_command"]
    logger.debug("Removed internal function 'is_command' from command registry")
