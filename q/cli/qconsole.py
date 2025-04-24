# q/cli/qconsole.py
# This module handles rich text output using the rich library.

from typing import Optional, Tuple, Union

from rich.console import Console
from rich.padding import Padding
from rich.status import Status

from q.core.constants import CONSOLE_LEFT_PADDING, CONSOLE_RIGHT_PADDING

# Create a standard Rich Console
_original_console = Console(force_terminal=True)

# Store the original print method
_original_print = _original_console.print


# Create a padded print function
def _padded_print(
    *args,
    padding: Optional[Union[int, Tuple[int, int, int, int]]] = None,
    left_padding: Optional[int] = None,
    right_padding: Optional[int] = None,
    **kwargs,
):
    """
    Print with padding.

    Args:
        *args: Arguments to pass to the original print method
        padding: Optional custom padding (overrides all other padding settings)
                Can be an int (all sides) or a tuple (top, right, bottom, left)
        left_padding: Optional left padding override
        right_padding: Optional right padding override
        **kwargs: Keyword arguments to pass to the original print method
    """
    if args and args[0] is not None:
        # Determine padding values
        if padding is not None:
            # Use custom padding if provided
            padding_value = padding
        else:
            # Use individual padding values or defaults
            left = left_padding if left_padding is not None else CONSOLE_LEFT_PADDING
            right = (
                right_padding if right_padding is not None else CONSOLE_RIGHT_PADDING
            )
            padding_value = (0, right, 0, left)

        # Apply padding to the first argument
        args = (Padding(args[0], padding_value),) + args[1:]

    # Call the original print method
    return _original_print(*args, **kwargs)


# Create a console object with the padded print method
class QConsole:
    """A proxy object that forwards most attributes to the original console."""

    def __init__(self, console):
        self._console = console

    def print(
        self,
        *args,
        padding: Optional[Union[int, Tuple[int, int, int, int]]] = None,
        left_padding: Optional[int] = None,
        right_padding: Optional[int] = None,
        **kwargs,
    ):
        """
        Print with padding.

        Args:
            *args: Arguments to pass to the original print method
            padding: Optional custom padding (overrides all other padding settings)
                    Can be an int (all sides) or a tuple (top, right, bottom, left)
            left_padding: Optional left padding override
            right_padding: Optional right padding override
            **kwargs: Keyword arguments to pass to the original print method
        """
        return _padded_print(
            *args,
            padding=padding,
            left_padding=left_padding,
            right_padding=right_padding,
            **kwargs,
        )

    def status(self, *args, left_padding: Optional[int] = None, **kwargs):
        """
        Forward status calls to the original console.

        Args:
            *args: Arguments to pass to the original status method
            left_padding: Optional left padding override
            **kwargs: Keyword arguments to pass to the original status method
        """
        # Add left padding to the first argument if it's a string
        if args and isinstance(args[0], str):
            # Use custom left padding if provided, otherwise use default
            padding = left_padding if left_padding is not None else CONSOLE_LEFT_PADDING
            args = (" " * padding + args[0],) + args[1:]
        return self._console.status(*args, **kwargs)

    def __getattr__(self, name):
        """Forward all other attribute access to the original console."""
        return getattr(self._console, name)


# Create our console instance
q_console = QConsole(_original_console)


def show_spinner(
    message: str,
    stype="dots",
    speed=1,
    style="status.spinner",
) -> Status:
    """
    Display a spinner with the given message.

    Args:
        message: The message to display alongside the spinner
        spinner_type: the type of spinner to be used
        spinner_speed: the speed of the speener

    Returns:
        A Status object that can be updated or stopped
    """
    return q_console.status(
        message,
        spinner=stype,
        speed=speed,
        spinner_style=style,
    )


def show_success(message: str) -> None:
    """
    Display a success message.

    Args:
        message: The success message to display
    """
    q_console.print(f"[bold green]{message}[/bold green]\n")


def show_error(message: str) -> None:
    """
    Display an error message.

    Args:
        message: The error message to display
    """
    q_console.print(f"[bold red]{message}[/bold red]\n")


def show_warning(message: str) -> None:
    """
    Display a warning message.

    Args:
        message: The warning message to display
    """
    q_console.print(f"[bold yellow]{message}[/bold yellow]\n")


def show_info(message: str) -> None:
    """
    Display an informational message.

    Args:
        message: The informational message to display
    """
    q_console.print(f"[bold blue]{message}[/bold blue]\n")
