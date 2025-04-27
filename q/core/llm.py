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
        self.messages: List[Dict[str, str]] = []
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

    def add_message(self, role: str, content: str) -> None:
        """
        Add a message to the conversation history.

        Args:
            role: The role of the message sender ("user", "assistant", or "system")
            content: The content of the message
        """
        self.messages.append({"role": role, "content": content})

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
            logger.inspect(
                f"LLM parameters: {json.dumps({k: v for k, v in params.items() if k != 'messages'})}"
            )

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
                message = params["messages"][-1]["content"]
                q_console.print(f"[cyan]{message}[/]")

            ############ Execute the API call #############
            response = litellm.completion(**params)

            if getattr(config, "LLM_IN_OUT", None):
                q_console.print(f"[red]{response.choices[0].message.content}[/]")

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
                raise

    def send_message(
        self,
        message: str,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a message to the LLM and get a response.

        Args:
            message: The message to send
            response_format: Optional format specification for structured responses
            tools: Optional tools configuration (e.g., for function calling or grounding)

        Returns:
            The LLM's response text
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

        # Prepare parameters for completion
        params = {
            "model": model_name,
            "messages": self.messages,
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

        # Add tools if provided
        if tools:
            params["tools"] = tools
            logger.debug(
                f"Using tools: {', '.join(list(tool.keys())[0] for tool in tools) if tools else 'None'}"
            )

        full_response_text = ""
        total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # Call LiteLLM completion with retry mechanism
        try:
            while True:
                try:
                    logger.debug("Sending request to LLM")
                    response = self._execute_llm_call(params)

                    # Extract response content - handle potential None values
                    response_content = response.choices[0].message.content
                    response_text = (
                        response_content if response_content is not None else ""
                    )
                    full_response_text += response_text

                    # Update usage information
                    total_usage["prompt_tokens"] += response.usage.prompt_tokens
                    total_usage["completion_tokens"] += response.usage.completion_tokens
                    total_usage["total_tokens"] += response.usage.total_tokens
                    logger.inspect(
                        f"Token usage: {total_usage['total_tokens']} total tokens"
                    )
                    logger.inspect(
                        f"Received chunk from LLM: {response.usage.total_tokens}"
                    )

                    # Check finish reason
                    finish_reason = response.choices[0].finish_reason
                    if finish_reason == "stop":
                        logger.inspect("LLM response complete (finish_reason: stop)")
                        break
                    elif finish_reason == "length":
                        # Add the last response to the messages to maintain context
                        logger.inspect(
                            "LLM response truncated (finish_reason: length), continuing"
                        )
                        self.add_message("assistant", response_text)
                        # Update the messages with the assistant's last response for the next iteration
                        params["messages"] = self.messages
                        continue
                    else:
                        # Handle unexpected finish reason
                        error_msg = f"Unexpected finish reason: {finish_reason}"
                        logger.warning(error_msg)
                        self.add_message("assistant", error_msg)
                        return error_msg

                except Exception as e:
                    # If we've exhausted retries or it's not an overloaded error, this will be raised
                    raise e

            # Add assistant response to history
            self.add_message("assistant", full_response_text)
            logger.debug("Added assistant response to conversation history")

            return full_response_text
        except Exception as e:
            error_msg = f"Error communicating with LLM: {str(e)}"
            logger.error(error_msg)
            # Add error as assistant message to maintain conversation flow
            self.add_message("assistant", error_msg)
            return error_msg

    def send_message_with_file(self, reply: str, file_data: Dict[str, Any]) -> str:
        """
        Send a message to the LLM with a file attachment.

        Args:
            reply: The text message to send
            file_data: Dictionary containing file information with keys:
                - mime_type: The MIME type of the file
                - content: The encoded file content
                - encoding: The encoding used (e.g., "base64")

        Returns:
            The LLM's response text
        """
        # Lazy load modules
        litellm = _get_litellm()
        llm_helpers = _get_llm_helpers()
        
        logger.debug(
            f"Sending message with file attachment of type: {file_data.get('mime_type')}"
        )

        # Validate file data
        if not all(k in file_data for k in ["mime_type", "content", "encoding"]):
            error_msg = (
                "File data missing required fields (mime_type, content, encoding)"
            )
            logger.error(error_msg)
            return f"Error: {error_msg}"

        mime_type = file_data.get("mime_type")
        encoding = file_data.get("encoding")
        content = file_data.get("content")

        # Create the data URL for the file
        file_url = f"data:{mime_type};{encoding},{content}"

        # Prepare the message parts with text and image_url
        parts = [
            {"type": "text", "text": reply},
            {"type": "image_url", "image_url": {"url": file_url}},
        ]

        # Prepare model name with provider prefix if needed
        model_name = llm_helpers.format_model_name(self.model, self.provider)
        logger.debug(f"Using model: {model_name}")

        # Create a copy of the messages for this request
        # We need to keep the system prompt if it exists
        messages_copy = [msg for msg in self.messages if msg["role"] == "system"]

        # Add the message with file parts
        messages_copy.append({"role": "user", "content": parts})  # type: ignore

        # Prepare parameters for completion with file attachment
        params = {
            "model": model_name,
            "messages": messages_copy,
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

        # Execute the LLM call and process response
        try:
            logger.debug("Sending request to LLM with file attachment")
            response = self._execute_llm_call(params)

            # Extract response content
            response_content = response.choices[0].message.content
            response_text = response_content if response_content is not None else ""

            # Update the conversation history with the user message and assistant response
            # First add the user message with just the text (for history purposes)
            self.add_message("user", reply)
            # Then add the assistant response
            self.add_message("assistant", response_text)
            logger.debug("Added assistant response to conversation history")

            return response_text

        except Exception as e:
            error_msg = f"Error communicating with LLM: {str(e)}"
            logger.error(error_msg)
            # Add error as assistant message to maintain conversation flow
            self.add_message("assistant", error_msg)
            return error_msg

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
            error_msg = (
                "Image data missing required fields (mime_type, content, encoding)"
            )
            logger.error(error_msg)
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

        # Prepare model name with provider prefix if needed
        model_name = llm_helpers.format_model_name(self.model, self.provider)
        logger.debug(f"Using model: {model_name}")

        # Create a copy of the messages for this request
        # We need to keep the system prompt if it exists
        messages_copy = [msg for msg in self.messages if msg["role"] == "system"]

        # Add the message with image parts
        messages_copy.append({"role": "user", "content": parts})  # type: ignore

        # Prepare parameters for completion with image attachment
        params = {
            "model": model_name,
            "messages": messages_copy,
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

        # Execute the LLM call and process response
        try:
            logger.debug("Sending request to LLM with image attachment")
            response = self._execute_llm_call(params)

            # Extract response content
            response_content = response.choices[0].message.content
            response_text = response_content if response_content is not None else ""

            # Update the conversation history with the user message and assistant response
            # First add the user message with just the text (for history purposes)
            self.add_message("user", reply)
            # Then add the assistant response
            self.add_message("assistant", response_text)
            logger.debug("Added assistant response to conversation history")

            return response_text

        except Exception as e:
            error_msg = f"Error communicating with LLM: {str(e)}"
            logger.error(error_msg)
            # Add error as assistant message to maintain conversation flow
            self.add_message("assistant", error_msg)
            return error_msg

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """
        Get the full conversation history.

        Returns:
            List of message dictionaries with 'role' and 'content' keys
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