from langchain_core.messages import BaseMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from config import MAX_CONTEXT_CHARS


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
    return isinstance(e, ChatGoogleGenerativeAIError) and ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e))
