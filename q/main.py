import argparse
import importlib.resources
import os
import sys

from rich.markdown import Markdown

from q import __version__
from q.cli.qconsole import q_console
from q.core.config import HOME_CONFIG_PATH, config
from q.core.constants import OPERATION_MARKER
from q.core.logging import get_logger
from q.core.session import clear_session, handle_recovery_ui, save_session
from q.core.validation import validate_configuration

# Initialize logger
logger = get_logger(__name__)

CODE_SYNTAX_THEME = getattr(config, "CODE_SYNTAX_THEME", "vim")

THINKING_HINT = dict(
    status="[cyan]Thinking... [Ctrl+C to cancel][/cyan]",
    spinner="dots",
    speed=2,
)
PROCESSING_HINT = dict(
    status="[cyan]Processing... [Ctrl+C to cancel][/cyan]",
    spinner="point",
    speed=2,
)

# Determine system prompt path using importlib.resources
try:
    prompt_resource = importlib.resources.files("q.prompts").joinpath(
        "system-prompt.md"
    )
    SYSTEM_PROMPT_PATH = str(prompt_resource)
    logger.info(f"Located system prompt resource at: {SYSTEM_PROMPT_PATH}")
except Exception as e:
    logger.error(f"Error locating system prompt resource: {e}", exc_info=True)
    SYSTEM_PROMPT_PATH = "q/prompts/system-prompt.md"
    logger.warning(f"Using fallback system prompt path: {SYSTEM_PROMPT_PATH}")

# Lazy imports for modules not needed immediately
_context_loader = None
_prompt_loader = None
_llm_creator = None
_command_handler = None
_user_input_getter = None
_operation_router = None
_helpers = None
_mcp_checker = None


def _get_context_loader():
    """Lazy import for context module."""
    global _context_loader
    if _context_loader is None:
        logger.debug("Lazy loading context module")
        from q.core.context import load_context

        _context_loader = load_context
    return _context_loader


def _get_prompt_loader():
    """Lazy import for prompt module."""
    global _prompt_loader
    if _prompt_loader is None:
        logger.debug("Lazy loading prompt module")
        from q.core.prompt import load_prompt

        _prompt_loader = load_prompt
    return _prompt_loader


def _get_llm_creator():
    """Lazy import for LLM module."""
    global _llm_creator
    if _llm_creator is None:
        logger.debug("Lazy loading LLM module")
        from q.core.llm import create_conversation

        _llm_creator = create_conversation
    return _llm_creator


def _get_command_handlers():
    """Lazy import for command handlers."""
    global _command_handler
    if _command_handler is None:
        logger.debug("Lazy loading command handlers")
        from q.cli.commands import handle_command, is_command

        _command_handler = (handle_command, is_command)
    return _command_handler


def _get_user_input_getter():
    """Lazy import for user input getter."""
    global _user_input_getter
    if _user_input_getter is None:
        logger.debug("Lazy loading user input getter")
        from q.cli.qprompt import get_user_input

        _user_input_getter = get_user_input
    return _user_input_getter


def _get_operation_router():
    """Lazy import for operation router."""
    global _operation_router
    if _operation_router is None:
        logger.debug("Lazy loading operation router")
        from q.operators.router import execute_operation, extract_operation

        _operation_router = (execute_operation, extract_operation)
    return _operation_router


def _get_helpers():
    """Lazy import for helpers."""
    global _helpers
    if _helpers is None:
        logger.debug("Lazy loading helpers")
        from q.utils.helpers import get_current_model

        _helpers = get_current_model
    return _helpers


def _get_mcp_checker():
    """Lazy import for MCP configuration checker."""
    global _mcp_checker
    if _mcp_checker is None:
        logger.debug("Lazy loading MCP configuration checker")
        try:
            from q.utils.mcp_servers import (
                USER_MCP_SERVERS_PATH,
                check_mcp_servers_file,
            )

            _mcp_checker = (check_mcp_servers_file, USER_MCP_SERVERS_PATH)
        except ImportError:
            logger.debug("MCP functionality not available")
            _mcp_checker = (None, None)
    return _mcp_checker


def main_loop(
    initial_question=None, exit_after_answer=False, allow_all=False, recover=False
):
    """Runs the main conversation loop.

    Args:
        initial_question (str, optional): Initial question to ask the model.
        exit_after_answer (bool, optional): Whether to exit after answering the initial question.
        allow_all (bool, optional): Whether to allow all commands except dangerous or prohibited ones.
        recover (bool, optional): Whether to recover the previous session.
    """
    logger.info("Starting Q conversation loop...")

    # Validate configuration and API keys before proceeding
    is_valid, errors, is_first_time_setup = validate_configuration()

    if is_first_time_setup:
        logger.info("First-time setup detected")
        q_console.print("[bold green]Welcome to Q![/bold green]")
        q_console.print(
            f"An example configuration file has been created at: {HOME_CONFIG_PATH}"
        )
        q_console.print("Please edit this file to add your API keys and restart Q.")
        q_console.print("\nExample configuration:")
        q_console.print(
            "1. Choose your preferred provider (anthropic, openai, groq, vertexai)"
        )
        q_console.print("2. Add your API key for the selected provider")
        q_console.print("3. Save the file and restart Q")
        return

    if not is_valid:
        logger.error("Configuration validation failed")
        q_console.print(
            "[bold red]Error:[/bold red] Q configuration is incomplete or invalid."
        )
        for error in errors:
            q_console.print(f"  - {error}")
        q_console.print(
            "\nPlease set up your configuration in ~/.config/q/q.conf or environment variables."
        )
        return

    # Check MCP servers configuration
    check_mcp_servers_file, USER_MCP_SERVERS_PATH = _get_mcp_checker()
    if check_mcp_servers_file:
        is_valid, error_msg = check_mcp_servers_file()
        if not is_valid:
            logger.warning(f"MCP servers configuration issue: {error_msg}")
            q_console.print(
                f"[bold yellow]Warning:[/bold yellow] MCP servers configuration issue: {error_msg}"
            )
            q_console.print(
                f"You can fix this with the [cyan]/mcp-fix[/cyan] command or by editing: {USER_MCP_SERVERS_PATH}"
            )

    if exit_after_answer and initial_question:
        logger.info("Will exit after answering the initial question")
    if allow_all:
        logger.info(
            "Auto-approval enabled for all commands except dangerous or prohibited ones"
        )
        # Set global flag for command approvals
        config.ALLOW_ALL_COMMANDS = True  # type: ignore

    # Store the latest model response for the old /save command (now unused)
    # and the last user prompt for the new /save-last-prompt command
    latest_response = ""
    last_user_prompt = ""  # Variable to store the last user prompt

    try:
        # 1. Load context variables - lazy load the context module
        logger.debug("Loading context variables...")
        load_context = _get_context_loader()
        context_vars = load_context()
        context_vars_filtered = {k: v for k, v in context_vars.items() if v is not None}
        logger.debug(f"Context loaded: {list(context_vars_filtered.keys())}")

        # if config has OPERATION_MARKER Attrubute, get it. if not use the constant OPERATION_MARKER
        config_operation_marker = getattr(config, "OPERATION_MARKER", None)
        if config_operation_marker:
            logger.debug(
                f"Using operation marker from config: {config_operation_marker}"
            )
        else:
            config_operation_marker = OPERATION_MARKER
            logger.debug(
                "Using default operation marker from constant: OPERATION_MARKER"
            )

        # 2. Load system prompt - lazy load the prompt module
        logger.debug(f"Loading system prompt from: {SYSTEM_PROMPT_PATH}")
        if not os.path.exists(SYSTEM_PROMPT_PATH):
            logger.error(f"System prompt file not found at: {SYSTEM_PROMPT_PATH}")
            q_console.print(
                f"[bold red]Error:[/bold red] System prompt file not found at {SYSTEM_PROMPT_PATH}. Exiting."
            )
            return

        load_prompt = _get_prompt_loader()
        context_vars_filtered["marker"] = config_operation_marker
        system_prompt_content = load_prompt(SYSTEM_PROMPT_PATH, **context_vars_filtered)
        logger.debug("System prompt loaded successfully.")

        # 3. Create conversation instance - lazy load the LLM module
        logger.debug("Initializing LLM conversation...")
        create_conversation = _get_llm_creator()
        conversation = create_conversation(system_prompt=system_prompt_content)

        # Helper function to print formatted response (defined once within main_loop scope)
        def _print_formatted_response(text_to_print):
            """Formats and prints the response using Rich Markdown."""
            if text_to_print:  # Avoid printing empty responses
                markdown_response = Markdown(
                    text_to_print, code_theme=CODE_SYNTAX_THEME
                )
                q_console.print(markdown_response)
                q_console.print("")
                # Update the latest response (kept for compatibility, though /save is removed)
                nonlocal latest_response
                latest_response = text_to_print

        # Handle session recovery or clearing
        if recover:
            logger.info("Attempting to recover previous session...")
            handle_recovery_ui(conversation, q_console, q_console.status)
        else:
            # If not recovering, clear any existing session file to start fresh
            logger.info("Starting fresh session, clearing any previous session data...")
            clear_session()

        # Lazy load helpers
        get_current_model = _get_helpers()
        logger.info("LLM Conversation initialized. Ready for input.")
        q_console.print(
            f"[#666666]Q ver:{__version__} - brain:{get_current_model(conversation)}[/#666666]"  # Pass conversation
        )

        # Process initial question if provided
        if initial_question:
            logger.debug(f"Processing initial question: '{initial_question[:50]}...'")
            q_console.print("")  # Add space before thinking hint

            # Store the initial question as the last prompt
            last_user_prompt = initial_question

            # Get initial response from LLM
            with q_console.status(**THINKING_HINT):  # pyright: ignore
                model_response = conversation.send_message(initial_question)

            # Lazy load operation router
            if _operation_router is None:
                execute_operation, extract_operation = _get_operation_router()
            else:
                execute_operation, extract_operation = _operation_router

            # Process response from the Model
            extraction_result = extract_operation(model_response)
            cleaned_text = extraction_result["text"]
            operation_details = extraction_result["operation"]
            parsing_error = extraction_result["error"]

            # Print the cleaned text to the console first
            _print_formatted_response(cleaned_text)

            # Handle any parsing errors
            if parsing_error:
                logger.error(
                    f"Parsing error during operation extraction: {parsing_error}"
                )
                q_console.print(
                    f"[bold red]Error parsing operation:[/bold red] {parsing_error}"
                )

            # If an operation was found, execute it
            if operation_details:
                logger.info(f"Found operation of type: {operation_details.get('type')}")
                execution_result = execute_operation(operation_details)
                operation_results = execution_result["results"]
                execution_error = execution_result["error"]

                if execution_error:
                    logger.error(f"Error during operation execution: {execution_error}")

                # Handle command execution results, potentially looping
                while operation_results:
                    logger.info(
                        f"Operation executed. Results preview: {str(operation_results)[:100]}"
                    )
                    # Send execution results back to LLM for next step/analysis
                    with q_console.status(**PROCESSING_HINT):  # pyright: ignore
                        # Check if operation_results contains an attachment
                        if operation_results.get("attachment"):
                            logger.debug("Attachment found in operation results")
                            # Use send_message_with_file for operations with attachments
                            model_response = conversation.send_message_with_file(
                                operation_results.get("reply", ""),
                                operation_results["attachment"],
                            )
                        else:
                            # Use standard send_message for text-only results
                            model_response = conversation.send_message(
                                str(operation_results)
                            )

                    # Process the LLM's response after getting execution results
                    extraction_result = extract_operation(model_response)
                    cleaned_text = extraction_result["text"]
                    operation_details = extraction_result["operation"]
                    parsing_error = extraction_result["error"]

                    # Print the cleaned text response
                    _print_formatted_response(cleaned_text)

                    # Handle any parsing errors
                    if parsing_error:
                        logger.error(
                            f"Parsing error during operation extraction: {parsing_error}"
                        )
                        q_console.print(
                            f"[bold red]Error parsing operation:[/bold red] {parsing_error}"
                        )

                    # If no more operations, we're done
                    if not operation_details:
                        logger.debug("Command execution cycle finished.")
                        break

                    # Execute the next operation - WITHOUT status display
                    execution_result = execute_operation(operation_details)

                    operation_results = execution_result["results"]
                    execution_error = execution_result["error"]

                    if execution_error:
                        logger.error(
                            f"Error during operation execution: {execution_error}"
                        )

            # Save the session after processing the initial question
            save_session(conversation.get_conversation_history())

            # Exit after answering if flag is set
            if exit_after_answer:
                logger.info("Exiting after answering initial question as requested")
                return

        # 4. Conversation loop
        # Lazy load command handlers and user input getter
        handle_command, is_command = _get_command_handlers()
        get_user_input = _get_user_input_getter()

        while True:
            try:
                user_input = get_user_input()

                # Handle empty input (just pressing Enter)
                if not user_input.strip():
                    continue

                # Store the current user input as the last prompt
                last_user_prompt = user_input

                # Check if input is a command and handle it
                # Include the conversation instance and status_func in the command context
                command_context = {
                    "latest_response": latest_response,  # Kept for compatibility, though /save is removed
                    "conversation": conversation,
                    "status_func": q_console.status,  # Add status_func to context
                    "last_user_prompt": last_user_prompt,  # Add the last user prompt to context
                }
                if is_command(user_input):
                    # handle_command returns False for exit commands, True otherwise
                    should_continue_loop = handle_command(user_input, command_context)
                    if not should_continue_loop:
                        # Exit command was handled, break the loop
                        save_session(conversation.get_conversation_history())
                        logger.info("Exiting conversation loop on command.")
                        break
                    else:
                        # Command was handled successfully, continue to next input
                        continue

                # If it wasn't a command or was a non-exit command that finished, proceed with LLM interaction
                logger.debug(f"Sending message to LLM: '{user_input[:50]}...'")
                q_console.print("")  # Add space before thinking hint

                # Get initial response from LLM
                with q_console.status(**THINKING_HINT):  # pyright: ignore
                    model_response = conversation.send_message(user_input)

                # Make sure operation router is loaded
                if _operation_router is None:
                    execute_operation, extract_operation = _get_operation_router()
                else:
                    execute_operation, extract_operation = _operation_router

                ## Process response from the Model
                extraction_result = extract_operation(model_response)  # pyright: ignore
                cleaned_text = extraction_result["text"]
                operation_details = extraction_result["operation"]
                parsing_error = extraction_result["error"]

                # Extra check for missed operations (raw tag heuristic)
                # This is now handled within router.py with the aggressive fallback parser

                # Print the cleaned text to the console first
                _print_formatted_response(cleaned_text)

                # Handle any parsing errors
                if parsing_error:
                    logger.error(
                        f"Parsing error during operation extraction: {parsing_error}"
                    )
                    q_console.print(
                        f"[bold red]Error parsing operation:[/bold red] {parsing_error}"
                    )

                # If an operation was found, execute it
                if operation_details:
                    logger.info(
                        f"Found operation of type: {operation_details.get('type')}"
                    )
                    execution_result = execute_operation(operation_details)  # pyright: ignore
                    operation_results = execution_result["results"]
                    execution_error = execution_result["error"]

                    if execution_error:
                        logger.error(
                            f"Error during operation execution: {execution_error}"
                        )

                    # Handle command execution results, potentially looping
                    while operation_results:
                        logger.info(
                            f"Operation executed. Results preview: {str(operation_results)[:100]}"
                        )
                        # Send execution results back to LLM for next step/analysis
                        with q_console.status(**PROCESSING_HINT):  # pyright: ignore
                            # Check if operation_results contains an attachment
                            if operation_results.get("attachment"):
                                logger.debug("Attachment found in operation results")
                                # Use send_message_with_file for operations with attachments
                                model_response = conversation.send_message_with_file(
                                    operation_results.get("reply", ""),
                                    operation_results["attachment"],
                                )
                            else:
                                # Use standard send_message for text-only results
                                model_response = conversation.send_message(
                                    str(operation_results)
                                )

                        # Process the LLM's response after getting execution results
                        extraction_result = extract_operation(model_response)  # pyright: ignore
                        cleaned_text = extraction_result["text"]
                        operation_details = extraction_result["operation"]
                        parsing_error = extraction_result["error"]

                        # Extra check for missed operations (raw tag heuristic)
                        # This is now handled within router.py with the aggressive fallback parser

                        # Print the cleaned text response
                        _print_formatted_response(cleaned_text)

                        # Handle any parsing errors
                        if parsing_error:
                            logger.error(
                                f"Parsing error during operation extraction: {parsing_error}"
                            )
                            q_console.print(
                                f"[bold red]Error parsing operation:[/bold red] {parsing_error}"
                            )

                        # If no more operations, we're done
                        if not operation_details:
                            logger.debug("Command execution cycle finished.")
                            break

                        # Execute the next operation - WITHOUT status display
                        execution_result = execute_operation(operation_details)  # pyright: ignore

                        operation_results = execution_result["results"]
                        execution_error = execution_result["error"]

                        if execution_error:
                            logger.error(
                                f"Error during operation execution: {execution_error}"
                            )

                # Save the session after each turn
                save_session(conversation.get_conversation_history())

            except (
                EOFError
            ):  # This handles Ctrl+D if get_user_input doesn't catch it (safety net)
                logger.info("EOF received, exiting.")
                # Save session before exiting
                save_session(conversation.get_conversation_history())
                break
            except KeyboardInterrupt:
                # For KeyboardInterrupt during processing (not during input)
                # The input-related Ctrl+C is already handled in qprompt.py
                logger.info("Keyboard interrupt received during processing.")
                q_console.print("\n[#666666]Operation cancelled.[/]")
                # Continue the loop instead of breaking
                continue
            except Exception as e:  # General exception handling
                logger.error(
                    f"An error occurred in the conversation loop: {e}", exc_info=True
                )
                q_console.print(f"\n[bold red]An error occurred:[/bold red] {e}")
                # Save session before exiting on error
                save_session(conversation.get_conversation_history())
                # Exit loop on unexpected error to prevent potential infinite loops
                break

    except FileNotFoundError as e:
        logger.error(f"Failed to initialize: {e}", exc_info=True)
        q_console.print(
            f"[bold red]Error:[/bold red] {e}. Please ensure necessary files exist."
        )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during initialization: {e}", exc_info=True
        )
        q_console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Q - Command-line AI assistant")
    parser.add_argument(
        "question", nargs="?", help="Initial question to ask (optional)"
    )
    parser.add_argument(
        "--exit-after",
        "-e",
        action="store_true",
        help="Exit after answering the initial question",
    )
    parser.add_argument(
        "--allow-all",
        "-a",
        action="store_true",
        help="Allow all commands without confirmation",
    )
    parser.add_argument(
        "--recover", "-r", action="store_true", help="Recover previous session"
    )
    parser.add_argument(
        "--version", "-v", action="store_true", help="Show version information and exit"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.version:
        print(f"Q version {__version__}")
        sys.exit(0)

    main_loop(
        initial_question=args.question,
        exit_after_answer=args.exit_after,
        allow_all=args.allow_all,
        recover=args.recover,
    )


if __name__ == "__main__":
    main()

