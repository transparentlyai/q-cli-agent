import re
from typing import Any, Dict

from q.core.config import config
from q.core.logging import get_logger
from q.operators.fetch import execute_fetch as run_fetch_operator
from q.operators.read import execute_read as run_read_operator
from q.operators.shell import run_shell as run_shell_operator
from q.operators.write import write_file as run_write_operator

logger = get_logger(__name__)


OPERATION_TAG_PATTERN = re.compile(
    rf"<Q:{config.OPERATION_MARKER}\s+(?P<attributes>.*?)\s*>(?P<content>.*?)</Q:{config.OPERATION_MARKER}>",  # type: ignore
    re.IGNORECASE | re.DOTALL,
)

ATTRIBUTE_PATTERN = re.compile(r'(\w+)\s*=\s*"(.*?)"')


def parse_attributes(attr_string: str) -> Dict[str, Any]:
    """Parses the attribute string from the operation tag."""
    attributes = {}
    for match in ATTRIBUTE_PATTERN.finditer(attr_string):
        attributes[match.group(1).lower()] = match.group(2)
    return attributes


def extract_operation(text: str) -> Dict[str, Any]:
    """
    Finds the first <Q:OPERATION> tag in the text, extracts its details,
    and returns a dictionary containing the details, the text excluding the tag,
    and any parsing error.

    Args:
        text: The input string potentially containing an operation tag.

    Returns:
        A dictionary with the following keys:
        - 'operation' (Optional[Dict[str, Any]]): Dictionary with operation details
          ('type', other attributes, 'content') if a valid tag is found, else None.
        - 'text' (str): The original text with the operation tag removed. If no tag
          is found or if the tag is malformed, this will be the text after
          removing the tag structure.
        - 'error' (str): An error message if parsing failed (e.g., missing 'type'
          or empty content), otherwise an empty string.
    """
    match = OPERATION_TAG_PATTERN.search(text)
    if not match:
        return {"operation": None, "text": text, "error": ""}

    # Extract parts
    raw_attributes = match.group("attributes")
    content = match.group("content").strip()  # Strip whitespace from content
    attributes = parse_attributes(raw_attributes)

    # Always remove the tag structure from the text, even if parsing fails
    cleaned_text = text[: match.start()] + text[match.end() :]

    # --- Validation Checks ---
    if "type" not in attributes:
        error_message = (
            "Operation tag parsing error: Mandatory 'type' attribute missing."
        )
        logger.warning(f"{error_message} in text: {text[:100]}...")
        return {"operation": None, "text": cleaned_text, "error": error_message}

    if not content:  # Check if content is empty after stripping
        error_message = "Operation tag parsing error: Content cannot be empty."
        logger.warning(f"{error_message} in text: {text[:100]}...")
        # Include attributes found so far in the error context if needed, but operation is None
        return {"operation": None, "text": cleaned_text, "error": error_message}
    # --- End Validation Checks ---

    operation_details = {
        **attributes,  # Includes 'type' and any other attributes
        "content": content,
    }
    logger.debug(f"Extracted operation: {operation_details}")
    return {"operation": operation_details, "text": cleaned_text, "error": ""}


def execute_operation(operation_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes an operation based on the provided operation details.

    Args:
        operation_details: Dictionary containing operation details including 'type' and 'content'.

    Returns:
        A dictionary containing:
        - 'results' (Dict[str, Any]): The structured output from the executed operator.
        - 'error' (Optional[str]): An error message if execution failed.
    """
    if not operation_details:
        return {"results": None, "error": "No operation details provided"}

    operation_type = operation_details.get("type")
    operation_content = operation_details.get("content")

    if operation_content is None:
        return {"results": None, "error": "Operation content is missing"}

    logger.info(f"Executing operation of type: {operation_type}")
    execution_results = None
    execution_error = None

    try:
        if operation_type == "shell":
            # Ensure operation_content is a string before passing to run_shell_operator
            if not isinstance(operation_content, str):
                raise TypeError(
                    f"Shell command must be a string, got {type(operation_content)}"
                )

            # Shell operator now returns a structured response with reply and error fields
            result = run_shell_operator(operation_content)
            execution_results = result

            # If the operator reported an error, capture it
            if result.get("error"):
                execution_error = result["error"]

            logger.info(
                f"Shell operator returned results for command: {operation_content[:50]}..."
            )

        elif operation_type == "read":
            # Ensure file_path_to_read is a string
            if not isinstance(operation_content, str):
                raise TypeError(
                    f"File path must be a string, got {type(operation_content)}"
                )

            file_path_to_read = operation_content
            
            # Extract from and to parameters if they exist
            from_line = operation_details.get("from")
            to_line = operation_details.get("to")
            
            # Convert to integers if specified
            from_line = int(from_line) if from_line else None
            to_line = int(to_line) if to_line else None
            
            # Read operator now returns a structured response with reply, attachment, and error fields
            result = run_read_operator(file_path_to_read, from_line, to_line)
            execution_results = result

            # If the operator reported an error, capture it
            if result.get("error"):
                execution_error = result["error"]

            # Log with line range information if specified
            if from_line or to_line:
                range_info = []
                if from_line:
                    range_info.append(f"from={from_line}")
                if to_line:
                    range_info.append(f"to={to_line}")
                logger.info(f"Read operator returned results for file: {file_path_to_read} ({', '.join(range_info)})")
            else:
                logger.info(f"Read operator returned results for file: {file_path_to_read}")

        elif operation_type == "write":
            # Extract file path and diff content from operation details
            file_path = operation_details.get("path")
            diff_content = operation_content

            if not file_path:
                execution_error = "Write operation requires a 'path' attribute"
                logger.warning(execution_error)
            else:
                # Write operator returns a structured response with reply and error fields
                result = run_write_operator(file_path, diff_content)
                execution_results = result

                # If the operator reported an error, capture it
                if result.get("error"):
                    execution_error = result["error"]

                logger.info(f"Write operator returned results for file: {file_path}")

        elif operation_type == "fetch":
            # Ensure url is a string
            if not isinstance(operation_content, str):
                raise TypeError(f"URL must be a string, got {type(operation_content)}")

            url = operation_content
            # Fetch operator returns a structured response with reply, content, and error fields
            result = run_fetch_operator(url)
            execution_results = result

            # If the operator reported an error, capture it
            if result.get("error"):
                execution_error = result["error"]

            logger.info(f"Fetch operator returned results for URL: {url}")

        else:
            execution_error = f"Unsupported operation type: '{operation_type}'"
            logger.warning(execution_error)

    except Exception as e:
        execution_error = f"Error during '{operation_type}' operation execution: {e}"
        logger.error(execution_error, exc_info=True)
        execution_results = None

    return {
        "results": execution_results,
        "error": execution_error,
    }
