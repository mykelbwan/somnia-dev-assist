from typing import Annotated, Literal, Sequence, TypedDict

from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from config import MAX_TOOL_CALL, MAX_TURNS
from prompts import system_prompt
from retriever import retriever
from settings import GEMINI_API_KEY
from utils import (
    InMemoryCache,
    generate_cache_key,
    is_rate_limit_error,
    trim_messages,
    with_retry,  # Asynchronous retry mechanism
    with_retry_sync,  # Synchronous retry mechanism
)

from langchain_core.runnables import RunnableLambda

# Initialize the LLM with tool binding. This LLM supports both synchronous (invoke) and
# asynchronous (ainvoke) calls, as well as streaming. The 'streaming=True' argument
# primarily affects asynchronous execution, enabling token-by-token streaming.
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    google_api_key=GEMINI_API_KEY,
    temperature=0,
    streaming=True,
).bind_tools([retriever])

# Caches are persistent across agent invocations in the same process.
# Retrieval results are cached to save latency and costs.
# LLM caching is used for non-streaming calls.
retrieval_cache = InMemoryCache()
llm_cache = InMemoryCache()

ExitReason = Literal[
    "COMPLETED",
    "LLM_GENERATION_FAILURE",
    "MAX_TURNS_REACHED",
    "MAX_TOOL_CALLS_REACHED",
    "INVALID_TOOL_CALL",
    "MAX_CONTEXT_REACHED",
    "EMPTY_INPUT",
    "RATE_LIMITED",
    "LLM_ERROR",
]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    turns: int
    tool_calls: int
    exit_reason: ExitReason | None


def should_continue(state: AgentState) -> bool:
    """Determines whether the agent should continue processing."""
    last = state["messages"][-1]
    return isinstance(last, AIMessage) and bool(last.tool_calls)


def _validate_llm_input(state: AgentState) -> dict | tuple[list[BaseMessage], str]:
    """
    Common validation and preparation logic for both synchronous and asynchronous
    LLM node implementations. This centralizes checks for turn limits, context
    overflow, and empty input to avoid duplication.
    """
    if state["turns"] >= MAX_TURNS:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I reached the maximum reasoning steps for this request. "
                        "Please rephrase or ask a more specific question."
                    )
                )
            ],
            "exit_reason": "MAX_TURNS_REACHED",
        }

    history = list(state["messages"])
    trimmed_history = trim_messages(history)

    # Context overflow — do not call LLM
    if len(trimmed_history) < len(history):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "The conversation is too long for me to answer safely. "
                        "Please start a new question or narrow the scope."
                    )
                )
            ],
            "exit_reason": "MAX_CONTEXT_REACHED",
        }

    # No empty human input
    if not any(
        isinstance(m, HumanMessage)
        and (m.content.strip() if isinstance(m.content, str) else bool(m.content))
        for m in trimmed_history
    ):
        return {"exit_reason": "EMPTY_INPUT"}

    messages = [system_prompt] + trimmed_history

    # Cache key based on model and full message payload.
    # This ensures deterministic caching behavior for both sync and async paths.
    llm_cache_key = generate_cache_key(
        "llm",
        {
            "model": "gemini-2.5-flash-lite",
            "messages": [
                (m.type, m.content, getattr(m, "tool_calls", None)) for m in messages
            ],
        },
    )
    return messages, llm_cache_key


def _handle_llm_error(e: Exception) -> dict:
    """
    Common error handling logic for both synchronous and asynchronous
    LLM node implementations, centralizing rate limit and general error responses.
    """
    if is_rate_limit_error(e) or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I'm temporarily rate-limited by the AI provider. "
                        "Please wait a moment and try again."
                    )
                )
            ],
            "exit_reason": "RATE_LIMITED",
        }
    return {
        "messages": [
            AIMessage(
                content=f"An internal error occurred while processing your request: {e}"
            )
        ],
        "exit_reason": "LLM_ERROR",
    }


def llm_node(state: AgentState):
    """
    Synchronous implementation of the LLM node.
    This function is used when the LangGraph agent is invoked synchronously (`.invoke()`).
    It explicitly uses synchronous cache access methods (`.get_sync()`, `.set_sync()`)
    and the synchronous `with_retry_sync` helper along with `llm.invoke()` to ensure
    all operations are blocking and compatible with a synchronous call stack.
    This prevents `TypeError` from asynchronous calls in a synchronous context.
    """
    validated = _validate_llm_input(state)
    if isinstance(validated, dict):
        return validated
    messages, llm_cache_key = validated

    # Use synchronous cache access for the sync path
    cached_response = llm_cache.get_sync(llm_cache_key)
    if cached_response:
        return {
            "messages": [cached_response],
            "turns": state["turns"] + 1,
            "exit_reason": "COMPLETED",
        }

    try:
        # Use synchronous retry and LLM invocation
        response = with_retry_sync(
            lambda: llm.invoke(messages),
            max_retries=2,
            retryable_exceptions=(Exception,),
        )
        llm_cache.set_sync(llm_cache_key, response, ttl=3600)
    except Exception as e:
        return _handle_llm_error(e)

    return {
        "messages": [response],
        "turns": state["turns"] + 1,
        "exit_reason": "COMPLETED",
    }


async def llm_node_async(state: AgentState):
    """
    Asynchronous implementation of the LLM node.
    This function is used when the LangGraph agent is invoked asynchronously (`.ainvoke()`
    or `.astream_events()`). It explicitly uses asynchronous cache access methods
    (`await .get()`, `await .set()`) and the asynchronous `await with_retry` helper
    along with `await llm.ainvoke()` to maintain non-blocking behavior.
    It also dispatches custom events for streaming consumers, crucial for
    real-time UI updates and cache hit notifications.
    """
    validated = _validate_llm_input(state)
    if isinstance(validated, dict):
        return validated
    messages, llm_cache_key = validated

    # Use asynchronous cache access for the async path
    cached_response = await llm_cache.get(llm_cache_key)
    if cached_response:
        # For streaming consumers: emit the full cached response content as a custom event.
        # This allows unified behavior between live streaming and cached delivery.
        await adispatch_custom_event(
            "cached_response", {"content": cached_response.content}
        )
        return {
            "messages": [cached_response],
            "turns": state["turns"] + 1,
            "exit_reason": "COMPLETED",
        }

    try:
        # Use asynchronous retry and LLM invocation for non-blocking operations
        response = await with_retry(
            lambda: llm.ainvoke(messages),
            max_retries=2,
            retryable_exceptions=(Exception,),
        )
        await llm_cache.set(llm_cache_key, response, ttl=3600)
    except Exception as e:
        return _handle_llm_error(e)

    return {
        "messages": [response],
        "turns": state["turns"] + 1,
        "exit_reason": "COMPLETED",
    }


def _prepare_tool_output(state: AgentState) -> dict | tuple[AIMessage, list]:
    """
    Common preparation and validation logic for both synchronous and asynchronous
    tool node implementations.
    """
    if state["tool_calls"] >= MAX_TOOL_CALL:
        return {
            "messages": [
                ToolMessage(
                    content="Tool call limit reached. Unable to retrieve more context.",
                    tool_call_id="limit",
                )
            ],
            "exit_reason": "MAX_TOOL_CALLS_REACHED",
        }
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {"messages": []}
    return last, []


def tool_node(state: AgentState):
    """
    Synchronous implementation of the tool node.
    Similar to `llm_node`, this function ensures all operations for tool execution
    (caching, retry, and `retriever` invocation) are strictly synchronous.
    It uses `.get_sync()`, `.set_sync()`, `with_retry_sync`, and `retriever.invoke()`
    to support synchronous agent execution without introducing asynchronous calls.
    """
    prepared = _prepare_tool_output(state)
    if isinstance(prepared, dict):
        return prepared
    last, outputs = prepared

    for call in last.tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        tool_id = call["id"]
        if tool_name == "retriever":
            # Cache key generation is deterministic and shared across sync/async
            cache_key = generate_cache_key(
                "retriever",
                {
                    "query": tool_args["query"],
                    "k": 5,
                    "fetch_k": 20,
                    "type": "mmr",
                },
            )

            # Use synchronous cache access for the sync path
            result = retrieval_cache.get_sync(cache_key)
            if result is None:
                try:
                    # Use synchronous retry and tool invocation
                    result = with_retry_sync(
                        lambda: retriever.invoke(tool_args["query"]),
                        max_retries=3,
                        retryable_exceptions=(Exception,),
                    )
                    if result and result != "DOCUMENTATION_SEARCH_RESULT: EMPTY":
                        retrieval_cache.set_sync(cache_key, result, ttl=3600)
                except Exception as e:
                    result = f"Error executing tool {tool_name}: {str(e)}"

            if result == "DOCUMENTATION_SEARCH_RESULT: EMPTY":
                outputs.append(ToolMessage(content=result, tool_call_id=tool_id))
                return {
                    "messages": outputs,
                    "tool_calls": state["tool_calls"] + 1,
                    "exit_reason": "LLM_GENERATION_FAILURE",
                }
            outputs.append(ToolMessage(content=result, tool_call_id=tool_id))
    return {
        "messages": outputs,
        "tool_calls": state["tool_calls"] + len(outputs),
    }


async def tool_node_async(state: AgentState):
    """
    Asynchronous implementation of the tool node.
    Similar to `llm_node_async`, this function uses asynchronous cache access
    (`await .get()`, `await .set()`), `await with_retry`, and `await retriever.ainvoke()`
    to provide a non-blocking execution path for tool calls, essential for
    asynchronous agent invocations and streaming.
    """
    prepared = _prepare_tool_output(state)
    if isinstance(prepared, dict):
        return prepared
    last, outputs = prepared

    for call in last.tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        tool_id = call["id"]
        if tool_name == "retriever":
            # Cache key generation is deterministic and shared across sync/async
            cache_key = generate_cache_key(
                "retriever",
                {
                    "query": tool_args["query"],
                    "k": 5,
                    "fetch_k": 20,
                    "type": "mmr",
                },
            )

            # Use asynchronous cache access for the async path
            result = await retrieval_cache.get(cache_key)
            if result is None:
                try:
                    # Use asynchronous retry and tool invocation
                    result = await with_retry(
                        lambda: retriever.ainvoke(tool_args["query"]),
                        max_retries=3,
                        retryable_exceptions=(Exception,),
                    )
                    if result and result != "DOCUMENTATION_SEARCH_RESULT: EMPTY":
                        await retrieval_cache.set(cache_key, result, ttl=3600)
                except Exception as e:
                    result = f"Error executing tool {tool_name}: {str(e)}"

            if result == "DOCUMENTATION_SEARCH_RESULT: EMPTY":
                outputs.append(ToolMessage(content=result, tool_call_id=tool_id))
                return {
                    "messages": outputs,
                    "tool_calls": state["tool_calls"] + 1,
                    "exit_reason": "LLM_GENERATION_FAILURE",
                }
            outputs.append(ToolMessage(content=result, tool_call_id=tool_id))
    return {
        "messages": outputs,
        "tool_calls": state["tool_calls"] + len(outputs),
    }


def build_agent():
    graph = StateGraph(AgentState)

    # Use RunnableLambda to provide both synchronous (func)
    # and asynchronous (afunc) implementations for nodes. This enables the graph
    # to be invoked via `.invoke()` for blocking execution and `.ainvoke()` or
    # `.astream_events()` for non-blocking, streaming execution.
    # This design avoids duplicating the graph structure or core logic, as the
    # common preparation and error handling are extracted into helper functions.
    # LangGraph automatically selects the appropriate 'func' or 'afunc' based on
    # how the overall graph is invoked.
    graph.add_node("llm", RunnableLambda(func=llm_node, afunc=llm_node_async))
    graph.add_node("tools", RunnableLambda(func=tool_node, afunc=tool_node_async))

    graph.set_entry_point("llm")
    graph.add_conditional_edges(
        "llm",
        should_continue,
        {True: "tools", False: END},
    )
    graph.add_edge("tools", "llm")
    return graph.compile()
