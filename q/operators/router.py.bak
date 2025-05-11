import re
from typing import Any, Dict

from bs4 import BeautifulSoup, Tag

from q.core.config import config
from q.core.logging import get_logger
from q.operators.fetch import execute_fetch as run_fetch_operator
from q.operators.read import execute_read as run_read_operator
from q.operators.shell import run_shell as run_shell_operator
from q.operators.write import write_file as run_write_operator

logger = get_logger(__name__)

# Fallback regular expressions for recovery when BS4 fails
OPERATION_EVIDENCE_PATTERN = re.compile(
    r"<\s*[qQ].*?(?:operation|OPERATION).*?>.*?</\s*[qQ].*?(?:operation|OPERATION).*?>",
    re.DOTALL,
)

# For potential content heuristics in fallback scenarios
URL_PATTERN = re.compile(r"(https?://\S+)")
PATH_PATTERN = re.compile(r"([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)")


def parse_attributes(tag: Tag) -> Dict[str, Any]:
    """
    Parses the attributes from a BeautifulSoup tag.

    Args:
        tag: The BeautifulSoup tag object

    Returns:
        Dictionary containing the extracted attributes
    """
    attributes = {}

    # Extract all attributes from the tag
    for key, value in tag.attrs.items():
        # Convert to lowercase for consistent lookup
        attributes[key.lower()] = value

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
    # Log the first 100 chars for debugging
    logger.debug(f"Extracting operation from text (start): {text[:100]}...")

    # Create a custom BeautifulSoup parser with a div wrapper to help with parsing
    # The wrapper helps with potentially malformed or incomplete tags
    wrapped_text = f"<div>{text}</div>"
    soup = BeautifulSoup(wrapped_text, "html.parser")

    # First try the standard format - case insensitive using CSS selector
    operation_tag = soup.select_one(f"q\\:{config.OPERATION_MARKER}")

    # If no match, try alternate formats with more flexibility
    if not operation_tag:
        # Try with space variations and case insensitivity
        for tag in soup.find_all():
            # Check if the tag name resembles our operation tag (case insensitive)
            if (
                tag.name.lower() == f"q:{config.OPERATION_MARKER}".lower()
                or tag.name.lower() == f"q:{config.OPERATION_MARKER.lower()}"
            ):
                operation_tag = tag
                logger.info("Found operation using flexible tag name matching")
                break

            # Check for "q" tags that might have operation marker in attributes
            if tag.name.lower() == "q" and any(
                attr.lower() == config.OPERATION_MARKER.lower() for attr in tag.attrs
            ):
                operation_tag = tag
                logger.info(
                    "Found operation as 'q' tag with operation marker attribute"
                )
                break

    # If still not found, check if there's evidence of an operation tag using regex
    if not operation_tag:
        # Check for possible operation tag evidence
        tag_evidence = OPERATION_EVIDENCE_PATTERN.search(text)
        if tag_evidence:
            logger.warning(
                "BeautifulSoup parsing failed but operation tag markers detected - trying aggressive fallback"
            )
            logger.debug(f"Evidence found: {tag_evidence.group(0)[:100]}...")
            return extract_operation_raw(text)
        else:
            # Additional check for common write operation pattern
            write_pattern = re.compile(
                r"<Q:[^>]*?type\s*=\s*[\"']?write[\"']?[^>]*?path\s*=\s*[\"']?[^\"'>]+[\"']?[^>]*?>",
                re.IGNORECASE,
            )
            write_match = write_pattern.search(text)
            if write_match:
                logger.warning(
                    "Detected partial write operation tag - trying aggressive fallback"
                )
                logger.debug(f"Write pattern found: {write_match.group(0)}")
                return extract_operation_raw(text)

    # No operation tag found
    if not operation_tag:
        return {"operation": None, "text": text, "error": ""}

    # Log the found operation tag
    logger.debug(f"Found operation tag: {str(operation_tag)[:200]}...")

    # Extract tag attributes and content
    attributes = parse_attributes(operation_tag)
    content = operation_tag.get_text().strip()

    # Log the extracted attributes and content
    logger.debug(f"Extracted attributes: {attributes}")
    logger.debug(f"Extracted content preview: {content[:100]}...")

    # Remove the tag from the original text to get cleaned_text
    original_tag_text = str(operation_tag)
    # Due to the wrapping we did, the actual tag text in the original might be slightly different
    # Let's try to find the actual tag text in the original
    clean_tag_pattern = re.compile(
        rf"<\s*[qQ][^>]*?{config.OPERATION_MARKER}.*?>.*?</\s*[qQ][^>]*?{config.OPERATION_MARKER}.*?>",
        re.DOTALL | re.IGNORECASE,
    )
    tag_match = clean_tag_pattern.search(text)
    if tag_match:
        matched_text = tag_match.group(0)
        logger.debug(f"Found matching tag in original text: {matched_text[:100]}...")
        cleaned_text = text.replace(
            matched_text, "", 1
        )  # Replace only the first occurrence
    else:
        # Fallback to simple replacement if regex fails
        logger.warning(
            "Could not find exact tag match in original text - using fallback replacement"
        )
        cleaned_text = text.replace(original_tag_text, "", 1)

    # --- Validation Checks ---
    if "type" not in attributes:
        error_message = (
            "Operation tag parsing error: Mandatory 'type' attribute missing."
        )
        logger.warning(f"{error_message} in text: {text[:100]}...")

        # Try to infer type based on content heuristics
        inferred_type = None
        if content.startswith("http://") or content.startswith("https://"):
            inferred_type = "fetch"
            logger.info("Inferred operation type 'fetch' from URL-like content")
        elif "/" in content and not content.startswith(("/", "$", "sudo")):
            # Simple heuristic for potential file paths
            inferred_type = "read"
            logger.info("Inferred operation type 'read' from path-like content")

        if inferred_type:
            attributes["type"] = inferred_type
            logger.info(f"Using inferred type: {inferred_type}")
        else:
            return {"operation": None, "text": cleaned_text, "error": error_message}

    if not content:  # Check if content is empty after stripping
        error_message = "Operation tag parsing error: Content cannot be empty."
        logger.warning(f"{error_message} in text: {text[:100]}...")
        # Include attributes found so far in the error context if needed, but operation is None
        return {"operation": None, "text": cleaned_text, "error": error_message}
    # --- End Validation Checks ---

    # For write operations, handle potential code fences in content
    if attributes.get("type") == "write":
        logger.debug(f"Write operation detected with content length: {len(content)}")
        # This is just a diagnostic check, actual processing happens in execute_operation

    operation_details = {
        **attributes,  # Includes 'type' and any other attributes
        "content": content,
    }
    logger.debug(f"Extracted operation: {str(operation_details)[:200]}...")
    return {"operation": operation_details, "text": cleaned_text, "error": ""}


def extract_operation_raw(text: str) -> Dict[str, Any]:
    """
    A more aggressive fallback parser for operation tags that tries harder to find potential operations
    when the BeautifulSoup parser fails.

    This is used internally by extract_operation when standard parsing fails but there's evidence
    of operation tags in the text.

    Args:
        text: The input string potentially containing an operation tag.

    Returns:
        Same structure as extract_operation.
    """
    logger.debug(f"Using aggressive fallback parser on text (start): {text[:100]}...")

    # First try with a standard pattern then fall back to more lenient ones
    patterns = [
        # Pattern 1: Standard Q:OPERATION format
        re.compile(
            r"<\s*[qQ][^>]*?(?:operation|OPERATION)[^>]*?>(.+?)</\s*[qQ][^>]*?(?:operation|OPERATION)[^>]*?>",
            re.DOTALL,
        ),
        # Pattern 2: Q:operation with attributes and potential write content
        re.compile(
            r"<\s*[qQ]:(?:operation|OPERATION)[^>]*?type\s*=\s*[\"']?write[\"']?[^>]*?path\s*=\s*[\"']?([^\"'>]+)[\"']?[^>]*?>(.+?)</\s*[qQ]",
            re.DOTALL | re.IGNORECASE,
        ),
        # Pattern 3: Even more lenient for write operations - catches partial tags
        re.compile(
            r"<\s*[qQ][^>]*?type\s*=\s*[\"']?write[\"']?[^>]*?path\s*=\s*[\"']?([^\"'>]+)[\"']?[^>]*?>(.+?)(?:</\s*[qQ]|$)",
            re.DOTALL | re.IGNORECASE,
        ),
    ]

    # Try each pattern in order
    match = None
    path_from_pattern = None
    matched_pattern_index = -1

    for i, pattern in enumerate(patterns):
        match_attempt = pattern.search(text)
        if match_attempt:
            match = match_attempt
            matched_pattern_index = i
            # For patterns 2 and 3, they capture the path directly
            if i >= 1:
                path_from_pattern = match.group(1)
            logger.debug(f"Matched with pattern {i + 1}")
            break

    if not match:
        logger.debug("No operation found with any pattern in aggressive fallback")
        return {"operation": None, "text": text, "error": ""}

    logger.debug(
        f"Found operation-like content with aggressive fallback: {match.group(0)[:100]}..."
    )

    # We found something that looks like an operation tag
    if matched_pattern_index == 0:
        # Standard pattern - extract content and look for attributes
        content_with_potential_attributes = match.group(1).strip()

        # Try to extract a type from what looks like attributes
        type_pattern = re.compile(r"type\s*=\s*[\"']?(\w+)[\"']?", re.IGNORECASE)
        type_match = type_pattern.search(text)

        operation_type = type_match.group(1).lower() if type_match else None

        # If we can't determine the type, try to infer it from the content
        if not operation_type:
            if (
                "http://" in content_with_potential_attributes
                or "https://" in content_with_potential_attributes
            ):
                operation_type = "fetch"
            elif (
                "/" in content_with_potential_attributes
                and not content_with_potential_attributes.startswith(("/", "$", "sudo"))
            ):
                operation_type = "read"
            else:
                # Default to shell as a last resort
                operation_type = "shell"

        # Extract potential content
        # For a shell command, it's usually just the text after the type=
        if operation_type == "shell":
            # Try to find content after type="shell"
            content_pattern = re.compile(
                r"type\s*=\s*[\"']?shell[\"']?\s*>(.+?)</", re.DOTALL | re.IGNORECASE
            )
            content_match = content_pattern.search(text)
            content = (
                content_match.group(1).strip()
                if content_match
                else content_with_potential_attributes
            )
        # For fetch, look for a URL
        elif operation_type == "fetch":
            url_match = URL_PATTERN.search(content_with_potential_attributes)
            content = (
                url_match.group(1) if url_match else content_with_potential_attributes
            )
        # For read, any file path like string
        elif operation_type == "read":
            path_match = PATH_PATTERN.search(content_with_potential_attributes)
            content = (
                path_match.group(1) if path_match else content_with_potential_attributes
            )
        # For write, try to find path attribute and content
        elif operation_type == "write":
            # Try to extract path attribute
            path_pattern = re.compile(
                r"path\s*=\s*[\"']?([^\"'>\s]+)[\"']?", re.IGNORECASE
            )
            path_match = path_pattern.search(text)
            path = path_match.group(1) if path_match else None

            # Extract content after all attributes
            if path:
                # Look for code fences within the content
                code_fence_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
                code_match = code_fence_pattern.search(
                    content_with_potential_attributes
                )

                # If we found code fences, use the content inside them
                if code_match:
                    content = code_match.group(1).strip()
                    logger.info(f"Extracted write content from within code fences")
                else:
                    content = content_with_potential_attributes

                # For write operations with path, set up the proper structure
                return {
                    "operation": {
                        "type": "write",
                        "path": path,
                        "content": content,
                        "_aggressive_fallback": True,
                    },
                    "text": text.replace(match.group(0), ""),
                    "error": "",
                }
            else:
                # Missing required path attribute for write
                return {
                    "operation": None,
                    "text": text,
                    "error": "Failed to extract write operation: missing path attribute",
                }
        else:
            content = content_with_potential_attributes

    else:
        # Matched with pattern 2 or 3 (write operation with path capture)
        operation_type = "write"
        path = path_from_pattern
        content_with_potential_attributes = match.group(2).strip()

        # Look for code fences within the content
        code_fence_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
        code_match = code_fence_pattern.search(content_with_potential_attributes)

        # If we found code fences, use the content inside them
        if code_match:
            content = code_match.group(1).strip()
            logger.info(
                f"Extracted write content from within code fences in specialized pattern"
            )
        else:
            # If no code fences, try to clean up the content
            # This is a common pattern with write operations
            lines = content_with_potential_attributes.splitlines()
            if (
                len(lines) >= 2
                and lines[0].strip().startswith("```")
                and lines[-1].strip() == "```"
            ):
                content = "\n".join(lines[1:-1])
                logger.info(
                    f"Removed code fences from write content in specialized pattern"
                )
            else:
                content = content_with_potential_attributes

        # Set up the proper structure for write operation
        return {
            "operation": {
                "type": "write",
                "path": path,
                "content": content,
                "_aggressive_fallback": True,
            },
            "text": text.replace(match.group(0), ""),
            "error": "",
        }

    # Build the operation details for non-write operations from pattern 1
    if operation_type and content:
        operation_details = {
            "type": operation_type,
            "content": content,
            # Flag that this was parsed with the fallback parser
            "_aggressive_fallback": True,
        }
        logger.warning(
            f"Extracted operation using aggressive fallback: {operation_type}"
        )
        return {
            "operation": operation_details,
            "text": text.replace(match.group(0), "")
            + "\n\n[yellow]Note: Operation tag was malformed but Q attempted to recover it. Please verify the results.[/yellow]",
            "error": "",
        }

    return {
        "operation": None,
        "text": text,
        "error": "Failed to extract operation details in fallback parser",
    }


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
                logger.info(
                    f"Read operator returned results for file: {file_path_to_read} ({', '.join(range_info)})"
                )
            else:
                logger.info(
                    f"Read operator returned results for file: {file_path_to_read}"
                )

        elif operation_type == "write":
            # Extract file path and diff content from operation details
            file_path = operation_details.get("path")
            diff_content = operation_content

            if not file_path:
                execution_error = "Write operation requires a 'path' attribute"
                logger.warning(execution_error)
            else:
                # Log the content for debugging - first 100 chars
                logger.debug(
                    f"Write operation content preview (before processing): {diff_content[:100]}..."
                )
                logger.debug(
                    f"Content type: {type(diff_content)}, Length: {len(diff_content) if diff_content else 0}"
                )

                # Pre-process content to remove code fences if present
                # This handles markdown code blocks that may be inside operation content
                lines = diff_content.splitlines() if diff_content else []

                # Log the line count for debugging
                logger.debug(f"Write operation content split into {len(lines)} lines")

                if len(lines) >= 2:
                    first_line = lines[0].strip()
                    last_line = lines[-1].strip()

                    # Log the first and last lines for debugging
                    logger.debug(f"First line: '{first_line}'")
                    logger.debug(f"Last line: '{last_line}'")

                    # Check if content is wrapped in code fences (handles cases with or without language specifier)
                    if first_line.startswith("```") and last_line == "```":
                        # Remove first and last line (the code fences)
                        diff_content = "\n".join(lines[1:-1])
                        logger.info(
                            f"Removed code fences from write operation content for file: {file_path}"
                        )
                    elif first_line.startswith("```") and "```" in last_line:
                        # Handle case where the closing fence might be on the same line as other content
                        last_line_parts = last_line.split("```", 1)
                        if len(last_line_parts) > 1:
                            modified_last_line = last_line_parts[0]
                            # Keep the last line without the fence if it has content
                            if modified_last_line.strip():
                                lines[-1] = modified_last_line
                                diff_content = "\n".join(lines[1:])
                            else:
                                diff_content = "\n".join(lines[1:-1])
                            logger.info(
                                f"Removed code fences with partial last line for file: {file_path}"
                            )

                # Log the content after processing - first 100 chars
                logger.debug(
                    f"Write operation content preview (after processing): {diff_content[:100]}..."
                )

                # Write operator returns a structured response with reply and error fields
                result = run_write_operator(file_path, diff_content)
                execution_results = result

                # If the operator reported an error, capture it
                if result.get("error"):
                    execution_error = result["error"]
                    logger.error(
                        f"Write operation error for file {file_path}: {execution_error}"
                    )

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

