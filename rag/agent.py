from typing import Annotated, Literal, Sequence, TypedDict

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
from utils import is_rate_limit_error, trim_messages

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    google_api_key=GEMINI_API_KEY,
    temperature=0,
    streaming=True,
).bind_tools([retriever])

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


def llm_node(state: AgentState):
    if state["turns"] >= MAX_TURNS:
        return {
            "messages": AIMessage(
                content=(
                    "I reached the maximum reasoning steps for this request. "
                    "Please rephrase or ask a more specific question."
                )
            ),
            "exit_reason": "MAX_TURNS_REACHED",
        }

    history = list(state["messages"])
    trimmed_history = trim_messages(history)

    # Context overflow — do not call LLM
    if len(trimmed_history) < len(history):
        return {
            "messages": AIMessage(
                content=(
                    "⚠️ The conversation is too long for me to answer safely. "
                    "Please start a new question or narrow the scope."
                )
            ),
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

    try:
        response = llm.invoke(messages)
    except Exception as e:
        if is_rate_limit_error(e) or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            return {
                "messages": AIMessage(
                    content=(
                        "I'm temporarily rate-limited by the AI provider. "
                        "Please wait a moment and try again."
                    )
                ),
                "exit_reason": "RATE_LIMITED",
            }
        return {
            "messages": AIMessage(
                content="An internal error occurred while processing your request."
            ),
            "exit_reason": "LLM_ERROR",
        }
    return {
        "messages": response,
        "turns": state["turns"] + 1,
        "exit_reason": "COMPLETED",
    }


def tool_node(state: AgentState):
    """Executes tools based on the last message's tool calls."""
    if state["tool_calls"] >= MAX_TOOL_CALL:
        return {
            "messages": [
                ToolMessage(
                    content="Tool call limit reached. Unable to retrieve more context.",
                    tool_call_id="limit",
                )
            ],
            "exit_reason": "MAX_TOOL_CALL_REACHED",
        }
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {"messages": []}

    outputs = []

    for call in last.tool_calls:
        tool_name = call["name"]
        tool_args = call["args"]
        tool_id = call["id"]
        if tool_name == "retriever":
            result = retriever.invoke(tool_args["query"])
            if result == "DOCUMENTATION_SEARCH_RESULT: EMPTY":
                outputs.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=tool_id,
                    )
                )
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
    graph.add_node("llm", llm_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("llm")
    graph.add_conditional_edges(
        "llm",
        should_continue,
        {True: "tools", False: END},
    )
    graph.add_edge("tools", "llm")
    return graph.compile()
