"""
Logging module for Q.
Provides centralized logging configuration and custom log levels.
"""

import logging
import sys
from typing import Optional

# Define log level constants directly here to avoid circular imports
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_CRITICAL = "CRITICAL"
LOG_LEVEL_INSPECT = "INSPECT"
DEFAULT_LOG_LEVEL = LOG_LEVEL_CRITICAL

# Define custom log level INSPECT between ERROR (40) and WARNING (30)
# DEBUG is 10, INFO is 20, WARNING is 30, ERROR is 40, CRITICAL is 50
INSPECT = 35
logging.addLevelName(INSPECT, LOG_LEVEL_INSPECT)

# Create a custom logger
logger = logging.getLogger("q")


# Add a method for the INSPECT level
def inspect(self, message, *args, **kwargs):
    """Log at INSPECT level (between ERROR and DEBUG)."""
    if self.isEnabledFor(INSPECT):
        self.log(INSPECT, message, *args, **kwargs)


# Add the inspect method to the Logger class
logging.Logger.inspect = inspect  # pyright: ignore [reportAttributeAccessIssue]


def configure_logging(log_level: Optional[str] = None) -> None:
    """
    Configure the logging system.

    Args:
        log_level: Optional log level to set (e.g., "DEBUG", "INFO", "WARNING", "ERROR", "INSPECT").
                   If None, defaults to DEFAULT_LOG_LEVEL.
    """
    # Import config here to avoid circular imports
    from q.core.config import config

    # Get log level from config, argument, or use default
    level_name = log_level or getattr(config, "Q_LOG_LEVEL", DEFAULT_LOG_LEVEL)

    # Convert string level to numeric value
    if level_name == LOG_LEVEL_INSPECT:
        level = INSPECT
    else:
        level = getattr(logging, level_name, logging.INFO)

    # Configure root logger
    logger.setLevel(level)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Add formatter to handler
    handler.setFormatter(formatter)

    # Clear existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()

    # Add handler to logger
    logger.addHandler(handler)

    logger.debug(f"Logging configured with level: {logging.getLevelName(level)}")


def get_logger(name: str = "") -> logging.Logger:
    """
    Get a logger instance with the given name.

    Args:
        name: Name for the logger, will be prefixed with 'q.'

    Returns:
        A configured logger instance
    """
    if name:
        return logging.getLogger(f"q.{name}")
    return logger


# Configure logging when module is imported - with default level initially
configure_logging()

