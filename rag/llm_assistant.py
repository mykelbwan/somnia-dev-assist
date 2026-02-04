from typing import Any, AsyncGenerator, Dict

from agent import AgentState, build_agent
from langchain_core.messages import HumanMessage


def build_llm_assistant(q: str):
    """Build an LLM assistant for non-streaming invocations."""
    agent = build_agent()
    result = agent.invoke(
        {
            "messages": [HumanMessage(content=q)],
            "turns": 0,
            "tool_calls": 0,
            "exit_reason": None,
        }
    )
    return result


async def stream_agent_events(
    input_state: Dict[str, Any],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream all events from the agent, including partial LLM tokens, tool calls,
    and the final state.
    """
    agent = build_agent()
    typed_state: AgentState = {
        "messages": input_state.get("messages", []),
        "turns": input_state.get("turns", 0),
        "tool_calls": input_state.get("tool_calls", 0),
        "exit_reason": input_state.get("exit_reason", None),
    }

    async for event in agent.astream_events(typed_state, version="v1"):
        kind = event["event"]

        # Stream tokens from the chat model
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if hasattr(chunk, "content") and chunk.content:
                # content can be a string or a list of dicts (for multimodal)
                if isinstance(chunk.content, str):
                    yield {"type": "token", "content": chunk.content}
                elif isinstance(chunk.content, list):
                    for part in chunk.content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            yield {"type": "token", "content": part.get("text", "")}
                        elif isinstance(part, str):
                            yield {"type": "token", "content": part}

        # Stream tool calls
        elif kind == "on_tool_start":
            yield {
                "type": "tool_start",
                "name": event["name"],
                "input": event["data"].get("input"),
            }
        elif kind == "on_tool_end":
            yield {
                "type": "tool_end",
                "name": event["name"],
                "output": event["data"].get("output"),
            }

        # Capture the final state of the graph
        elif kind == "on_chain_end":
            # The top-level chain end event contains the final state.
            # In LangGraph, the output of the compiled graph is the final AgentState.
            output = event["data"].get("output")
            if output and isinstance(output, dict) and "exit_reason" in output:
                # Check if it's the root runnable (no parent_ids in v1 usually means it's top-level)
                # Or just yield it, the consumer can take the last one.
                yield {"type": "final_state", "state": output}
                
        elif kind == "on_chat_model_start":
            yield {"type": "message_start"}

        elif kind == "on_chat_model_end":
            yield {"type": "message_end"}


async def stream_agent(q: str) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream all events for a given query.
    """
    input_state = {
        "messages": [HumanMessage(content=q)],
        "turns": 0,
        "tool_calls": 0,
        "exit_reason": None,
    }
    async for event in stream_agent_events(input_state):
        yield event
