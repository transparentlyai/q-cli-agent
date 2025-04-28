# pyright: basic, reportAttributeAccessIssue=false

import json
import os
import time
from collections import deque
from typing import Any, Dict, List, Optional

# Import retry directly - it's lightweight
from retry import retry

from q.cli.qconsole import q_console
from q.core.config import config
from q.core.constants import (
    ANTHROPIC_DEFAULT_MODEL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROVIDER,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TEMPERATURE,
    GROQ_DEFAULT_MODEL,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_BACKOFF_FACTOR,
    LLM_RETRY_INITIAL_DELAY,
    LLM_RETRY_JITTER_MAX,
    LLM_RETRY_JITTER_MIN,
    OPENAI_DEFAULT_MODEL,
    VERTEXAI_DEFAULT_LOCATION,
    VERTEXAI_DEFAULT_MODEL,
)
from q.core.logging import get_logger

# Initialize logger for this module
logger = get_logger("llm")

# Lazy imports - don't import litellm or other heavy modules until needed
_litellm = None
_llm_helpers = None
_mcp_client = None

def _get_litellm():
    """Lazy import for litellm to avoid loading it at startup."""
    global _litellm
    if _litellm is None:
        logger.debug("Lazy loading litellm module")
        import litellm
        _litellm = litellm
    return _litellm

def _get_llm_helpers():
    """Lazy import for llm_helpers to avoid loading it at startup."""
    global _llm_helpers
    if _llm_helpers is None:
        logger.debug("Lazy loading llm_helpers module")
        from q.utils import llm_helpers
        _llm_helpers = llm_helpers
    return _llm_helpers

def _get_mcp_client():
    """Lazy import for MCP client to avoid loading it at startup."""
    global _mcp_client
    if _mcp_client is None:
        logger.debug("Lazy loading MCP client module")
        try:
            from q.code import mcp
            _mcp_client = mcp
            logger.debug("MCP client module loaded successfully")
        except ImportError:
            logger.warning("MCP client module not available")
            _mcp_client = None
    return _mcp_client


class TokenRateLimiter:
    """
    A class to handle token rate limiting for LLM API calls.

    Tracks token usage over time and enforces rate limits by adding
    appropriate delays when necessary.
    """

    def __init__(self, tokens_per_min: int):
        """
        Initialize the token rate limiter.

        Args:
            tokens_per_min: Maximum number of tokens allowed per minute
        """
        self.tokens_per_min = tokens_per_min
        self.token_usage_history = deque()
        self.window_size = 60  # 60 seconds (1 minute)

    def update_tokens_per_min(self, tokens_per_min: int):
        """
        Update the tokens per minute limit.

        Args:
            tokens_per_min: New maximum number of tokens allowed per minute
        """
        self.tokens_per_min = tokens_per_min

    def add_token_usage(self, token_count: int, timestamp: Optional[float] = None):
        """
        Add a token usage record to the history.

        Args:
            token_count: Number of tokens used
            timestamp: Optional timestamp (defaults to current time)
        """
        if timestamp is None:
            timestamp = time.time()

        self.token_usage_history.append((timestamp, token_count))
        self._clean_old_usage()

    def _clean_old_usage(self):
        """Remove token usage records older than the window size."""
        current_time = time.time()
        cutoff_time = current_time - self.window_size

        while self.token_usage_history and self.token_usage_history[0][0] < cutoff_time:
            self.token_usage_history.popleft()

    def get_current_usage(self) -> int:
        """
        Get the total token usage within the current window.

        Returns:
            Total token count in the current window
        """
        self._clean_old_usage()
        return sum(count for _, count in self.token_usage_history)

    def wait_if_needed(self, upcoming_token_count: int) -> float:
        """
        Wait if adding the upcoming tokens would exceed the rate limit.

        Args:
            upcoming_token_count: Number of tokens in the upcoming request

        Returns:
            The amount of time waited in seconds
        """
        self._clean_old_usage()
        current_usage = self.get_current_usage()

        # If adding the upcoming tokens would exceed the limit
        if current_usage + upcoming_token_count > self.tokens_per_min:
            # Calculate how many tokens we need to wait for
            tokens_to_wait_for = (
                current_usage + upcoming_token_count - self.tokens_per_min
            )

            # If we have usage history, we need to wait for enough tokens to expire
            if self.token_usage_history:
                current_time = time.time()
                wait_time = 0

                # Sort records by timestamp (oldest first)
                sorted_records = sorted(self.token_usage_history, key=lambda x: x[0])
                tokens_freed = 0

                # Calculate how long to wait for enough tokens to be freed
                for timestamp, token_count in sorted_records:
                    # Calculate when this record will expire
                    expiry_time = timestamp + self.window_size
                    record_wait_time = max(0, expiry_time - current_time)

                    # Add these tokens to our running total
                    tokens_freed += token_count

                    # If we've freed enough tokens, this is our wait time
                    if tokens_freed >= tokens_to_wait_for:
                        wait_time = record_wait_time
                        break

                if wait_time > 0:
                    logger.inspect(  # type: ignore
                        f"Rate limit approaching: Waiting {wait_time:.2f}s for {tokens_to_wait_for} tokens to free up"
                    )
                    time.sleep(wait_time)
                    # After waiting, clean up old usage again
                    self._clean_old_usage()
                    return wait_time

            # If we don't have enough history or couldn't calculate a wait time,
            # use a simple proportional wait time based on the window size
            wait_time = (tokens_to_wait_for / self.tokens_per_min) * self.window_size
            logger.inspect(  # type: ignore
                f"Rate limit approaching: Using fallback wait of {wait_time:.2f}s for {tokens_to_wait_for} tokens"
            )
            time.sleep(wait_time)
            self._clean_old_usage()
            return wait_time

        return 0.0


class LLMConversation:
    """
    A class to handle conversations with various LLM providers through LiteLLM.

    Supports VertexAI, Anthropic, OpenAI, and Groq providers.
    Configuration is loaded from Q config, with optional overrides via init parameters.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        tokens_per_min: Optional[int] = None,
        **kwargs,
    ):
        """
        Initialize the LLM conversation handler.

        Args:
            model: The specific model to use (e.g., "gpt-4", "claude-3-opus-20240229")
            provider: The LLM provider (vertexai, anthropic, openai, groq)
            api_key: The API key for the provider
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            system_prompt: System prompt to use for the conversation
            tokens_per_min: Maximum tokens per minute for rate limiting
            **kwargs: Additional provider-specific parameters
        """
        # Load configuration from config with fallbacks
        self.provider = provider or getattr(config, "PROVIDER", DEFAULT_PROVIDER)
        self.provider = self.provider.lower()

        logger.debug(f"Initializing LLMConversation with provider: {self.provider}")

        # Lazy load llm_helpers
        llm_helpers = _get_llm_helpers()

        # Set up provider-specific configurations
        self._setup_provider_config()

        # Override with explicitly provided parameters
        if api_key:
            self.api_key = api_key
        if model:
            self.model = model

        # Set conversation parameters - now provider-specific
        self.temperature = temperature or self._get_provider_config(
            "TEMPERATURE", DEFAULT_TEMPERATURE
        )
        self.max_tokens = max_tokens or self._get_provider_config(
            "MAX_TOKENS", DEFAULT_MAX_TOKENS
        )
        self.system_prompt = system_prompt or getattr(
            config, "SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT
        )

        # Set up token rate limiting
        self.tokens_per_min = tokens_per_min or self._get_provider_config(
            "TOKENS_PER_MIN", llm_helpers.get_default_tokens_per_min(self.provider)
        )
        self.rate_limiter = TokenRateLimiter(self.tokens_per_min)

        # Log provider-specific settings for debugging
        logger.debug(f"Provider: {self.provider}")
        logger.debug(f"Model: {self.model}")
        logger.debug(f"Temperature: {self.temperature}")
        logger.debug(f"Max tokens: {self.max_tokens}")
        logger.debug(f"Tokens per minute: {self.tokens_per_min}")

        # Store additional parameters
        self.additional_params = kwargs

        # Initialize conversation history
        self.messages: List[Dict[str, Any]] = [] # Allow Any for tool_calls etc.
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def _get_provider_config(self, param_name: str, default_value: Any) -> Any:
        """
        Get a provider-specific configuration parameter.

        Args:
            param_name: The parameter name (without provider prefix)
            default_value: Default value if not found

        Returns:
            The provider-specific parameter value or default
        """
        # Try provider-specific parameter first (e.g., ANTHROPIC_MAX_TOKENS)
        provider_param = f"{self.provider.upper()}_{param_name}"
        value = getattr(
            config, provider_param, getattr(config, param_name, default_value)
        )
        logger.debug(
            f"Config parameter {param_name}: {value} (from {provider_param if hasattr(config, provider_param) else param_name if hasattr(config, param_name) else 'default'})"
        )
        return value

    def _setup_provider_config(self):
        """Set up provider-specific configuration based on the selected provider."""
        # Lazy load llm_helpers
        llm_helpers = _get_llm_helpers()

        if self.provider == "vertexai":
            # Handle Vertex AI credentials
            self.model = getattr(config, "VERTEXAI_MODEL", VERTEXAI_DEFAULT_MODEL)
            self.project_id = getattr(
                config, "VERTEXAI_PROJECT", os.environ.get("VERTEXAI_PROJECT", "")
            )
            self.location = getattr(
                config,
                "VERTEXAI_LOCATION",
                os.environ.get("VERTEXAI_LOCATION", VERTEXAI_DEFAULT_LOCATION),
            )

            # Check for credentials file path
            credentials_file = getattr(
                config,
                "VERTEXAI_API_KEY",
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            )

            # Load credentials if available
            self.vertex_credentials = llm_helpers.load_vertexai_credentials(credentials_file)

            # Set environment variables for LiteLLM
            llm_helpers.setup_vertexai_environment(self.project_id, self.location)

        elif self.provider == "anthropic":
            self.api_key = getattr(
                config, "ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")
            )
            # Use a valid model name from the list of supported models
            self.model = getattr(config, "ANTHROPIC_MODEL", ANTHROPIC_DEFAULT_MODEL)

            # Remove 'anthropic/' prefix if present in the model name
            if self.model.startswith("anthropic/"):
                self.model = self.model[len("anthropic/") :]

            # Set environment variables for LiteLLM
            llm_helpers.setup_provider_environment(self.provider, self.api_key)

        elif self.provider == "groq":
            self.api_key = getattr(
                config, "GROQ_API_KEY", os.environ.get("GROQ_API_KEY", "")
            )
            self.model = getattr(config, "GROQ_MODEL", GROQ_DEFAULT_MODEL)

            # Set environment variables for LiteLLM
            llm_helpers.setup_provider_environment(self.provider, self.api_key)

        else:  # Default to OpenAI
            self.provider = "openai"
            self.api_key = getattr(
                config, "OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")
            )
            self.model = getattr(config, "OPENAI_MODEL", OPENAI_DEFAULT_MODEL)

            # Set environment variables for LiteLLM
            llm_helpers.setup_provider_environment(self.provider, self.api_key)

    def add_message(self, role: str, content: Any, **kwargs) -> None:
        """
        Add a message to the conversation history.

        Args:
            role: The role of the message sender ("user", "assistant", or "system", "tool")
            content: The content of the message (can be string or list for complex content)
            **kwargs: Additional fields for the message (e.g., tool_call_id, tool_calls)
        """
        message = {"role": role, "content": content}
        message.update(kwargs)
        self.messages.append(message)


    @retry(
        exceptions=Exception,
        tries=LLM_RETRY_ATTEMPTS,
        delay=LLM_RETRY_INITIAL_DELAY,
        backoff=LLM_RETRY_BACKOFF_FACTOR,
        jitter=(LLM_RETRY_JITTER_MIN, LLM_RETRY_JITTER_MAX),
        logger=logger,
    )
    def _execute_llm_call(self, params):
        """
        Execute the LLM API call with retry logic.
        Only retries on overloaded errors.

        Args:
            params: Parameters for the LLM completion call

        Returns:
            The LLM response
        """
        try:
            # Lazy load modules
            litellm = _get_litellm()
            llm_helpers = _get_llm_helpers()

            logger.debug("Executing LLM API call")
            # Avoid logging potentially large message history
            log_params = {k: v for k, v in params.items() if k != 'messages'}
            # Log message roles and content types for debugging structure
            if 'messages' in params:
                message_summary = [
                    f"{msg['role']}:{type(msg.get('content', ''))}"
                    for msg in params['messages']
                ]
                log_params['message_summary'] = message_summary[-5:] # Log last 5 messages summary
            logger.inspect(f"LLM parameters (summary): {json.dumps(log_params)}")


            # Count tokens in the request
            token_count = llm_helpers.count_tokens_in_messages(
                params["messages"],
                self.model,
                self.provider,
            )
            logger.debug(f"Request contains approximately {token_count} tokens")

            # Apply rate limiting if needed
            wait_time = self.rate_limiter.wait_if_needed(token_count)
            if wait_time > 0:
                logger.info(
                    f"Rate limiting applied: waited {wait_time:.2f}s to avoid exceeding {self.tokens_per_min} tokens/min limit"
                )
            # Parameters for LiteLLM retries
            if getattr(config, "LLM_IN_OUT", None):
                # Only print user messages for brevity
                if params["messages"][-1]["role"] == "user":
                    message_content = params["messages"][-1]["content"]
                    if isinstance(message_content, list): # Handle complex content
                         text_part = next((part['text'] for part in message_content if part['type'] == 'text'), '[Complex Content]')
                         q_console.print(f"[cyan]User: {text_part}[/]")
                    else:
                         q_console.print(f"[cyan]User: {message_content}[/]")


            ############ Execute the API call #############
            response = litellm.completion(**params)

            if getattr(config, "LLM_IN_OUT", None):
                 if response.choices and response.choices[0].message:
                     assistant_content = response.choices[0].message.content or "[No Content]"
                     tool_calls_info = ""
                     if response.choices[0].message.tool_calls:
                         tool_calls_info = f" (Tool Calls: {len(response.choices[0].message.tool_calls)})"
                     q_console.print(f"[red]Assistant: {assistant_content}{tool_calls_info}[/]")


            # Record token usage for rate limiting
            total_tokens = response.usage.total_tokens
            self.rate_limiter.add_token_usage(total_tokens)
            logger.debug(f"Added {total_tokens} tokens to rate limiter history")

            return response
        except Exception as e:
            # Only retry if it's an overloaded error
            if llm_helpers.is_overloaded_error(e):
                # Log the overloaded error
                logger.error(f"LLM service overloaded, will retry: {str(e)}")
                # Let the retry decorator handle this
                raise
            else:
                # For other errors, don't retry
                logger.error(f"Non-retryable error: {str(e)}")
                # Re-raise the original exception to preserve type and traceback
                raise e


    def _parse_schema(self, schema_str: str) -> Dict[str, Any]:
        """
        Parse a JSON schema string into a Python dictionary.

        Args:
            schema_str: JSON schema as a string

        Returns:
            Dictionary representation of the schema
        """
        try:
            if not schema_str:
                return {"type": "object", "properties": {}, "additionalProperties": True}

            schema = json.loads(schema_str)
            return schema
        except Exception as e:
            logger.warning(f"Error parsing schema: {str(e)}")
            return {"type": "object", "properties": {}, "additionalProperties": True}

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """
        Get available MCP tools for use with LLM.

        Returns:
            List of tool definitions in the format expected by LLMs
        """
        mcp_client = _get_mcp_client()
        if not mcp_client:
            logger.debug("MCP client not available, no tools will be used")
            return []

        try:
            # Get tools from all connected MCP servers
            result = mcp_client.mcp_list_tools()

            if result.get("status") != "success":
                logger.warning(f"Failed to get MCP tools: {result.get('error', 'Unknown error')}")
                return []

            tools = []
            tools_by_server = result.get("tools", {})

            for server_name, server_tools in tools_by_server.items():
                if isinstance(server_tools, dict) and "error" in server_tools:
                    logger.warning(f"Error getting tools from server '{server_name}': {server_tools['error']}")
                    continue

                for tool in server_tools:
                    tool_name = tool.get("name")
                    tool_description = tool.get("description", "")
                    tool_schema = tool.get("schema")

                    # Create a tool definition in the format expected by LLMs
                    # Use a provider-compatible naming convention (no colons)
                    safe_tool_name = f"{server_name}_{tool_name}".replace("-", "_")

                    # Parse the schema if available
                    parameters = self._parse_schema(tool_schema) if tool_schema else {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True
                    }

                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": safe_tool_name,
                            "description": f"[{server_name}] {tool_description}",
                            "parameters": parameters
                        }
                    }
                    tools.append(tool_def)

            logger.debug(f"Found {len(tools)} MCP tools")
            return tools

        except Exception as e:
            logger.error(f"Error getting MCP tools: {str(e)}")
            return []

    def _handle_tool_calls(self, response) -> bool:
        """
        Handle tool calls from the LLM response by executing them via MCP
        and adding the results to the conversation history.

        Args:
            response: The LLM response object

        Returns:
            True if tool calls were processed, False otherwise.
        """
        mcp_client = _get_mcp_client()
        if not mcp_client or not hasattr(response, 'choices') or not response.choices:
            return False

        choice = response.choices[0]
        if not hasattr(choice, 'message') or not hasattr(choice.message, 'tool_calls') or not choice.message.tool_calls:
            return False

        tool_calls = choice.message.tool_calls
        logger.debug(f"Found {len(tool_calls)} tool calls in LLM response")

        # Add the assistant message that requested the tool calls
        assistant_message = choice.message
        self.add_message(
            role="assistant",
            content=assistant_message.content, # Can be None
            tool_calls=[ # Store the raw tool_calls structure
                {"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ]
        )

        tool_results_to_add = []

        for tool_call in tool_calls:
            tool_id = tool_call.id
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                 logger.error(f"Failed to parse tool arguments for {tool_name}: {e}")
                 tool_results_to_add.append({
                     "tool_call_id": tool_id,
                     "role": "tool",
                     "content": f"Error: Failed to parse arguments: {e}"
                 })
                 continue


            # Parse the server name and actual tool name from the tool name
            parts = tool_name.split('_', 1)
            if len(parts) < 2:
                logger.warning(f"Invalid tool name format: {tool_name}, expected 'server_name_tool_name'")
                tool_results_to_add.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "content": f"Error: Invalid tool name format: {tool_name}, expected 'server_name_tool_name'"
                })
                continue

            server_name = parts[0]
            # The actual tool name as known by the MCP server (may contain hyphens)
            actual_tool_name = parts[1]

            logger.debug(f"Calling MCP tool '{actual_tool_name}' on server '{server_name}' with args: {tool_args}")

            try:
                # Call the tool via MCP
                result = mcp_client.mcp_call_tool(server_name, actual_tool_name, tool_args)

                if isinstance(result, dict) and "error" in result:
                    error_msg = result["error"]
                    logger.error(f"Error calling MCP tool '{actual_tool_name}': {error_msg}")
                    tool_results_to_add.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "content": f"Error: {error_msg}"
                    })
                else:
                    # Format the result as a tool response
                    # Ensure content is JSON serializable, default to string representation
                    content_to_send = result.get("content", result)
                    try:
                        json_content = json.dumps(content_to_send)
                    except TypeError:
                        logger.warning(f"Tool result for {actual_tool_name} is not JSON serializable, sending as string.")
                        json_content = str(content_to_send)

                    tool_results_to_add.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "content": json_content
                    })
            except Exception as e:
                logger.error(f"Exception calling MCP tool '{actual_tool_name}': {str(e)}")
                tool_results_to_add.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "content": f"Error: {str(e)}"
                })

        # Add all tool results to the conversation history
        for result in tool_results_to_add:
            self.add_message(
                role="tool",
                content=result["content"],
                tool_call_id=result["tool_call_id"]
            )

        return True # Indicate that tool calls were processed


    def send_message(
        self,
        message: str,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a message to the LLM and get a response, handling tool calls.

        Args:
            message: The message to send
            response_format: Optional format specification for structured responses
            tools: Optional tools configuration (e.g., for function calling or grounding)

        Returns:
            The LLM's final response text after handling any tool calls.
        """
        # Lazy load modules
        litellm = _get_litellm()
        llm_helpers = _get_llm_helpers()

        # Add user message to history
        self.add_message("user", message)
        logger.debug("Added user message to conversation history")

        # Prepare model name with provider prefix if needed
        model_name = llm_helpers.format_model_name(self.model, self.provider)
        logger.debug(f"Using model: {model_name}")

        # Prepare initial parameters for completion
        params = {
            "model": model_name,
            "messages": self.messages, # Start with current history
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.additional_params,
        }

        # Add Vertex AI specific parameters if using Vertex AI
        if self.provider == "vertexai":
            if hasattr(self, "project_id") and self.project_id:
                params["vertex_project"] = self.project_id
            if hasattr(self, "location") and self.location:
                params["vertex_location"] = self.location
            if hasattr(self, "vertex_credentials") and self.vertex_credentials:
                params["vertex_credentials"] = self.vertex_credentials

        # Add response format if provided
        if response_format:
            params["response_format"] = response_format
            logger.debug(f"Using response format: {response_format['type']}")

        # Get MCP tools if available and merge with provided tools
        mcp_tools = self._get_mcp_tools()
        final_tools = tools.copy() if tools else []
        if mcp_tools:
            final_tools.extend(mcp_tools)
            logger.debug(f"Added {len(mcp_tools)} MCP tools to the request")

        # Add tools if any are defined
        if final_tools:
            params["tools"] = final_tools
            logger.debug(
                f"Using tools: {', '.join(tool['function']['name'] for tool in final_tools)}"
            )

        full_response_text = ""
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # Loop to handle potential tool call cycles
        max_tool_cycles = 5 # Prevent infinite loops
        for cycle in range(max_tool_cycles):
            try:
                logger.debug(f"Sending request to LLM (Cycle {cycle + 1})")
                # Update messages for the current call
                params["messages"] = self.messages
                response = self._execute_llm_call(params)

                # Update usage information from this call
                if hasattr(response, 'usage'):
                    total_usage["prompt_tokens"] += response.usage.prompt_tokens
                    total_usage["completion_tokens"] += response.usage.completion_tokens
                    total_usage["total_tokens"] += response.usage.total_tokens
                    logger.inspect(f"Token usage (cycle {cycle + 1}): {response.usage.total_tokens} tokens")

                # Check for tool calls in the response
                processed_tools = self._handle_tool_calls(response)

                if processed_tools:
                    logger.debug("Tool calls processed, continuing loop for LLM response.")
                    # The history has been updated by _handle_tool_calls, loop again
                    continue
                else:
                    # No tool calls, this is the final response (or an error occurred)
                    response_content = response.choices[0].message.content
                    response_text = response_content if response_content is not None else ""
                    full_response_text = response_text # Use the final response text

                    # Add final assistant response to history
                    self.add_message("assistant", full_response_text)
                    logger.debug("Added final assistant response to conversation history")
                    logger.inspect(f"Total token usage for request: {total_usage['total_tokens']} tokens")
                    return full_response_text # Exit loop and return

            except Exception as e:
                error_msg = f"Error communicating with LLM: {str(e)}"
                logger.error(error_msg, exc_info=True) # Log traceback for debugging
                # Add error as assistant message to maintain conversation flow
                self.add_message("assistant", error_msg)
                return error_msg # Return error

        # If loop finishes without returning (e.g., max cycles reached)
        timeout_msg = "Exceeded maximum tool call cycles."
        logger.warning(timeout_msg)
        self.add_message("assistant", timeout_msg)
        return timeout_msg


    def send_message_with_file(self, reply: str, file_data: Dict[str, Any]) -> str:
        """
        Send a message to the LLM with a file attachment (treated as image for now).

        Args:
            reply: The text message to send
            file_data: Dictionary containing file information with keys:
                - mime_type: The MIME type of the file
                - content: The encoded file content
                - encoding: The encoding used (e.g., "base64")

        Returns:
            The LLM's response text
        """
        # Currently, treating all files as images for multimodal input
        # TODO: Add specific handling for non-image files if needed/supported
        if file_data.get("mime_type", "").startswith("image/"):
            return self.send_message_with_image(reply, file_data)
        else:
            # Fallback: Send only the text part if the file is not an image
            logger.warning(f"File type {file_data.get('mime_type')} not directly supported as image. Sending text only.")
            return self.send_message(reply)


    def send_message_with_image(self, reply: str, image_data: Dict[str, Any]) -> str:
        """
        Send a message to the LLM with an image attachment.

        Args:
            reply: The text message to send
            image_data: Dictionary containing image information with keys:
                - mime_type: The MIME type of the image (must be an image type)
                - content: The encoded image content
                - encoding: The encoding used (e.g., "base64")

        Returns:
            The LLM's response text
        """
        # Lazy load modules
        litellm = _get_litellm()
        llm_helpers = _get_llm_helpers()

        logger.debug(
            f"Sending message with image attachment of type: {image_data.get('mime_type')}"
        )

        # Validate image data
        if not all(k in image_data for k in ["mime_type", "content", "encoding"]):
            error_msg = "Image data missing required fields (mime_type, content, encoding)"
            logger.error(error_msg)
            # Add error as assistant message? No, this is an input error.
            return f"Error: {error_msg}"

        mime_type = image_data.get("mime_type", "")
        encoding = image_data.get("encoding", "")
        content = image_data.get("content", "")

        # Verify this is actually an image type
        if not mime_type.startswith("image/"):
            error_msg = f"Invalid mime type for image: {mime_type}. Must be an image type (image/jpeg, image/png, etc.)"
            logger.error(error_msg)
            return f"Error: {error_msg}"

        # Create the data URL for the image
        image_url = f"data:{mime_type};{encoding},{content}"

        # Prepare the message parts with text and image_url
        parts = [
            {"type": "text", "text": reply},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

        # Add the complex user message to the history
        self.add_message("user", parts)
        logger.debug("Added user message with image to conversation history")

        # Prepare model name with provider prefix if needed
        model_name = llm_helpers.format_model_name(self.model, self.provider)
        logger.debug(f"Using model: {model_name}")

        # Prepare parameters for completion
        params = {
            "model": model_name,
            "messages": self.messages, # Use the updated history
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.additional_params,
        }

        # Add provider-specific parameters
        if self.provider == "vertexai":
            if hasattr(self, "project_id") and self.project_id:
                params["vertex_project"] = self.project_id
            if hasattr(self, "location") and self.location:
                params["vertex_location"] = self.location
            if hasattr(self, "vertex_credentials") and self.vertex_credentials:
                params["vertex_credentials"] = self.vertex_credentials

        # Get MCP tools if available
        mcp_tools = self._get_mcp_tools()
        if mcp_tools:
            params["tools"] = mcp_tools
            logger.debug(f"Added {len(mcp_tools)} MCP tools to the request")


        full_response_text = ""
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # Loop to handle potential tool call cycles (similar to send_message)
        max_tool_cycles = 5
        for cycle in range(max_tool_cycles):
            try:
                logger.debug(f"Sending request to LLM with image (Cycle {cycle + 1})")
                # Update messages for the current call
                params["messages"] = self.messages
                response = self._execute_llm_call(params)

                # Update usage information
                if hasattr(response, 'usage'):
                    total_usage["prompt_tokens"] += response.usage.prompt_tokens
                    total_usage["completion_tokens"] += response.usage.completion_tokens
                    total_usage["total_tokens"] += response.usage.total_tokens
                    logger.inspect(f"Token usage (cycle {cycle + 1}): {response.usage.total_tokens} tokens")

                # Check for tool calls in the response
                processed_tools = self._handle_tool_calls(response)

                if processed_tools:
                    logger.debug("Tool calls processed, continuing loop for LLM response.")
                    # History updated by _handle_tool_calls, loop again
                    continue
                else:
                    # No tool calls, this is the final response
                    response_content = response.choices[0].message.content
                    response_text = response_content if response_content is not None else ""
                    full_response_text = response_text

                    # Add final assistant response to history
                    self.add_message("assistant", full_response_text)
                    logger.debug("Added final assistant response to conversation history")
                    logger.inspect(f"Total token usage for request: {total_usage['total_tokens']} tokens")
                    return full_response_text # Exit loop and return

            except Exception as e:
                error_msg = f"Error communicating with LLM: {str(e)}"
                logger.error(error_msg, exc_info=True)
                # Add error as assistant message
                self.add_message("assistant", error_msg)
                return error_msg # Return error

        # If loop finishes without returning
        timeout_msg = "Exceeded maximum tool call cycles."
        logger.warning(timeout_msg)
        self.add_message("assistant", timeout_msg)
        return timeout_msg


    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """
        Get the full conversation history.

        Returns:
            List of message dictionaries
        """
        return self.messages

    def clear_conversation(self, keep_system_prompt: bool = True) -> None:
        """
        Clear the conversation history.

        Args:
            keep_system_prompt: Whether to keep the system prompt in history
        """
        logger.debug(
            f"Clearing conversation history (keep_system_prompt={keep_system_prompt})"
        )
        if keep_system_prompt and self.system_prompt:
            self.messages = [{"role": "system", "content": self.system_prompt}]
        else:
            self.messages = []


def create_conversation(
    model: Optional[str] = None,
    provider: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tokens_per_min: Optional[int] = None,
    **kwargs,
) -> LLMConversation:
    """
    Create a new LLM conversation instance.

    Args:
        model: The specific model to use
        provider: The LLM provider (vertexai, anthropic, openai, groq)
        system_prompt: System prompt to use for the conversation
        tokens_per_min: Maximum tokens per minute for rate limiting
        **kwargs: Additional parameters to pass to the LLMConversation constructor

    Returns:
        An initialized LLMConversation instance
    """
    logger.debug(f"Creating new conversation with provider={provider}, model={model}")
    return LLMConversation(
        model=model,
        provider=provider,
        system_prompt=system_prompt,
        tokens_per_min=tokens_per_min,
        **kwargs,
    )