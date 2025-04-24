"""
Configuration module for Q.

This module is responsible for loading configuration variables using the envhanced library.
Configuration is loaded from ~/.config/q/q.conf and local .env files.
"""

import os
import inspect
import shutil
from pathlib import Path
from envhanced import Config

from q.core import constants

# Define configuration file paths
HOME_CONFIG_PATH = os.path.expanduser("~/.config/q/q.conf")
LOCAL_ENV_PATH = ".env"
EXAMPLE_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "examples", "config_example.env")

class QConfig(Config):
    """
    Extended Config class that specifically loads from Q configuration locations.
    
    Loads configuration in the following priority order:
    1. Environment variables (highest priority)
    2. Local .env file
    3. ~/.config/q/q.conf file
    4. Constants (lowest priority)
    """
    
    def __init__(self, **kwargs):
        """
        Initialize the QConfig with Q-specific configuration paths.
        
        Args:
            **kwargs: Additional configuration variables to set directly
        """
        # Create home config directory if it doesn't exist
        home_config_dir = os.path.dirname(HOME_CONFIG_PATH)
        os.makedirs(home_config_dir, exist_ok=True)
        
        # Check if config file exists
        self.config_exists = os.path.exists(HOME_CONFIG_PATH)
        
        # Create empty config file if it doesn't exist
        if not self.config_exists:
            Path(HOME_CONFIG_PATH).touch()
        
        # Initialize with Q-specific configuration paths
        super().__init__(
            defaults=HOME_CONFIG_PATH,  # Use home config as defaults
            environ=LOCAL_ENV_PATH,     # Use local .env as environment-specific config
            **kwargs                    # Add any additional variables
        )
        
        # Load constants with lowest priority (only if not already set)
        for name, value in inspect.getmembers(constants):
            # Only include uppercase constants (standard convention)
            if name.isupper() and not name.startswith('_'):
                if not hasattr(self, name) or getattr(self, name) is None:
                    setattr(self, name, value)
    
    def copy_example_config(self):
        """
        Copy the example configuration file to the user's config directory.
        
        Returns:
            bool: True if the file was copied successfully, False otherwise
        """
        try:
            if os.path.exists(EXAMPLE_CONFIG_PATH):
                shutil.copy2(EXAMPLE_CONFIG_PATH, HOME_CONFIG_PATH)
                return True
            return False
        except Exception:
            return False

# Create a singleton instance for use throughout the application
config = QConfig()

# Export the config instance as the primary module interface
__all__ = ['config']