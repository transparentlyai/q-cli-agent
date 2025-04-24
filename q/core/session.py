"""
Session management for Q.

This module handles saving and loading conversation sessions,
allowing users to recover from crashes or accidental exits.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from q.core.config import config
from q.core.constants import DEFAULT_SESSION_TURNS
from q.core.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Session file location
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
    Save the last N conversation turns to the session file.

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys

    Returns:
        True if successful, False otherwise
    """
    try:
        ensure_session_dir()

        # Get the maximum number of turns to save
        max_turns = get_max_turns()
        logger.debug(f"Saving up to {max_turns} conversation turns")

        # Filter out system messages and keep only the last max_turns * 2 messages
        # (each turn consists of a user message and an assistant message)
        filtered_messages = [msg for msg in messages if msg["role"] != "system"]

        # Keep only the last max_turns * 2 messages (user + assistant pairs)
        if len(filtered_messages) > max_turns * 2:
            filtered_messages = filtered_messages[-(max_turns * 2) :]

        # Save to file
        with open(SESSION_FILE, "w") as f:
            json.dump(filtered_messages, f)

        logger.debug(f"Saved {len(filtered_messages)} messages to session file")
        return True
    except Exception as e:
        logger.error(f"Failed to save session: {e}")
        return False


def load_session() -> Optional[List[Dict[str, str]]]:
    """
    Load the saved conversation turns from the session file.

    Returns:
        List of message dictionaries if successful, None otherwise
    """
    try:
        if not os.path.exists(SESSION_FILE):
            logger.debug("No session file found")
            return None

        with open(SESSION_FILE, "r") as f:
            messages = json.load(f)

        logger.debug(f"Loaded {len(messages)} messages from session file")
        return messages
    except Exception as e:
        logger.error(f"Failed to load session: {e}")
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

