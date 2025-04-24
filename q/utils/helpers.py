import os  # Added for expanduser
from typing import Any, Optional  # Added Optional and Any for type hinting

from q.core.config import config
from q.core.constants import (
    ANTHROPIC_DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    GROQ_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    VERTEXAI_DEFAULT_MODEL,
)
from q.core.logging import get_logger

# Initialize logger for this module
logger = get_logger("helpers")  # Changed logger name for clarity


def get_current_model(conversation: Optional[Any] = None) -> str:
    """
    Retrieves the currently configured or active LLM model name.

    If a conversation object is provided, it reads the provider and model
    directly from it. Otherwise, it reads the provider from the global config
    and returns the corresponding model name specified in the config,
    falling back to defaults if necessary.

    Args:
        conversation: Optional LLMConversation object to get current model from.

    Returns:
        The name of the currently active or configured LLM model.
    """
    provider = ""
    model_name = ""

    # Try getting from conversation object first
    if (
        conversation
        and hasattr(conversation, "provider")
        and hasattr(conversation, "model")
    ):
        provider = conversation.provider.lower()
        model_name = conversation.model
        logger.debug(
            f"Determined current model from conversation object: {provider}/{model_name}"
        )
        # Ensure consistency with how model names are stored/used (e.g., remove prefix)
        if provider == "anthropic" and model_name.startswith("anthropic/"):
            model_name = model_name[len("anthropic/") :]
        return model_name
    else:
        # Fallback to global config if no conversation object or attributes missing
        logger.debug("Falling back to global config to determine current model.")
        provider = getattr(config, "PROVIDER", DEFAULT_PROVIDER).lower()

        if provider == "vertexai":
            model_name = getattr(config, "VERTEXAI_MODEL", VERTEXAI_DEFAULT_MODEL)
        elif provider == "anthropic":
            model_name = getattr(config, "ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)
            # Remove 'anthropic/' prefix if present, consistent with __init__
            if model_name.startswith("anthropic/"):
                model_name = model_name[len("anthropic/") :]
        elif provider == "groq":
            model_name = getattr(config, "GROQ_MODEL", GROQ_DEFAULT_MODEL)
        else:  # Default to OpenAI
            provider = "openai"  # Explicitly set provider for logging if defaulting
            model_name = getattr(config, "OPENAI_MODEL", OPENAI_DEFAULT_MODEL)

        logger.debug(
            f"Determined current model from config based on provider '{provider}': {model_name}"
        )
        return model_name


def save_response_to_file(response_text: str, file_path: str) -> tuple[bool, str]:
    """
    Saves the provided response text to a file.

    Args:
        response_text: The text to save to the file
        file_path: The path where the file should be saved

    Returns:
        A tuple containing (success: bool, message: str)
    """
    logger.debug(f"Attempting to save response to file: {file_path}")

    try:
        # Expand user directory if path starts with ~
        expanded_file_path = os.path.expanduser(file_path)

        # Create directory if it doesn't exist
        directory = os.path.dirname(expanded_file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
            logger.debug(f"Created directory: {directory}")

        # Write the response to the file
        with open(expanded_file_path, "w", encoding="utf-8") as f:
            f.write(response_text)

        logger.info(f"Successfully saved response to file: {expanded_file_path}")
        return True, f"Response saved to {expanded_file_path}"

    except Exception as e:
        error_msg = f"Error saving response to file '{file_path}': {str(e)}"
        logger.error(error_msg, exc_info=True)  # Add exc_info for more details
        return False, error_msg

