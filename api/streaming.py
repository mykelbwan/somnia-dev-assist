import json
from typing import AsyncGenerator

from rag.llm_assistant import stream_agent


async def stream_chat_responses(query: str) -> AsyncGenerator[str, None]:
    """
    Yields Server-Sent Events for the streaming chat endpoint, including handling
    errors as events within the stream.
    """
    final_state_event = None
    try:
        async for event in stream_agent(query):
            if event.get("type") == "final_state":
                # Don't send the final state immediately, as it can be large.
                # We'll process it for the exit reason after the loop.
                final_state_event = event
            else:
                sse_event = f"data: {json.dumps(event)}\n\n"
                yield sse_event

        # After the stream is finished, analyze the final state for the exit reason.
        if final_state_event:
            exit_reason = final_state_event.get("state", {}).get("exit_reason")
            if exit_reason and exit_reason not in ["COMPLETED", "MAX_TURNS_REACHED", "MAX_TOOL_CALLS_REACHED"]:
                error_event = {
                    "type": "error",
                    "detail": exit_reason,
                }
                yield f"data: {json.dumps(error_event)}\n\n"
            
            # Always emit a final event with the exit reason
            final_event = {
                "type": "final_reason",
                "exit_reason": exit_reason or "UNKNOWN"
            }
            yield f"data: {json.dumps(final_event)}\n\n"

    except Exception as e:
        error_payload = {
            "type": "error",
            "detail": "INTERNAL_SERVER_ERROR",
            "message": str(e),
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
