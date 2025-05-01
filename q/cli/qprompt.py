# q/cli/qprompt.py
# This module handles the interactive prompt using prompt_toolkit.

import os
import sys
from datetime import datetime
from typing import Iterator, List, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import (
    Completer,
    Completion,
    PathCompleter,
    merge_completers,
)
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from pyfzf.pyfzf import FzfPrompt

from q.cli.approvals import is_auto_approve_active
from q.cli.commands import CommandCompleter
from q.cli.qconsole import q_console

# Define a simple style for the prompt
prompt_style = Style.from_dict(
    {
        "": "#ff0066",
        "prompt": "#FF4500",
        "prompt.multiline": "#0066CC",
        "hint": "#888888",
    }
)

# Define the fixed prompt strings
FIXED_PROMPT = FormattedText([("class:prompt", " Q⏵ ")])
AUTO_APPROVE_PROMPT = FormattedText([("class:prompt", " AQ⏵ ")])
MULTILINE_PROMPT = " M⏵ "
MULTILINE_HINT = "[Alt+Enter to submit] "

# Define the history file path
history_dir = os.path.expanduser("~/.config/q")
history_file_path = os.path.join(history_dir, "history")

# Ensure the directory exists
os.makedirs(history_dir, exist_ok=True)

# Create a FileHistory instance
# Note: prompt_toolkit's FileHistory doesn't directly support the #/+ format.
# We handle the format manually for FZF, but FileHistory manages the file itself.
q_history = FileHistory(history_file_path)


class CommandArgumentPathCompleter(Completer):
    """
    A custom completer that tries to complete paths for the word
    before the cursor, potentially useful for command arguments.
    """

    def __init__(self):
        self.path_completer = PathCompleter(expanduser=True)

    def get_completions(
        self, document: Document, complete_event
    ) -> Iterator[Completion]:
        text_before_cursor = document.text_before_cursor

        if text_before_cursor.startswith('/') and len(text_before_cursor.strip()) <= 1:
            return []

        words = text_before_cursor.split()
        if not words:
            return []

        current_word = words[-1]
        dummy_document = Document(current_word, len(current_word))

        looks_like_path = False
        if (
            current_word.startswith("/")
            or current_word.startswith("./")
            or current_word.startswith("../")
            or current_word.startswith("~")
        ):
            looks_like_path = True
        elif "/" in current_word or "\\" in current_word:
            looks_like_path = True
        elif not words[:-1]:
             looks_like_path = True # Also complete if it's the first word

        if looks_like_path:
            last_slash_index = current_word.rfind("/")
            if last_slash_index >= 0:
                path_prefix = current_word[: last_slash_index + 1]
                base_path = path_prefix
                partial_name = current_word[last_slash_index + 1 :]
            else:
                path_prefix = ""
                base_path = "./"
                partial_name = current_word

            if base_path.startswith("~"):
                base_path = os.path.expanduser(base_path)

            try:
                if os.path.isdir(os.path.expanduser(base_path)):
                    dir_contents = os.listdir(os.path.expanduser(base_path))
                    matches = [
                        item for item in dir_contents if item.startswith(partial_name)
                    ]

                    for item in matches:
                        full_path = os.path.join(base_path, item)
                        expanded_path = os.path.expanduser(full_path)
                        display_text = item
                        completion_text = path_prefix + item

                        if os.path.isdir(expanded_path):
                            display_text = f"{item}/"
                            completion_text = f"{path_prefix}{item}/"

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
                pass

            path_completions = self.path_completer.get_completions(
                dummy_document, complete_event
            )
            for completion in path_completions:
                adjusted_start_position = completion.start_position - len(current_word)
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
session = PromptSession(history=q_history)


def get_user_input() -> str:
    """
    Gets user input using prompt_toolkit with custom key bindings and features.
    - Enter: Submits the current line (unless in multiline mode).
    - Alt+Enter: Toggles multiline mode. Submits when toggled off.
    - Tab: Triggers completion for commands and file paths.
    - Ctrl+R: Triggers FZF fuzzy history search with simplified timestamps.
    - Ctrl+C: Shows a message about using 'exit' or 'quit'.
    Includes persistent history (~/.config/q/history).
    The multiline prompt includes a grey hint "[Alt+Enter to submit]".
    The prompt shows "AQ⏵ " when auto-approve is active.

    Returns:
        The string entered by the user.

    Raises:
        EOFError: If the user signals end-of-file (e.g., Ctrl+D).
    """
    kb = KeyBindings()
    is_multiline = [False]
    current_prompt = [FIXED_PROMPT]

    def _parse_history_entry(timestamp_line: str, command_line: str) -> Tuple[str, str] | None:
        """
        Parses a timestamp and command line pair from history.

        Args:
            timestamp_line: The line starting with '# '.
            command_line: The line starting with '+'.

        Returns:
            A tuple (formatted_display_string, original_command) or None if parsing fails.
        """
        if not timestamp_line.startswith("# ") or not command_line.startswith("+"):
            return None

        try:
            # Extract timestamp string after '# '
            ts_str = timestamp_line[2:].strip()
            # Parse the timestamp (handle potential microseconds)
            try:
                dt_obj = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                 # Fallback if microseconds are missing
                dt_obj = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

            # Format the timestamp: DD Mon HH:MM (e.g., 15 Mar 17:02)
            formatted_ts = dt_obj.strftime("%d %b %H:%M")

            # Extract command after '+' and strip leading/trailing whitespace
            original_command = command_line[1:].strip()

            # Create the display string for FZF
            display_string = f"[{formatted_ts}] {original_command}"

            return display_string, original_command
        except (ValueError, IndexError):
            # Handle errors during parsing or formatting
            return None

    def _show_history_fzf(event):
        """Handle Ctrl+R: Show command history using FZF with formatted entries."""
        history_data: List[Tuple[str, str]] = [] # List of (display_string, original_command)
        try:
            # Ensure history file exists before reading
            if not os.path.exists(history_file_path):
                 event.cli.output.write("History file not found.\n")
                 return
            with open(history_file_path, "r") as f:
                lines = f.readlines()
        except IOError as e:
             event.cli.output.write(f"Error reading history file: {e}\n")
             return

        if not lines:
            event.cli.output.write("History file is empty.\n")
            return

        # Process lines sequentially, pairing timestamp and command lines
        timestamp_line = None
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith("# "):
                # Found a timestamp line, store it
                timestamp_line = stripped_line
            elif stripped_line.startswith("+") and timestamp_line is not None:
                # Found a command line immediately after a timestamp line
                command_line = stripped_line
                parsed_entry = _parse_history_entry(timestamp_line, command_line)
                if parsed_entry:
                    history_data.append(parsed_entry)
                # Reset timestamp_line after processing a pair
                timestamp_line = None
            # Ignore empty lines or lines that don't fit the pattern

        if not history_data:
            event.cli.output.write("No valid history entries found in the expected format.\n")
            return

        # Reverse history so recent commands appear first in FZF
        history_data.reverse()

        # Create a mapping from display string back to original command
        # Using index as key in case of duplicate display strings (unlikely but safer)
        display_options = [item[0] for item in history_data]
        index_to_command_map = {i: item[1] for i, item in enumerate(history_data)}


        fzf = FzfPrompt()
        try:
            # Use FZF to select a display string. Pass --no-sort and --with-nth=1.. to search only command part
            # Pass --select-1 to exit immediately on selection
            # Pass --exit-0 to exit with 0 status even if no match
            # Pass --print-query to print the query if nothing selected
            # Pass --bind='ctrl-r:reload(cat ~/.config/q/history)' # Example, needs refinement
            # Pass --header='CTRL+R: Search History'
            # Use prompt to guide user
            selected_display_list = fzf.prompt(
                display_options,
                fzf_options="--no-sort --header='[CTRL+R History Search]' --prompt='Search> ' --select-1 --exit-0"
            )


            if selected_display_list:
                selected_display = selected_display_list[0]
                # Find the index of the selected display string to get the original command
                try:
                    selected_index = display_options.index(selected_display)
                    selected_command = index_to_command_map.get(selected_index)

                    if selected_command is not None:
                        # Replace buffer content with the original command
                        event.cli.current_buffer.document = Document(
                            text=selected_command, cursor_position=len(selected_command)
                        )
                    else:
                         event.cli.output.write("Error: Could not retrieve original command.\n")
                except ValueError:
                     event.cli.output.write("Error: Selected item not found in history map.\n")

            # If selected_display_list is empty (e.g., user pressed Esc), do nothing.

        except Exception as e:
            event.cli.output.write(f"Error running FZF: {e}\n")
            event.cli.output.write("Ensure 'fzf' executable is installed and in your PATH.\n")


    @kb.add("c-m")  # Enter
    def _handle_enter(event):
        if is_multiline[0]:
            event.cli.current_buffer.insert_text("\n")
        else:
            event.cli.current_buffer.validate_and_handle()

    @kb.add("escape", "c-m")  # Alt+Enter
    def _handle_alt_enter(event):
        if is_multiline[0]:
            is_multiline[0] = False
            if is_auto_approve_active():
                current_prompt[0] = AUTO_APPROVE_PROMPT
            else:
                current_prompt[0] = FIXED_PROMPT
            event.cli.current_buffer.validate_and_handle()
        else:
            is_multiline[0] = True
            current_prompt[0] = FormattedText(
                [
                    ("class:prompt.multiline", MULTILINE_PROMPT),
                    ("class:hint", MULTILINE_HINT),
                    ("", "\n"),
                ]
            )
            event.cli.current_buffer.insert_text("\n")

    @kb.add("c-c")  # Ctrl+C
    def _handle_ctrl_c(event):
        event.app.exit(exception=KeyboardInterrupt())

    @kb.add("c-r") # Ctrl+R for history search
    def _(event):
        """Bind Ctrl+R to FZF history search."""
        _show_history_fzf(event)

    # Reset multiline state for this specific prompt call
    is_multiline[0] = False

    path_completer = CommandArgumentPathCompleter()
    command_completer = CommandCompleter()
    merged_completer = merge_completers([command_completer, path_completer])

    try:
        if not is_multiline[0]:
            if is_auto_approve_active():
                current_prompt[0] = AUTO_APPROVE_PROMPT
            else:
                current_prompt[0] = FIXED_PROMPT

        user_input = session.prompt(
            lambda: current_prompt[0],
            style=prompt_style,
            key_bindings=kb,
            completer=merged_completer,
            complete_while_typing=False,
        )
        return user_input
    except KeyboardInterrupt:
        q_console.print("[#666666]Use 'exit' or 'quit' to exit the application.[/]")
        return ""
    except EOFError:
        return "exit"


# Example usage (if run directly)
if __name__ == "__main__":
    # Create dummy history for testing if needed
    dummy_history_content = """# 2025-03-15 17:02:22.826496
+ls -l /tmp

# 2025-03-15 17:05:10.123456
+echo "Hello World"

# 2025-03-16 09:30:00.000000
+/help

# 2025-03-16 09:31:15.987654
+cat q/cli/qprompt.py
"""
    # Ensure history directory exists
    os.makedirs(os.path.dirname(history_file_path), exist_ok=True)
    # Create/overwrite dummy history only if it doesn't exist or is empty
    if not os.path.exists(history_file_path) or os.path.getsize(history_file_path) == 0:
        print(f"Creating dummy history file at {history_file_path}")
        try:
            with open(history_file_path, "w") as f:
                f.write(dummy_history_content)
            # Re-initialize history object to load the new file content
            session.history = FileHistory(history_file_path)
        except IOError as e:
            print(f"Error creating dummy history file: {e}")


    try:
        print("Entering example input loop (Ctrl+D or Ctrl+C to exit):")
        print("Press Enter to submit.")
        print(
            f"Press Alt+Enter to start multiline input (prompt changes to '{MULTILINE_PROMPT}' + grey hint)."
        )
        print("While in multiline, Enter adds a newline.")
        print("Press Alt+Enter again to submit the multiline input.")
        print(f"History will be saved to {history_file_path}")
        print("Press Tab to activate completion for commands and file paths.")
        print("Press Ctrl+R to search history with FZF (formatted timestamps).")
        print("Examples to try:")
        print("  - /s[TAB] to complete /save")
        print("  - cat /etc/ho[TAB]")
        print("  - ls ~/Doc[TAB]")
        print("  - ./my[TAB]")
        while True:
            user_text = get_user_input()
            if user_text.lower() in ["exit", "quit"]:
                 print("\nExiting example.")
                 break
            if user_text:
                print(f"You entered:\n---\n{user_text}\n---")
                # Add entry to history in the expected format for testing
                # Note: This manual addition bypasses prompt_toolkit's history deduplication etc.
                # It's just for making the FZF example work when run directly.
                try:
                    with open(history_file_path, "a") as f:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                        f.write(f"# {ts}\n")
                        f.write(f"+{user_text}\n")
                        f.write("\n") # Add empty line for consistency with prompt_toolkit's format
                except IOError as e:
                    print(f"Error writing to history file: {e}")


    except (EOFError, KeyboardInterrupt):
        print("\nExiting example.")