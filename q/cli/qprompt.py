# q/cli/qprompt.py
# This module handles the interactive prompt using prompt_toolkit.

import os  # - Import os for path expansion
import sys
from typing import Iterator  # Add import for type annotation

from prompt_toolkit import PromptSession  # - Import PromptSession
from prompt_toolkit.completion import (  # - Import completion classes
    Completer,
    Completion,
    PathCompleter,
    merge_completers,
)
from prompt_toolkit.document import Document  # - Import Document for completion
from prompt_toolkit.formatted_text import (
    FormattedText,  # - Import FormattedText for styled prompts
)
from prompt_toolkit.history import FileHistory  # - Import FileHistory
from prompt_toolkit.key_binding import (
    KeyBindings,  # - Import KeyBindings for custom keys
)
from prompt_toolkit.styles import Style

from q.cli.approvals import is_auto_approve_active  # Import the new function
from q.cli.commands import CommandCompleter
from q.cli.qconsole import q_console

# Define a simple style for the prompt
# See https://python-prompt-toolkit.readthedocs.io/en/master/pages/styling.html
prompt_style = Style.from_dict(
    {
        # User input (default text)
        "": "#ff0066",
        # Prompt message (before input) - Style for "Q> "
        "prompt": "#FF4500",
        # Style for when multiline is active (optional visual feedback)
        "prompt.multiline": "#0066CC",  # Example: Blue prompt in multiline
        # Style for the multiline hint text
        "hint": "#888888",  # Dim grey
    }
)

# Define the fixed prompt strings
FIXED_PROMPT = FormattedText(
    [("class:prompt", " Q⏵ ")]
)  # Use FormattedText for consistency
AUTO_APPROVE_PROMPT = FormattedText(
    [("class:prompt", " AQ⏵ ")]
) # Prompt when auto-approve is active
MULTILINE_PROMPT = " M⏵ "  # Prompt indicator for multiline mode
MULTILINE_HINT = "[Alt+Enter to submit] "  # Hint text for multiline submission

# Define the history file path
# Use os.path.expanduser to correctly resolve the home directory
history_file_path = os.path.expanduser("~/.qhistory")  # - Define history path

# Create a FileHistory instance
q_history = FileHistory(history_file_path)  # - Create history object


class CommandArgumentPathCompleter(Completer):
    """
    A custom completer that tries to complete paths for the word
    before the cursor, potentially useful for command arguments.
    """

    def __init__(self):
        # Initialize with expand_user=True to handle ~ in paths
        self.path_completer = PathCompleter(expanduser=True)

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterator[Completion]:
        # Get the text before the cursor
        text_before_cursor = document.text_before_cursor

        # Skip path completion if the input starts with a slash and we're at the beginning
        # This ensures only commands are suggested when typing a slash at the beginning
        if text_before_cursor.startswith('/') and len(text_before_cursor.strip()) <= 1:
            return []

        # Get the "word" before the cursor
        # A simple approach: split by whitespace and take the last part.
        # This is NOT a robust shell-like parser.
        words = text_before_cursor.split()
        if not words:
            # No word before cursor, no completion
            return []

        current_word = words[-1]

        # Create a dummy document representing just the current word,
        # placing the cursor at the end of this dummy document.
        dummy_document = Document(current_word, len(current_word))

        # --- Check if it looks like a path ---
        looks_like_path = False
        if (
            current_word.startswith("/")
            or current_word.startswith("./")
            or current_word.startswith("../")
            or current_word.startswith("~")
        ):
            looks_like_path = True
        elif (
            "/" in current_word or "\\" in current_word
        ):  # Check for separators within the word
            looks_like_path = True
        # Also complete if it's the first word (could be a command path)
        elif not words[:-1]:
            looks_like_path = True

        if looks_like_path:
            # Get the path prefix (everything up to the last directory separator)
            last_slash_index = current_word.rfind("/")
            if last_slash_index >= 0:
                path_prefix = current_word[: last_slash_index + 1]  # Include the slash
                base_path = path_prefix
                partial_name = current_word[last_slash_index + 1 :]
            else:
                path_prefix = ""
                base_path = "./"
                partial_name = current_word

            # Expand user directory if needed
            if base_path.startswith("~"):
                base_path = os.path.expanduser(base_path)

            try:
                # Get directory contents
                if os.path.isdir(os.path.expanduser(base_path)):
                    dir_contents = os.listdir(os.path.expanduser(base_path))

                    # Filter based on partial name
                    matches = [
                        item for item in dir_contents if item.startswith(partial_name)
                    ]

                    # Generate completions with proper formatting
                    for item in matches:
                        full_path = os.path.join(base_path, item)
                        expanded_path = os.path.expanduser(full_path)

                        # Determine if it's a directory and add trailing slash if so
                        display_text = item
                        completion_text = path_prefix + item

                        if os.path.isdir(expanded_path):
                            display_text = f"{item}/"
                            completion_text = f"{path_prefix}{item}/"

                        # Calculate the correct start position for replacement
                        start_position = -len(current_word)

                        yield Completion(
                            completion_text,
                            start_position=start_position,
                            display=display_text,
                            display_meta="dir"
                            if os.path.isdir(expanded_path)
                            else "file",
                        )

                    return
            except (PermissionError, FileNotFoundError):
                # Fall back to the default path completer if we can't access the directory
                pass

            # Delegate to the default path completer as a fallback
            path_completions = self.path_completer.get_completions(
                dummy_document, complete_event
            )

            for completion in path_completions:
                adjusted_start_position = completion.start_position - len(current_word)

                # Ensure we're returning the full path, not just the completion part
                if last_slash_index >= 0:
                    full_path = path_prefix + completion.text
                else:
                    full_path = completion.text

                yield Completion(
                    full_path,
                    start_position=adjusted_start_position,
                    display=completion.display,
                    display_meta=completion.display_meta,
                    style=completion.style,
                    selected_style=completion.selected_style,
                )


# Create a PromptSession instance with history enabled
# We'll add the completer in the get_user_input function
session = PromptSession(history=q_history)


def get_user_input() -> str:
    """
    Gets user input using prompt_toolkit with custom Enter/Alt+Enter behavior.
    - Enter: Submits the current line (unless Alt+Enter was pressed).
    - Alt+Enter: Toggles multiline mode. Submits when toggled off.
    - Tab: Triggers completion for commands and file paths.
    - Ctrl+C: Shows a message about using 'exit' or 'quit' instead of exiting.
    Includes persistent history (~/.qhistory).
    The multiline prompt includes a grey hint "[Alt+Enter to submit]".
    The prompt shows "AQ⏵ " when auto-approve is active.

    Returns:
        The string entered by the user.

    Raises:
        EOFError: If the user signals end-of-file (e.g., Ctrl+D).
    """
    kb = KeyBindings()
    # Use a mutable type (list) to allow modification within closures
    is_multiline = [False]
    # Store current prompt message (can be string or FormattedText)
    # The actual value will be set dynamically before each prompt call
    current_prompt = [FIXED_PROMPT]

    @kb.add("c-m")  # Enter
    def _handle_enter(event):
        """Handle Enter key press."""
        if is_multiline[0]:
            # In multiline mode, insert a newline
            event.cli.current_buffer.insert_text("\n")
        else:
            # Not in multiline mode, submit the input
            event.cli.current_buffer.validate_and_handle()

    @kb.add("escape", "c-m")  # Alt+Enter (often sends Escape followed by Enter)
    def _handle_alt_enter(event):
        """Handle Alt+Enter key press."""
        if is_multiline[0]:
            # Currently in multiline mode, so exit and submit
            is_multiline[0] = False
            # Set prompt based on auto-approve status when exiting multiline
            if is_auto_approve_active():
                current_prompt[0] = AUTO_APPROVE_PROMPT
            else:
                current_prompt[0] = FIXED_PROMPT
            event.cli.current_buffer.validate_and_handle()
        else:
            # Not in multiline mode, so enter multiline mode
            is_multiline[0] = True
            # Update the prompt to include the styled multiline indicator and hint
            current_prompt[0] = FormattedText(
                [
                    ("class:prompt.multiline", MULTILINE_PROMPT),
                    ("class:hint", MULTILINE_HINT),
                    # Add a newline visually after the hint in the prompt itself
                    ("", "\n"),
                ]
            )
            # Insert a newline into the *buffer* to start the multiline input
            event.cli.current_buffer.insert_text("\n")

    @kb.add("c-c")  # Ctrl+C
    def _handle_ctrl_c(event):
        """Handle Ctrl+C key press during input."""
        # Exit the current prompt session with a custom exception
        event.app.exit(exception=KeyboardInterrupt())

    # Reset multiline state for this specific prompt call
    is_multiline[0] = False

    # Create our custom completers
    path_completer = CommandArgumentPathCompleter()
    command_completer = CommandCompleter()

    # Merge the completers with command_completer having priority
    merged_completer = merge_completers([command_completer, path_completer])

    try:
        # Determine the correct prompt *before* calling session.prompt
        # This ensures the lambda picks up the right value
        if not is_multiline[0]: # Only check auto-approve for single-line prompt
            if is_auto_approve_active():
                current_prompt[0] = AUTO_APPROVE_PROMPT
            else:
                current_prompt[0] = FIXED_PROMPT
        # If is_multiline[0] is true, the prompt is already set by _handle_alt_enter

        # prompt_toolkit raises EOFError automatically,
        # which is handled in the main_loop.
        user_input = session.prompt(
            lambda: current_prompt[0],  # Use a lambda to dynamically change prompt
            style=prompt_style,
            key_bindings=kb,  # Use our custom key bindings
            completer=merged_completer,  # Use our merged completer
            complete_while_typing=False,  # Only complete when Tab is pressed
            # Refresh prompt on key press might be needed if dynamically changing style
            # refresh_interval=0.1 # Uncomment if visual prompt changes lag
        )
        return user_input
    except KeyboardInterrupt:
        # This will be reached when Ctrl+C is pressed due to our key binding
        # Print the message here after exiting the prompt
        q_console.print("[#666666]Use 'exit' or 'quit' to exit the application.[/]")
        return ""
    except EOFError:
        # Handle Ctrl+D
        return "exit"


# Example usage (if run directly)
if __name__ == "__main__":
    try:
        # Example usage no longer needs arguments
        print("Entering example input loop (Ctrl+D or Ctrl+C to exit):")
        print("Press Enter to submit.")
        print(
            f"Press Alt+Enter to start multiline input (prompt changes to '{MULTILINE_PROMPT}' + grey hint)."
        )  # Updated help text
        print("While in multiline, Enter adds a newline.")
        print("Press Alt+Enter again to submit the multiline input.")
        print(f"History will be saved to {history_file_path}")
        print(
            "Press Tab to activate completion for commands and file paths."
        )
        print("Examples to try:")
        print("  - /s[TAB] to complete /save")
        print("  - cat /etc/ho[TAB]")
        print("  - ls ~/Doc[TAB]")
        print("  - ./my[TAB]")
        while True:
            user_text = get_user_input()
            print(f"You entered:\n---\n{user_text}\n---")
    except (EOFError, KeyboardInterrupt):
        print("\nExiting example.")