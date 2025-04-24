"""
Validation module for Q.

This module provides functions to validate the configuration and API keys
before starting the application.
"""

import os
import sys
from typing import List, Tuple

from q.core.config import config, HOME_CONFIG_PATH
from q.core.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def validate_configuration() -> Tuple[bool, List[str], bool]:
    """
    Validate that the necessary configuration and API keys are set up.
    
    Returns:
        Tuple containing:
            - Boolean indicating if validation passed
            - List of error messages if validation failed
            - Boolean indicating if this is a first-time setup
    """
    errors = []
    is_first_time_setup = False
    
    # Check if this is the first time running (config file doesn't exist or is empty)
    if not config.config_exists or os.path.getsize(HOME_CONFIG_PATH) == 0:
        logger.info("Configuration file not found or empty. Setting up first-time configuration.")
        is_first_time_setup = True
        success = config.copy_example_config()
        if not success:
            errors.append("Failed to copy example configuration file. Please create ~/.config/q/q.conf manually.")
            return False, errors, is_first_time_setup
        return False, ["Configuration file has been created. Please edit it to add your API keys."], is_first_time_setup
    
    # Get the provider from config or use default
    provider = getattr(config, "PROVIDER", "anthropic").lower()
    logger.debug(f"Validating configuration for provider: {provider}")
    
    # Check provider-specific API keys
    if provider == "anthropic":
        api_key = getattr(config, "ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
        if not api_key:
            errors.append("Anthropic API key is not set. Please set ANTHROPIC_API_KEY in your configuration.")
    
    elif provider == "openai":
        api_key = getattr(config, "OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
        if not api_key:
            errors.append("OpenAI API key is not set. Please set OPENAI_API_KEY in your configuration.")
    
    elif provider == "groq":
        api_key = getattr(config, "GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))
        if not api_key:
            errors.append("Groq API key is not set. Please set GROQ_API_KEY in your configuration.")
    
    elif provider == "vertexai":
        project_id = getattr(config, "VERTEXAI_PROJECT", os.environ.get("VERTEXAI_PROJECT", ""))
        credentials_file = getattr(
            config, 
            "VERTEXAI_API_KEY", 
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        )
        
        if not project_id:
            errors.append("Vertex AI project ID is not set. Please set VERTEXAI_PROJECT in your configuration.")
        
        if not credentials_file:
            errors.append("Vertex AI credentials are not set. Please set VERTEXAI_API_KEY or GOOGLE_APPLICATION_CREDENTIALS.")
        elif credentials_file != "ADC" and not os.path.exists(credentials_file):
            errors.append(f"Vertex AI credentials file not found at: {credentials_file}")
    
    else:
        errors.append(f"Unsupported provider: {provider}. Supported providers are: anthropic, openai, groq, vertexai")
    
    # Return validation result
    return len(errors) == 0, errors, is_first_time_setup