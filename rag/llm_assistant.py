from agent import AgentState, build_agent
from langchain_core.messages import HumanMessage


def build_llm_assistant(q: str):
    """Build an LLM assistant."""
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


def stream_agent(input_state: dict):
    agent = build_agent()

    # Wrap dict into AgentState type hint (TypedDict is just a dict at runtime)
    typed_state: AgentState = {
        "messages": input_state.get("messages", []),
        "turns": input_state.get("turns", 0),
        "tool_calls": input_state.get("tool_calls", 0),
        "exit_reason": input_state.get("exit_reason", None),
    }

    for event in agent.stream(typed_state):
        yield event
