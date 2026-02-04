import asyncio
import sys

from llm_assistant import stream_agent


async def main():
    use_streaming = "--stream" in sys.argv

    while True:
        try:
            q = input("> ")
        except EOFError:
            break

        if q.lower() in ("exit", "quit"):
            break
        if not q.strip():
            continue

        if use_streaming:
            print("--- Streaming Response ---")
            final_state = None
            async for event in stream_agent(q):
                if event["type"] == "token":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "tool_start":
                    print(
                        f"\n[Calling tool: {event['name']} with input: {event['input']}]"
                    )
                elif event["type"] == "tool_end":
                    # We don't necessarily want to print the whole tool output to the user
                    # but maybe a confirmation that it's done.
                    print(f"[Tool {event['name']} completed]")
                elif event["type"] == "final_state":
                    final_state = event["state"]

            if final_state:
                # If there's a final state, check for messages and an exit reason.
                if "messages" in final_state and final_state["messages"]:
                    final_state["messages"][-1]
                    # Assuming AIMessage has a 'content' attribute.
                    # The streaming part should have already printed the content.
                    # This part might be redundant if the last message is the full response.
                    # We will keep the exit reason print.
                print(f"\n\n[exit_reason={final_state.get('exit_reason')}]")
            else:
                print("\n[Error: No final state received]")
        else:
            from llm_assistant import build_llm_assistant

            result = build_llm_assistant(q)
            print("--- Non-Streaming Response ---")
            if result["messages"]:
                print(result["messages"][-1].content)
            print(f"\n[exit_reason={result.get('exit_reason')}]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
