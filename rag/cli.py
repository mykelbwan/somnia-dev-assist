from llm_assistant import build_llm_assistant

while True:
    q = input("> ")
    if q in ("exit", "quit"):
        break

    result = build_llm_assistant(q)

    print(result["messages"][-1].content)
    print(f"\n[exit_reason={result.get('exit_reason')}]")
