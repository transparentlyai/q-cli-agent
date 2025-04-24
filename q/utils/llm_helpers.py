"""
Helper functions for LLM operations in Q.

This module contains utility functions for working with LLMs,
including token counting, error handling, and provider-specific helpers.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from litellm.utils import token_counter

from q.core.constants import (
    ANTHROPIC_DEFAULT_MODEL,
    ANTHROPIC_DEFAULT_TOKENS_PER_MIN,
    GROQ_DEFAULT_MODEL,
    GROQ_DEFAULT_TOKENS_PER_MIN,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_TOKENS_PER_MIN,
    VERTEXAI_DEFAULT_LOCATION,
    VERTEXAI_DEFAULT_MODEL,
    VERTEXAI_DEFAULT_TOKENS_PER_MIN,
    DEFAULT_TOKENS_PER_MIN,
)
from q.core.logging import get_logger

# Initialize logger for this module
logger = get_logger("llm_helpers")


def is_overloaded_error(exception) -> bool:
    """
    Check if the exception is an overloaded error.

    Args:
        exception: The exception to check

    Returns:
        bool: True if it's an overloaded error, False otherwise
    """
    error_str = str(exception)
    return (
        '"type":"overloaded_error"' in error_str
        or '"message":"Overloaded"' in error_str
        or "quota exceeded" in error_str.lower()
        or "resource exhausted" in error_str.lower()
    )


def count_tokens_in_messages(messages: List[Dict[str, str]], model: str, provider: str) -> Any:
    """
    Count the number of tokens in a list of messages.

    Args:
        messages: List of message dictionaries with 'role' and 'content' keys
        model: The model name
        provider: The provider name (vertexai, anthropic, openai, groq)

    Returns:
        Total token count for the messages
    """
    try:
        # Format model name for token counting
        model_name = format_model_name(model, provider)
        
        # Use litellm's token_counter to count tokens
        token_count = token_counter(model=model_name, messages=messages)
        return token_count
    except Exception as e:
        logger.warning(f"Error counting tokens: {str(e)}. Using estimate instead.")
        # Fallback to a simple estimation if token_counter fails
        return sum(len(msg.get("content", "").split()) * 1.3 for msg in messages)


def format_model_name(model: str, provider: str) -> str:
    """
    Format the model name with provider prefix if needed.

    Args:
        model: The model name
        provider: The provider name

    Returns:
        Properly formatted model name for the provider
    """
    if provider == "vertexai":
        if not model.startswith("vertex_ai/"):
            return f"vertex_ai/{model}"
    elif provider == "anthropic":
        if model.startswith("anthropic/"):
            return model[len("anthropic/"):]
    elif provider == "groq":
        if not model.startswith("groq/"):
            return f"groq/{model}"
    elif provider == "openai":
        if not model.startswith("openai/"):
            return f"openai/{model}"
    
    return model


def get_default_tokens_per_min(provider: str) -> int:
    """
    Get the default tokens per minute limit for the specified provider.

    Args:
        provider: The provider name

    Returns:
        Default tokens per minute limit
    """
    if provider == "anthropic":
        return ANTHROPIC_DEFAULT_TOKENS_PER_MIN
    elif provider == "vertexai":
        return VERTEXAI_DEFAULT_TOKENS_PER_MIN
    elif provider == "groq":
        return GROQ_DEFAULT_TOKENS_PER_MIN
    elif provider == "openai":
        return OPENAI_DEFAULT_TOKENS_PER_MIN
    else:
        return DEFAULT_TOKENS_PER_MIN


def setup_provider_environment(provider: str, api_key: Optional[str] = None) -> None:
    """
    Set up environment variables for the specified provider.

    Args:
        provider: The provider name
        api_key: Optional API key to set
    """
    if provider == "anthropic" and api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key
    elif provider == "groq" and api_key:
        os.environ["GROQ_API_KEY"] = api_key
    elif provider == "openai" and api_key:
        os.environ["OPENAI_API_KEY"] = api_key


def setup_vertexai_environment(
    project_id: Optional[str] = None,
    location: Optional[str] = None
) -> None:
    """
    Set up environment variables for Vertex AI.

    Args:
        project_id: The Google Cloud project ID
        location: The Google Cloud location
    """
    if project_id:
        os.environ["VERTEXAI_PROJECT"] = project_id
    if location:
        os.environ["VERTEXAI_LOCATION"] = location


def load_vertexai_credentials(credentials_file: str) -> Optional[str]:
    """
    Load Vertex AI credentials from a file.

    Args:
        credentials_file: Path to the credentials file

    Returns:
        JSON string of credentials or None if error
    """
    if credentials_file and credentials_file != "ADC" and os.path.exists(credentials_file):
        try:
            with open(credentials_file, "r") as f:
                return json.dumps(json.load(f))
        except Exception as e:
            logger.error(f"Error loading Vertex AI credentials file: {str(e)}")
    
    return None