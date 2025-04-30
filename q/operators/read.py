"""
Read operator for reading files.
"""

import base64
import functools
from pathlib import Path
from typing import Any, Dict

import magic

from q.cli.approvals import request_approval  # Q: no-change
from q.cli.qconsole import show_error, show_spinner, show_success, show_warning
from q.core.constants import (
    OPEARION_SPINNER_COMMAND_COLOR,
    OPEARION_SPINNER_MESSAGE_COLOR,
)
from q.core.logging import get_logger

logger = get_logger(__name__)


def execute_read(
    file_path_str: str, from_line: int | None = None, to_line: int | None = None
) -> Dict[str, Any]:
    """
    Reads a file and returns its content. Supports only:
    - Text files: returned as strings
    - PDF files: text extracted and converted to markdown
    - Image files: base64 encoded
    All other file types are rejected.

    Args:
        file_path_str: The path to the file to read (relative to CWD or absolute).
        from_line: Optional starting line number (inclusive, 1-indexed). If None, starts from the first line.
        to_line: Optional ending line number (inclusive, 1-indexed). If None, reads to the end of the file.

    Returns:
        A dictionary containing:
        - 'reply' (str): A message indicating success or failure
        - 'attachment' (dict or None): Contains mime_type, content, and encoding information when successful, None on error
        - 'error' (str or None): Error message if an error occurred, None otherwise
    """
    result = {
        "reply": f"Here is the content of {file_path_str}:",
        "attachment": {"mime_type": "", "content": "", "encoding": None},
        "error": None,
    }

    logger.debug(f"Received request to read file: {file_path_str}")

    # Check approval status
    approval_status = check_approval(file_path_str, result)
    if approval_status is not True:
        return approval_status

    try:
        # Show spinner while resolving and detecting file type
        with show_spinner(
            f"[{OPEARION_SPINNER_MESSAGE_COLOR}]Reading file[/] [{OPEARION_SPINNER_COMMAND_COLOR}]{file_path_str}[/]..."
        ):
            # Resolve the path after approval, relative to CWD if not absolute
            file_path = Path(file_path_str).resolve(strict=True)
            logger.debug(f"Resolved path to read: {file_path}")

            # Detect file type and process accordingly
            mime_type = detect_mime_type(file_path)
            logger.debug(f"Detected MIME type: {mime_type}")

            # Log line range if specified
            if from_line is not None or to_line is not None:
                range_info = []
                if from_line is not None:
                    range_info.append(f"from={from_line}")
                if to_line is not None:
                    range_info.append(f"to={to_line}")
                logger.debug(f"Reading with line range: {', '.join(range_info)}")

        # Process file based on mime type
        return process_file_by_type(
            file_path, mime_type, result, file_path_str, from_line, to_line
        )

    except FileNotFoundError:
        show_error(f"File not found: {file_path_str}")
        return handle_error(
            result,
            f"File not found at '{file_path_str}'",
            f"File not found at '{file_path_str}'",
            "debug",
        )
    except PermissionError:
        show_error(f"Permission denied: {file_path_str}")
        return handle_error(
            result,
            f"Permission denied for path '{file_path_str}'",
            f"STOP: Permission denied for path '{file_path_str}'",
            "debug",
        )
    except Exception as e:
        show_error(f"Error reading file: {e}")
        return handle_error(
            result,
            f"An unexpected error occurred: {e}",
            f"STOP: An unexpected error occurred: {e}",
            "debug",
            exc_info=True,
        )


def check_approval(file_path_str: str, result: Dict[str, Any]) -> Any:
    """Check if the read operation is approved."""
    approval_status = request_approval(
        operation_type="read", operation_content=file_path_str
    )

    if isinstance(approval_status, dict) and "reason" in approval_status:
        reason = approval_status["reason"]
        show_warning(f"Read operation denied: {reason}")
        logger.warning(f"Read operation denied: {reason}")
        result["reply"] = f"File read operation failed"
        result["error"] = reason
        result["attachment"] = None
        return result
    elif approval_status == "cancelled":
        show_warning(f"Read operation cancelled: {file_path_str}")
        logger.warning(f"Read operation cancelled by user for path: '{file_path_str}'")
        result["reply"] = f"STOP: File read operation cancelled"
        result["error"] = (
            f"Read operation cancelled by user for path '{file_path_str}'."
        )
        result["attachment"] = None
        return result
    elif approval_status is not True:
        show_error(f"Unexpected approval status: {approval_status}")
        logger.debug(
            f"Unexpected approval status '{approval_status}' for read operation on '{file_path_str}'. Denying."
        )
        result["reply"] = f"STOP: File read operation failed"
        result["error"] = f"Unexpected approval status '{approval_status}'."
        result["attachment"] = None
        return result

    # Approval granted
    logger.debug(f"Approval granted for reading file: {file_path_str}")
    return True


def detect_mime_type(file_path: Path) -> str:
    """Detect the MIME type of a file."""
    return magic.Magic(mime=True).from_file(str(file_path))


def process_file_by_type(
    file_path: Path,
    mime_type: str,
    result: Dict[str, Any],
    file_path_str: str,
    from_line: int | None = None,
    to_line: int | None = None,
) -> Dict[str, Any]:
    """Process a file based on its MIME type."""
    # Handle text files
    if is_text_file(mime_type):
        return read_text_file(file_path, result, file_path_str, from_line, to_line)
    # Handle PDF files - line parameters don't apply to PDFs
    elif mime_type == "application/pdf":
        if from_line is not None or to_line is not None:
            logger.debug("Line range parameters ignored for PDF files")
        return read_pdf_file(file_path, result, file_path_str)
    # Handle image files - line parameters don't apply to images
    elif mime_type.startswith("image/"):
        if from_line is not None or to_line is not None:
            logger.debug("Line range parameters ignored for image files")
        return read_image_file(file_path, mime_type, result, file_path_str)
    # Reject all other file types
    else:
        show_warning(f"Unsupported file type: {mime_type}")
        return handle_error(
            result,
            f"Unsupported file type: {mime_type}",
            f"STOP: Unsupported file type: {mime_type}",
            "debug",
        )


def is_text_file(mime_type: str) -> bool:
    """Check if the MIME type corresponds to a text file."""
    text_mime_types = [
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-python",
        "application/x-sh",
        "application/x-yaml",
        "application/toml",
        "application/x-perl",
        "application/x-ruby",
        "application/x-php",
        "application/csv",
        "application/x-tex",
        "application/x-shellscript",
        "application/x-troff-man",
        "application/x-msdos-program",  # .bat files
        "application/xhtml+xml",
    ]
    return mime_type.startswith("text/") or mime_type in text_mime_types


def read_text_file(
    file_path: Path,
    result: Dict[str, Any],
    file_path_str: str,
    from_line: int | None = None,
    to_line: int | None = None,
) -> Dict[str, Any]:
    """
    Read a text file and update the result dictionary.

    Optionally reads only a specific range of lines if from_line and/or to_line are provided.
    """
    try:
        with show_spinner(
            f"[{OPEARION_SPINNER_MESSAGE_COLOR}]Reading text file[/] [{OPEARION_SPINNER_COMMAND_COLOR}]{file_path_str}...[/]"
        ):
            # If we need to read specific lines
            if from_line is not None or to_line is not None:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                # Adjust line indices (convert from 1-indexed to 0-indexed)
                start_idx = (from_line - 1) if from_line is not None else 0
                end_idx = to_line if to_line is not None else len(lines)

                # Validate indices
                if start_idx < 0:
                    start_idx = 0
                if end_idx > len(lines):
                    end_idx = len(lines)

                # Join only the requested lines
                content = "".join(lines[start_idx:end_idx])

                # Update the reply message to indicate partial content
                line_info = ""
                if from_line is not None and to_line is not None:
                    line_info = f" (lines {from_line}-{to_line})"
                elif from_line is not None:
                    line_info = f" (from line {from_line})"
                elif to_line is not None:
                    line_info = f" (up to line {to_line})"

                result["reply"] = (
                    f"Here is the partial content of {file_path_str}{line_info}:"
                )
            else:
                # Read the entire file
                content = file_path.read_text(encoding="utf-8")

            result["reply"] += f"\n\n{content}"
            result["attachment"] = {
                "mime_type": "text/plain",
                "content": content,
                "encoding": None
            }
            logger.debug(
                f"Read text content from '{file_path_str}' ({len(content)} chars)"
            )

        # Update success message to include line information
        success_message = f"Successfully read text file: {file_path_str}"
        if from_line is not None or to_line is not None:
            line_range = []
            if from_line is not None:
                line_range.append(f"from line {from_line}")
            if to_line is not None:
                line_range.append(f"to line {to_line}")
            success_message += f" ({' '.join(line_range)})"

        show_success(success_message)
        return result
    except UnicodeDecodeError:
        show_error(f"Error decoding text file with UTF-8 encoding: {file_path_str}")
        return handle_error(
            result,
            "Error decoding text file with UTF-8 encoding",
            "STOP: Error decoding text file with UTF-8 encoding",
            "debug",
        )
    except Exception as e:
        show_error(f"Error reading file: {e}")
        return handle_error(
            result,
            f"Error reading file: {e}",
            f"STOP: Error reading file: {e}",
            "debug",
            exc_info=True,
        )


def read_pdf_file(
    file_path: Path, result: Dict[str, Any], file_path_str: str
) -> Dict[str, Any]:
    """Read a PDF file, convert to markdown, and update the result dictionary."""
    try:
        with show_spinner(
            f"[{OPEARION_SPINNER_MESSAGE_COLOR}]Converting PDF to markdown:[/] [{OPEARION_SPINNER_COMMAND_COLOR}]{file_path_str}...[/]"
        ):
            markdown_content = convert_pdf_to_markdown(str(file_path))
            result["reply"] += f"\n\n{markdown_content}"
            result["attachment"] = {
                "mime_type": "text/markdown",
                "content": markdown_content,
                "encoding": None
            }
            logger.debug(
                f"Converted PDF to markdown '{file_path_str}' ({len(markdown_content)} chars)"
            )

        show_success(f"Successfully converted PDF: {file_path_str}")
        return result
    except Exception as e:
        show_error(f"Error converting PDF: {e}")
        return handle_error(
            result,
            f"Error converting PDF to markdown: {e}",
            f"STOP: Error converting PDF to markdown: {e}",
            "debug",
            exc_info=True,
        )


def read_image_file(
    file_path: Path, mime_type: str, result: Dict[str, Any], file_path_str: str
) -> Dict[str, Any]:
    """Read an image file, encode it, and update the result dictionary."""
    try:
        binary_content = file_path.read_bytes()
        encoded_content = base64.b64encode(binary_content).decode("utf-8")

        result["attachment"]["content"] = encoded_content
        result["attachment"]["mime_type"] = mime_type
        result["attachment"]["encoding"] = "base64"
        logger.debug(
            f"Read and base64 encoded image from '{file_path_str}' ({len(encoded_content)} chars)"
        )

        show_success(f"Successfully processed image: {file_path_str}")
        return result
    except Exception as e:
        show_error(f"Error processing image: {e}")
        return handle_error(
            result,
            f"Error reading image file: {e}",
            f"STOP: Error reading image file: {e}",
            "debug",
            exc_info=True,
        )


def handle_error(
    result: Dict[str, Any],
    error_msg: str,
    reply_msg: str,
    log_level: str = "debug",
    exc_info: bool = False,
) -> Dict[str, Any]:
    """Handle errors consistently and update the result dictionary."""
    log_func = getattr(logger, log_level)
    log_func(error_msg, exc_info=exc_info)

    result["reply"] = reply_msg
    result["error"] = error_msg
    result["attachment"] = None
    return result


# Lazy-load the pymupdf4llm library only when needed
@functools.lru_cache(maxsize=1)
def get_pdf_converter():
    """Lazy-load the PDF conversion library."""
    try:
        import pymupdf4llm

        return pymupdf4llm
    except ImportError as e:
        logger.error(f"Failed to import pymupdf4llm: {e}", exc_info=True)
        raise ImportError(f"PDF conversion requires pymupdf4llm library: {e}")


def convert_pdf_to_markdown(file_path: str) -> str:
    """
    Convert a PDF file to markdown using pymupdf4llm.

    Args:
        file_path: Path to the PDF file

    Returns:
        Markdown content as a string
    """
    logger.debug(f"Converting PDF to markdown using pymupdf4llm: {file_path}")

    # Get the PDF converter (lazy-loaded)
    pdf_converter = get_pdf_converter()

    # Convert the PDF to markdown
    try:
        markdown_content = pdf_converter.to_markdown(file_path)
        return markdown_content
    except Exception as e:
        logger.debug(f"Error in PDF conversion: {e}", exc_info=True)
        raise

