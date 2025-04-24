"""
Utility functions for updating the Q configuration file.
"""

import os
import re
from pathlib import Path
from typing import Optional

from q.core.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def update_config_provider_model(provider: str, model: str) -> bool:
    """
    Update the provider and model in the Q configuration file.
    
    Args:
        provider: The provider name (e.g., 'anthropic', 'vertexai')
        model: The model name (e.g., 'claude-3-7-sonnet-latest')
        
    Returns:
        bool: True if the update was successful, False otherwise
    """
    config_path = os.path.expanduser("~/.config/q/q.conf")
    
    # Check if config file exists
    if not os.path.exists(config_path):
        logger.error(f"Config file not found at {config_path}")
        return False
    
    try:
        # Read the current config file
        with open(config_path, 'r') as f:
            config_content = f.read()
        
        # Update the PROVIDER setting
        provider_pattern = re.compile(r'^PROVIDER=.*$', re.MULTILINE)
        if re.search(provider_pattern, config_content):
            # Replace existing PROVIDER line
            config_content = re.sub(provider_pattern, f"PROVIDER={provider}", config_content)
        else:
            # Add PROVIDER line if it doesn't exist
            config_content += f"\nPROVIDER={provider}\n"
        
        # Update the model setting for the specific provider
        model_setting = f"{provider.upper()}_MODEL"
        model_pattern = re.compile(f"^{model_setting}=.*$", re.MULTILINE)
        
        if re.search(model_pattern, config_content):
            # Replace existing model line
            config_content = re.sub(model_pattern, f"{model_setting}={model}", config_content)
        else:
            # Add model line if it doesn't exist
            config_content += f"\n{model_setting}={model}\n"
        
        # Write the updated config back to the file
        with open(config_path, 'w') as f:
            f.write(config_content)
        
        logger.info(f"Updated config file with provider={provider}, model={model}")
        return True
    
    except Exception as e:
        logger.error(f"Error updating config file: {e}", exc_info=True)
        return False