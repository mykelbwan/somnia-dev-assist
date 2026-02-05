import asyncio
import hashlib
import inspect
import json
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, TypeVar

from config import MAX_CONTEXT_CHARS
from langchain_core.messages import BaseMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

T = TypeVar("T")


class BaseCache(ABC):
    """Base interface for caching implementations."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        pass

    @abstractmethod
    def get_sync(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    def set_sync(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        pass


class InMemoryCache(BaseCache):
    """Simple in-memory cache with TTL support."""

    def __init__(self):
        self._cache: Dict[str, tuple[Any, float]] = {}

    def get_sync(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        value, expiry = self._cache[key]
        if expiry is not None and time.time() > expiry:
            del self._cache[key]
            return None
        return value

    def set_sync(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expiry = time.time() + ttl if ttl is not None else None
        self._cache[key] = (value, expiry)

    async def get(self, key: str) -> Optional[Any]:
        return self.get_sync(key)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.set_sync(key, value, ttl)


def generate_cache_key(prefix: str, data: Dict[str, Any]) -> str:
    """Generates a deterministic hash key for a given prefix and data dictionary."""
    serialized = json.dumps(data, sort_keys=True)
    hash_val = hashlib.sha256(serialized.encode()).hexdigest()
    return f"{prefix}:{hash_val}"


def with_retry_sync(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """
    Executes a function with exponential backoff and jitter for transient failures.
    Synchronous version.
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries - 1:
                break

            delay = min(max_delay, base_delay * (2**attempt))
            jitter = random.uniform(0, 0.1 * delay)
            time.sleep(delay + jitter)

    if last_exception:
        raise last_exception
    raise RuntimeError("Retry failed without exception")


async def with_retry(
    func: Callable[..., Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """
    Executes a function with exponential backoff and jitter for transient failures.
    Supports both sync and async callables but MUST be awaited.
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            # Determine if the function itself is a coroutine function.
            # If so, await its execution. Otherwise, call it directly.
            # Call the function (sync or async)
            func_result = func()

            # If the result is awaitable, await it
            if inspect.isawaitable(func_result):
                return await func_result
            else:
                # Otherwise, return the result directly
                return func_result

        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries - 1:
                break

            delay = min(max_delay, base_delay * (2**attempt))
            jitter = random.uniform(0, 0.1 * delay)
            await asyncio.sleep(delay + jitter)

    if last_exception:
        raise last_exception
    raise RuntimeError("Retry failed without exception")


def trim_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Trims a list of messages to ensure that the cumulative length of their content
    remains within the limit defined by MAX_CONTEXT_CHARS.

    The function processes the messages in reverse chronological order, starting
    from the most recent message at the end of the list. It accumulates the
    character count of each message's content and includes it in the result as
    long as the total remains under the maximum threshold. If adding a message
    would cause the total to exceed MAX_CONTEXT_CHARS, the process terminates,
    effectively discarding older messages that do not fit. Finally, the selected
    messages are returned in their original chronological order.

    Args:
                                    messages (list[BaseMessage]): A list of message objects to be evaluated.

    Returns:
                                    list[BaseMessage]: A list of the most recent messages whose combined
                                                                    content length is within the maximum context size.
    """
    total = 0
    trimmed = []

    for msg in reversed(messages):
        size = len(msg.content)
        if total + size > MAX_CONTEXT_CHARS:
            break
        trimmed.append(msg)
        total += size

    return list(reversed(trimmed))


def is_rate_limit_error(e: Exception) -> bool:
    return isinstance(e, ChatGoogleGenerativeAIError) and (
        "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
    )
