"""
Fetch operator for fetching content from URLs.
"""

import asyncio
from typing import Any, Dict, Optional, Union

import httpx

from q.cli.approvals import request_approval
from q.cli.qconsole import show_error, show_spinner, show_success, show_warning
from q.core.constants import (
    OPEARION_SPINNER_COMMAND_COLOR,
    OPEARION_SPINNER_MESSAGE_COLOR,
)
from q.core.logging import get_logger

logger = get_logger(__name__)


async def fetch_url_async(
    url: str,
    method: str = "GET",
    timeout: int = 10,
    follow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Union[Dict[str, Any], str]] = None,
    json: Optional[Any] = None,
) -> Optional[httpx.Response]:
    """
    Fetches a URL using the httpx library (asynchronous).

    Args:
        url: The URL to fetch.
        method: HTTP method (GET, POST, PUT, DELETE, etc.). Defaults to 'GET'.
        timeout: Request timeout in seconds. Defaults to 10.
        follow_redirects: Follow HTTP redirects. Defaults to True.
        headers: Dictionary of HTTP headers.
        params: Dictionary of URL parameters for GET requests.
        data: Dictionary or bytes/string for POST/PUT request body.
        json: JSON payload for POST/PUT request body.

    Returns:
        An httpx.Response object if successful, None otherwise.
    """
    try:
        # Using an async client ensures connection pooling
        async with httpx.AsyncClient(
            follow_redirects=follow_redirects, http2=False
        ) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                data=data,  # type: ignore
                json=json,
                timeout=timeout,
            )
            # Raise an HTTPStatusError for bad status codes (4xx or 5xx)
            response.raise_for_status()
            logger.debug(
                f"Successfully fetched {url} with status {response.status_code} (HTTP/{response.http_version})"
            )
            return response
    except httpx.RequestError as e:
        logger.error(f"Error fetching {e.request.url!r}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred for {url}: {e}")
        return None


def fetch_url_sync(
    url: str,
    method: str = "GET",
    timeout: int = 10,
    follow_redirects: bool = True,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Union[Dict[str, Any], str]] = None,
    json: Optional[Any] = None,
) -> Optional[httpx.Response]:
    """
    Fetches a URL using the httpx library (synchronous).

    Args:
        url: The URL to fetch.
        method: HTTP method (GET, POST, PUT, DELETE, etc.). Defaults to 'GET'.
        timeout: Request timeout in seconds. Defaults to 10.
        follow_redirects: Follow HTTP redirects. Defaults to True.
        headers: Dictionary of HTTP headers.
        params: Dictionary of URL parameters for GET requests.
        data: Dictionary or bytes/string for POST/PUT request body.
        json: JSON payload for POST/PUT request body.

    Returns:
        An httpx.Response object if successful, None otherwise.
    """
    try:
        # Using a client ensures connection pooling
        with httpx.Client(follow_redirects=follow_redirects, http2=False) as client:
            response = client.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                data=data,
                json=json,
                timeout=timeout,
            )
            # Raise an HTTPStatusError for bad status codes (4xx or 5xx)
            response.raise_for_status()
            logger.debug(
                f"Successfully fetched {url} with status {response.status_code} (HTTP/{response.http_version})"
            )
            return response
    except httpx.RequestError as e:
        logger.error(f"Error fetching {e.request.url!r}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred for {url}: {e}")
        return None


def execute_fetch(url: str) -> Dict[str, Any]:
    """
    Fetches content from a URL after requesting approval.

    Args:
        url: The URL to fetch.

    Returns:
        A dictionary containing:
        - 'reply' (str): A message indicating success or failure
        - 'content' (str or None): The fetched content when successful, None on error
        - 'error' (str or None): Error message if an error occurred, None otherwise
    """
    result = {
        "reply": f"Here is the content from {url}:",
        "content": None,
        "error": None,
    }

    logger.debug(f"Received request to fetch URL: {url}")

    # Check approval status
    approval_status = check_approval(url, result)
    if approval_status is not True:
        return approval_status

    try:
        # Show spinner while fetching
        with show_spinner(
            f"[{OPEARION_SPINNER_MESSAGE_COLOR}]Fetching URL[/] [{OPEARION_SPINNER_COMMAND_COLOR}]{url}[/]..."
        ):
            # Use synchronous fetch for simplicity
            response = fetch_url_sync(url)

            if response is None:
                return handle_error(
                    result,
                    f"Failed to fetch URL: {url}",
                    f"STOP: Failed to fetch URL: {url}",
                    "error",
                )

            # Get content type from headers
            content_type = response.headers.get("content-type", "")

            # Process response based on content type
            if "application/json" in content_type:
                try:
                    content = response.json()
                    result["content"] = content
                    logger.debug(f"Successfully fetched JSON from {url}")
                except Exception as e:
                    return handle_error(
                        result,
                        f"Error parsing JSON response: {e}",
                        f"STOP: Error parsing JSON response: {e}",
                        "error",
                        exc_info=True,
                    )
            else:
                # Default to text for all other content types
                content = response.text
                result["content"] = content
                logger.debug(
                    f"Successfully fetched content from {url} ({len(content)} chars)"
                )

        show_success(f"Successfully fetched URL: {url}")
        return result

    except Exception as e:
        show_error(f"Error fetching URL: {e}")
        return handle_error(
            result,
            f"An unexpected error occurred: {e}",
            f"STOP: An unexpected error occurred: {e}",
            "error",
            exc_info=True,
        )


def check_approval(url: str, result: Dict[str, Any]) -> Any:
    """Check if the fetch operation is approved."""
    approval_status = request_approval(operation_type="fetch", operation_content=url)

    if isinstance(approval_status, dict) and "reason" in approval_status:
        reason = approval_status["reason"]
        show_warning(f"Fetch operation denied: {reason}")
        logger.warning(f"Fetch operation denied: {reason}")
        result["reply"] = f"STOP: URL fetch operation failed"
        result["error"] = reason
        result["content"] = None
        return result
    elif approval_status == "cancelled":
        show_warning(f"Fetch operation cancelled: {url}")
        logger.warning(f"Fetch operation cancelled by user for URL: '{url}'")
        result["reply"] = f"STOP: URL fetch operation cancelled"
        result["error"] = f"Fetch operation cancelled by user for URL '{url}'."
        result["content"] = None
        return result
    elif approval_status is not True:
        show_error(f"Unexpected approval status: {approval_status}")
        logger.warning(
            f"Unexpected approval status '{approval_status}' for fetch operation on '{url}'. Denying."
        )
        result["reply"] = f"STOP: URL fetch operation failed"
        result["error"] = f"Unexpected approval status '{approval_status}'."
        result["content"] = None
        return result

    # Approval granted
    logger.debug(f"Approval granted for fetching URL: {url}")
    return True


def handle_error(
    result: Dict[str, Any],
    error_msg: str,
    reply_msg: str,
    log_level: str = "error",
    exc_info: bool = False,
) -> Dict[str, Any]:
    """Handle errors consistently and update the result dictionary."""
    log_func = getattr(logger, log_level)
    log_func(error_msg, exc_info=exc_info)

    result["reply"] = reply_msg
    result["error"] = error_msg
    result["content"] = None
    return result