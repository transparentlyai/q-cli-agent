import re
from typing import Any, Dict

from q.core.config import config
from q.core.logging import get_logger
from q.operators.fetch import execute_fetch as run_fetch_operator
from q.operators.read import execute_read as run_read_operator
from q.operators.shell import run_shell as run_shell_operator
from q.operators.write import write_file as run_write_operator

logger = get_logger(__name__)


# Main operation tag pattern - handles standard format
OPERATION_TAG_PATTERN = re.compile(
    rf"<Q:{config.OPERATION_MARKER}\s+(?P<attributes>.*?)\s*>(?P<content>.*?)</Q:{config.OPERATION_MARKER}>",  # type: ignore
    re.IGNORECASE | re.DOTALL,
)

# Fallback pattern with more flexible whitespace handling
OPERATION_TAG_PATTERN_FLEXIBLE = re.compile(
    rf"<\s*Q\s*:\s*{config.OPERATION_MARKER}\s+(?P<attributes>.*?)\s*>\s*(?P<content>.*?)\s*</\s*Q\s*:\s*{config.OPERATION_MARKER}\s*>",  # type: ignore
    re.IGNORECASE | re.DOTALL,
)

# Additional patterns for common closing tag errors
OPERATION_TAG_PATTERN_ALT_CLOSING = re.compile(
    rf"<Q:{config.OPERATION_MARKER}\s+(?P<attributes>.*?)\s*>(?P<content>.*?)</Q>",  # Missing OPERATION_MARKER in closing tag
    re.IGNORECASE | re.DOTALL,
)

# More robust attribute patterns to handle different quoting styles
ATTRIBUTE_PATTERN_DOUBLE = re.compile(r'(\w+)\s*=\s*"(.*?)"')  # Double quotes
ATTRIBUTE_PATTERN_SINGLE = re.compile(r"(\w+)\s*=\s*'(.*?)'")  # Single quotes
ATTRIBUTE_PATTERN_NONE = re.compile(r'(\w+)\s*=\s*([^\s"\']+)')  # No quotes


def parse_attributes(attr_string: str) -> Dict[str, Any]:
    """Parses the attribute string from the operation tag."""
    attributes = {}
    
    # Try all attribute patterns in sequence
    for pattern in [ATTRIBUTE_PATTERN_DOUBLE, ATTRIBUTE_PATTERN_SINGLE, ATTRIBUTE_PATTERN_NONE]:
        for match in pattern.finditer(attr_string):
            key = match.group(1).lower()
            value = match.group(2)
            
            # Only add if key is not already in attributes (prioritize patterns in order)
            if key not in attributes:
                attributes[key] = value
                
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
    # Try standard pattern first
    match = OPERATION_TAG_PATTERN.search(text)
    
    # If no match, try the flexible pattern
    if not match:
        match = OPERATION_TAG_PATTERN_FLEXIBLE.search(text)
        if match:
            logger.info("Found operation using flexible pattern matching")
    
    # If still no match, try the alternate closing tag pattern
    if not match:
        match = OPERATION_TAG_PATTERN_ALT_CLOSING.search(text)
        if match:
            logger.info("Found operation using alternate closing tag pattern")
    
    # If still no match, check if there's evidence of an operation tag that didn't match our patterns
    if not match:
        # Check for evidence of operation tags that our standard patterns didn't catch
        if ("<Q:" in text or "<q:" in text.lower()) and ("</Q:" in text or "</q:" in text.lower()):
            logger.warning("Standard patterns failed but operation tag markers detected - trying aggressive fallback")
            # Try more aggressive parsing as a last resort
            return extract_operation_raw(text)
        
        # No evidence of operation tags
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

    operation_details = {
        **attributes,  # Includes 'type' and any other attributes
        "content": content,
    }
    logger.debug(f"Extracted operation: {operation_details}")
    return {"operation": operation_details, "text": cleaned_text, "error": ""}


def extract_operation_raw(text: str) -> Dict[str, Any]:
    """
    A more aggressive fallback parser for operation tags that tries harder to find potential operations
    when the standard parser fails.
    
    This is used internally by extract_operation when standard patterns fail but there's evidence
    of operation tags in the text.
    
    Args:
        text: The input string potentially containing an operation tag.
        
    Returns:
        Same structure as extract_operation.
    """
    # Look for any text that might be an operation tag with a very lenient pattern
    raw_pattern = re.compile(
        r"<\s*[qQ][^>]*?(?:operation|OPERATION)[^>]*?>(.+?)</\s*[qQ][^>]*?(?:operation|OPERATION)[^>]*?>",
        re.DOTALL,
    )
    
    match = raw_pattern.search(text)
    if not match:
        return {"operation": None, "text": text, "error": ""}
        
    # We found something that looks like an operation tag
    content_with_potential_attributes = match.group(1).strip()
    
    # Try to extract a type from what looks like attributes
    type_pattern = re.compile(r"type\s*=\s*[\"']?(\w+)[\"']?", re.IGNORECASE)
    type_match = type_pattern.search(text)
    
    operation_type = type_match.group(1).lower() if type_match else None
    
    # If we can't determine the type, try to infer it from the content
    if not operation_type:
        if "http://" in content_with_potential_attributes or "https://" in content_with_potential_attributes:
            operation_type = "fetch"
        elif "/" in content_with_potential_attributes and not content_with_potential_attributes.startswith(("/", "$", "sudo")):
            operation_type = "read"
        else:
            # Default to shell as a last resort
            operation_type = "shell"
            
    # Extract potential content
    # For a shell command, it's usually just the text after the type=
    if operation_type == "shell":
        # Try to find content after type="shell"
        content_pattern = re.compile(r"type\s*=\s*[\"']?shell[\"']?\s*>(.+?)</", re.DOTALL | re.IGNORECASE)
        content_match = content_pattern.search(text)
        content = content_match.group(1).strip() if content_match else content_with_potential_attributes
    # For fetch, look for a URL
    elif operation_type == "fetch":
        url_pattern = re.compile(r"(https?://\S+)")
        url_match = url_pattern.search(content_with_potential_attributes)
        content = url_match.group(1) if url_match else content_with_potential_attributes
    # For read, any file path like string
    elif operation_type == "read":
        # Simple pattern for something that looks like a file path
        path_pattern = re.compile(r"([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)")
        path_match = path_pattern.search(content_with_potential_attributes)
        content = path_match.group(1) if path_match else content_with_potential_attributes
    # For write, try to find path attribute and content
    elif operation_type == "write":
        # Try to extract path attribute
        path_pattern = re.compile(r"path\s*=\s*[\"']?([^\"'>\s]+)[\"']?", re.IGNORECASE)
        path_match = path_pattern.search(text)
        path = path_match.group(1) if path_match else None
        
        # Extract content after all attributes
        if path:
            # For write operations with path, set up the proper structure
            return {
                "operation": {
                    "type": "write",
                    "path": path,
                    "content": content_with_potential_attributes,
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
        
    # Build the operation details
    if operation_type and content:
        operation_details = {
            "type": operation_type,
            "content": content,
            # Flag that this was parsed with the fallback parser
            "_aggressive_fallback": True 
        }
        logger.warning(f"Extracted operation using aggressive fallback: {operation_type}")
        return {
            "operation": operation_details,
            "text": text.replace(match.group(0), "") + "\n\n[yellow]Note: Operation tag was malformed but Q attempted to recover it. Please verify the results.[/yellow]",
            "error": "",
        }
        
    return {"operation": None, "text": text, "error": "Failed to extract operation details in fallback parser"}


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
