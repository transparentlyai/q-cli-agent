"""
Session management for Q.

This module handles saving and loading conversation sessions,
allowing users to recover from crashes or accidental exits,
and also provides functionality for user-initiated session save/load.
"""

import json
import os
import pickle # Import pickle
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from q.core.config import config
from q.core.constants import DEFAULT_SESSION_TURNS
from q.core.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Session file location for automatic recovery
SESSION_DIR = os.path.expanduser("~/.config/q")
SESSION_FILE = os.path.join(SESSION_DIR, "qsession")


def ensure_session_dir():
    """Ensure the session directory exists."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    logger.debug(f"Ensured session directory exists: {SESSION_DIR}")


def get_max_turns():
    """
    Get the maximum number of turns to save from config or use default.

    Returns:
        int: Maximum number of turns to save
    """
    # Check if config has SESSION_TURNS attribute
    return getattr(config, "SESSION_TURNS", DEFAULT_SESSION_TURNS)


def clear_session():
    """
    Clear the session file to start fresh.

    Returns:
        True if successful or if no file existed, False on error
    """
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
            logger.debug("Cleared existing session file")
        return True
    except Exception as e:
        logger.error(f"Failed to clear session file: {e}")
        return False


def save_session(messages: List[Dict[str, str]]) -> bool:
    """
    Save the last N conversation turns to the session file (for recovery).

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys

    Returns:
        True if successful, False otherwise
    """
    try:
        ensure_session_dir()

        # Get the maximum number of turns to save
        max_turns = get_max_turns()
        logger.debug(f"Saving up to {max_turns} conversation turns for recovery")

        # Filter out system messages and keep only the last max_turns * 2 messages
        # (each turn consists of a user message and an assistant message)
        filtered_messages = [msg for msg in messages if msg["role"] != "system"]

        # Keep only the last max_turns * 2 messages (user + assistant pairs)
        if len(filtered_messages) > max_turns * 2:
            filtered_messages = filtered_messages[-(max_turns * 2) :]

        # Save to file
        with open(SESSION_FILE, "w") as f:
            json.dump(filtered_messages, f)

        logger.debug(f"Saved {len(filtered_messages)} messages to recovery session file")
        return True
    except Exception as e:
        logger.error(f"Failed to save recovery session: {e}")
        return False


def load_session() -> Optional[List[Dict[str, str]]]:
    """
    Load the saved conversation turns from the session file (for recovery).

    Returns:
        List of message dictionaries if successful, None otherwise
    """
    try:
        if not os.path.exists(SESSION_FILE):
            logger.debug("No recovery session file found")
            return None

        with open(SESSION_FILE, "r") as f:
            messages = json.load(f)

        logger.debug(f"Loaded {len(messages)} messages from recovery session file")
        return messages
    except Exception as e:
        logger.error(f"Failed to load recovery session: {e}")
        return None


def recover_session(conversation) -> Tuple[bool, int]:
    """
    Recover a saved session and add it to the given conversation.

    Args:
        conversation: The LLMConversation instance to add the messages to

    Returns:
        Tuple of (success_flag, number_of_messages_recovered)
    """
    try:
        # Load saved messages
        saved_messages = load_session()

        if not saved_messages or len(saved_messages) == 0:
            logger.debug("No saved session to recover")
            return False, 0

        # Get current messages (should have at least the system prompt)
        current_messages = conversation.get_conversation_history()

        # Extract system prompt if it exists
        system_prompt = None
        for msg in current_messages:
            if msg["role"] == "system":
                system_prompt = msg
                break

        # Clear the conversation but keep the system prompt
        conversation.clear_conversation(keep_system_prompt=True)

        # Add saved messages
        for msg in saved_messages:
            conversation.add_message(msg["role"], msg["content"])

        num_messages = len(saved_messages)
        logger.info(f"Recovered {num_messages} messages from previous session")
        return True, num_messages
    except Exception as e:
        logger.error(f"Failed to recover session: {e}")
        return False, 0


def get_session_summary(conversation) -> str:
    """
    Request a summary of the recovered conversation from the LLM.

    Args:
        conversation: The LLMConversation instance with the recovered messages

    Returns:
        The summary text from the LLM
    """
    try:
        # Create a prompt asking for a summary
        summary_prompt = (
            "Please provide a brief summary of what we were discussing. "
            "Focus on the main topics and any conclusions or pending questions. "
            "Keep it concise (3-5 sentences)."
        )

        # Send the request to the LLM
        logger.debug("Requesting conversation summary from LLM")
        # Use a temporary context or ensure send_message doesn't rely on external context
        # Assuming conversation.send_message is self-contained for this purpose
        summary = conversation.send_message(summary_prompt)

        return summary
    except Exception as e:
        logger.error(f"Failed to get conversation summary: {e}")
        return "Failed to generate a summary of the previous conversation."


def handle_recovery_ui(conversation, console, status_func) -> bool:
    """
    Shared function to handle session recovery with UI feedback.

    Args:
        conversation: The LLMConversation instance to recover into
        console: The console object for output
        status_func: Function to create a status context manager

    Returns:
        True if recovery was successful, False otherwise
    """
    try:
        # Attempt to recover the session
        success, num_messages = recover_session(conversation)

        if success:
            console.print(
                f"[bold green]Previous session recovered successfully ({num_messages} messages).[/bold green]"
            )

            # Get a summary of the recovered conversation
            # Use status context manager for the summary generation
            with status_func("Generating summary..."):
                 summary = get_session_summary(conversation)

            # Print the summary
            console.print("\n[bold]Conversation Summary:[/bold]")

            # Use the rich.markdown.Markdown class if available in the caller's context
            try:
                from rich.markdown import Markdown

                markdown_response = Markdown(summary)
                console.print(markdown_response)
            except (ImportError, NameError):
                # Fallback if Markdown is not available
                console.print(summary)

            console.print("")
            return True
        else:
            console.print("[yellow]No previous session found to recover.[/yellow]")
            return False
    except Exception as e:
        logger.error(f"Error during recovery UI handling: {e}")
        console.print(f"[bold red]Error during session recovery:[/bold red] {str(e)}")
        return False


# --- New functions for user-initiated session save/load ---

def save_conversation_pickle(conversation, file_path: str) -> Tuple[bool, str]:
    """
    Save the current conversation history to a file using pickle.

    Args:
        conversation: The LLMConversation instance.
        file_path: The path to the file where the session should be saved.

    Returns:
        Tuple of (success_flag, message)
    """
    if not conversation:
        return False, "No active conversation instance found."

    try:
        # Get the full conversation history, including the system prompt
        messages = conversation.get_conversation_history()

        # Ensure the directory exists
        file_dir = os.path.dirname(file_path)
        if file_dir: # Only create if a directory is specified
             os.makedirs(file_dir, exist_ok=True)

        with open(file_path, 'wb') as f:
            pickle.dump(messages, f)

        logger.info(f"Saved conversation history ({len(messages)} messages) to {file_path}")
        return True, f"Conversation saved successfully to [cyan]{file_path}[/cyan]."

    except Exception as e:
        logger.error(f"Failed to save conversation to {file_path}: {e}", exc_info=True)
        return False, f"Failed to save conversation: {e}"


def load_conversation_pickle(conversation, file_path: str) -> Tuple[bool, str, Optional[List[Dict[str, str]]]]:
    """
    Load conversation history from a pickle file and replace the current history.

    Args:
        conversation: The LLMConversation instance.
        file_path: The path to the pickle file.

    Returns:
        Tuple of (success_flag, message, loaded_messages or None)
    """
    if not conversation:
        return False, "No active conversation instance found.", None

    if not os.path.exists(file_path):
        return False, f"File not found: [cyan]{file_path}[/cyan]", None

    try:
        with open(file_path, 'rb') as f:
            loaded_messages = pickle.load(f)

        if not isinstance(loaded_messages, list):
             return False, f"Invalid data format in file: [cyan]{file_path}[/cyan]. Expected a list.", None

        # Find the current system prompt
        current_messages = conversation.get_conversation_history()
        system_prompt = next((msg for msg in current_messages if msg["role"] == "system"), None)

        # Clear the current conversation history
        conversation.clear_conversation(keep_system_prompt=False) # Clear everything first

        # Add the system prompt back if it existed
        if system_prompt:
             conversation.add_message(system_prompt["role"], system_prompt["content"])

        # Add loaded messages
        for msg in loaded_messages:
            # Ensure loaded messages have the correct structure before adding
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                 # Avoid adding a duplicate system prompt if it was already added
                 if not (msg["role"] == "system" and system_prompt and msg["content"] == system_prompt["content"]):
                    conversation.add_message(msg["role"], msg["content"])
            else:
                 logger.warning(f"Skipping invalid message format during load: {msg}")


        num_messages = len(conversation.get_conversation_history()) - (1 if system_prompt else 0) # Count non-system messages
        logger.info(f"Loaded conversation history ({num_messages} messages) from {file_path}")
        return True, f"Conversation loaded successfully from [cyan]{file_path}[/cyan].", loaded_messages

    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, IndexError) as e:
        logger.error(f"Failed to load conversation from {file_path} (pickle error): {e}", exc_info=True)
        return False, f"Failed to load conversation (invalid file format or content): {e}", None
    except Exception as e:
        logger.error(f"Failed to load conversation from {file_path}: {e}", exc_info=True)
        return False, f"Failed to load conversation: {e}", None
