import os

import pathspec

from q.core.logging import get_logger
from q.utils.helpers import get_current_model

logger = get_logger(__name__)  # Initialize logger for this module


def load_context():
    project_root = find_project_root()
    user_context_file = os.path.expanduser("~/.config/q/user.md")
    context = {}

    try:
        with open(user_context_file, "r") as f:
            context["user_context"] = f.read()
    except FileNotFoundError:
        context["user_context"] = ""
        logger.debug(
            f"User context file not found: {user_context_file}"
        )  # Log debug message

    # Only load project context and files if we found a project root
    if project_root:
        project_context_file = os.path.join(project_root, ".Q", "project.md")
        try:
            with open(project_context_file, "r") as f:
                context["project_context"] = f.read()
        except FileNotFoundError:
            context["project_context"] = ""
            logger.debug(
                f"Project context file not found: {project_context_file}"
            )  # Log debug message

        # Only get filtered files if we have a project root
        project_files = "\n".join(get_filtered_files_by_gitignore(project_root))
        context["project_files"] = project_files
    else:
        context["project_context"] = ""
        context["project_files"] = ""
        logger.debug("No project root found, skipping project files and context")

    context["model"] = get_current_model()
    logger.inspect(context)  # pyright: ignore
    return context


def find_project_root():
    current_dir = os.getcwd()
    home_dir = os.path.expanduser("~")
    one_level_above_home = os.path.dirname(home_dir)

    search_dir = current_dir
    while search_dir != one_level_above_home:
        if os.path.exists(os.path.join(search_dir, ".Q")) or os.path.exists(
            os.path.join(search_dir, ".git")
        ):
            return search_dir
        search_dir = os.path.dirname(search_dir)
        if search_dir == "/":  # to prevent infinite loop in case of root directory
            return ""  # or maybe current_dir? or None is better to indicate not found? Let's return None

    return ""  # Not found


# --- New Helper function ---
def _find_gitignore(start_path):
    """Helper to find the nearest .gitignore file upwards from start_path."""
    current_dir = os.path.abspath(start_path)
    while True:
        gitignore_path = os.path.join(current_dir, ".gitignore")
        if os.path.isfile(gitignore_path):
            logger.debug(f"Found .gitignore at: {gitignore_path}")
            return gitignore_path
        parent_dir = os.path.dirname(current_dir)
        # Stop if we reach the filesystem root or the directory doesn't change
        if parent_dir == current_dir or parent_dir == os.path.dirname(parent_dir):
            logger.debug(f"No .gitignore found at or above: {start_path}")
            return None
        current_dir = parent_dir


# --- New Main function ---
def get_filtered_files_by_gitignore(start_path):
    """
    Lists files under start_path, respecting .gitignore rules found in or above start_path,
    always excluding the .git directory, and always including the .Q directory (relative to start_path).

    Filters directories *before* traversing them for efficiency.

    Args:
        start_path (str): The directory path to start searching from.

    Returns:
        list: A list of absolute file paths, excluding those ignored by .gitignore or .git,
              but always including files within the .Q directory located directly under start_path.
              Returns an empty list if start_path is not a valid directory.
    """
    abs_start_path = os.path.abspath(start_path)
    if not os.path.isdir(abs_start_path):
        logger.error(f"Provided path is not a valid directory: {abs_start_path}")
        return []

    gitignore_path = _find_gitignore(abs_start_path)
    spec = None
    if gitignore_path:
        try:
            with open(gitignore_path, "r") as f:
                # Use GitWildMatchPattern for standard .gitignore syntax
                spec = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern,  # pyright: ignore
                    f,
                )
            logger.debug(f"Using .gitignore rules from: {gitignore_path}")
        except Exception as e:
            logger.error(f"Error reading or parsing {gitignore_path}: {e}")
            # Continue without gitignore filtering if parsing fails

    filtered_files = []
    # Use abs_start_path for walking
    for root, dirs, files in os.walk(
        abs_start_path, topdown=True
    ):  # topdown=True is crucial
        # --- Directory Filtering ---
        # 1. Always exclude .git directory first (modify dirs in-place)
        if ".git" in dirs:
            dirs.remove(".git")
            logger.debug(f"Explicitly excluding .git directory found in: {root}")

        # 2. Apply .gitignore rules, but *always keep* .Q (modify dirs in-place)
        if spec:
            # Calculate path relative to start_path for matching with pathspec
            rel_root_for_match = os.path.relpath(root, abs_start_path)
            if rel_root_for_match == ".":
                rel_root_for_match = ""  # Use empty string for root level

            # Keep directory 'd' if it's '.Q' OR if gitignore doesn't match it.
            # Important: Modify dirs[:] in-place!
            dirs[:] = [
                d
                for d in dirs
                if d == ".Q"
                or not spec.match_file(
                    os.path.join(rel_root_for_match, d).replace(os.sep, "/")
                )
            ]
        # --- End Directory Filtering ---

        # --- File Filtering and Collection ---
        for file in files:
            # Calculate relative path for matching (using '/' separator for consistency)
            rel_root_for_match = os.path.relpath(root, abs_start_path)
            if rel_root_for_match == ".":
                rel_root_for_match = ""  # Use empty string for root level
            # Ensure consistent '/' separator for matching logic below
            rel_file_path_for_match = os.path.join(rel_root_for_match, file).replace(
                os.sep, "/"
            )

            # Check if the file is within the .Q directory relative to start_path
            # This uses '/' because rel_file_path_for_match was normalized above.
            is_in_dot_q_at_root = rel_file_path_for_match.startswith(".Q/")

            # Include the file if it's in .Q OR if gitignore doesn't match it (or no spec exists)
            if (
                is_in_dot_q_at_root
                or not spec
                or not spec.match_file(rel_file_path_for_match)
            ):
                # Store the absolute path
                absolute_file_path = os.path.join(root, file)
                filtered_files.append(absolute_file_path)
        # --- End File Filtering ---

    logger.debug(
        f"Found {len(filtered_files)} files in '{start_path}' after gitignore/.git/.Q filtering (returning absolute paths)."
    )
    return filtered_files

