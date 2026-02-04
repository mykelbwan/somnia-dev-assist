# Somnia RAG Agent: Behavioral Contract

## 1. Purpose & Scope

This document describes the guaranteed runtime behavior of the Somnia RAG agent. It defines the agent's operational promises, limitations, and failure modes based strictly on its implementation.

This contract covers the agent's internal logic, including input processing, retrieval, state management, and termination conditions. It explicitly does *not* cover the following:

-   The specific content of the documentation (`docs/`).
-   The data ingestion process (`ingest.py`).
-   The underlying vector database (`ChromaDB`).
-   API implementation details (e.g., FastAPI, streaming protocols).
-   Architectural descriptions, which are covered in `ARCHITECTURE.md`.

## 2. Input Assumptions

The agent operates on a single string input representing the user's query.

-   **Valid Input:** The agent expects a non-empty string containing a technical question or claim related to the Somnia ecosystem.
-   **Empty/Whitespace Input:** If the user provides an input that is empty or consists only of whitespace, the agent will immediately exit with an `EMPTY_INPUT` reason. It will not call the LLM.
-   **Ambiguous or Malformed Input:** The agent does not perform semantic validation on the input. Ambiguous, malformed, or non-technical questions are passed directly to the LLM. The `system_prompt` instructs the LLM to ask for clarification if a query is vague, but this behavior is delegated to the model and not guaranteed by the agent's code.

## 3. Retrieval Behavior

Retrieval is a mandatory and central component of the agent's reasoning process.

-   **Mandatory Retrieval (Prompt-Enforced):**
The agent is prompted to call the retriever tool for any technical Somnia-related question. While the control flow supports tool usage, enforcement relies on the LLM adhering to the system prompt rather than a hard graph constraint.
-   **Refusal without Context:** The `system_prompt` strictly forbids the agent from answering technical questions without retrieved context. If retrieval yields no results, the prompt commands the agent to state: "I don't have enough information in the current documentation to answer that."
-   **Missing/Empty Retrieval Results:** If the `retriever` tool is called but finds no matching documents, it returns the specific string `"DOCUMENTATION_SEARCH_RESULT: EMPTY"`. The `tool_node` passes this result back to the LLM. The agent's `exit_reason` is set to `LLM_GENERATION_FAILURE`, indicating the model's query failed to yield context. The final response is then determined by the LLM, which is instructed to report that it lacks information.

## 4. Grounding & Citation Rules

The agent's behavior is strictly governed by the principle of grounding answers in provided documentation.

-   **Definition of "Grounded":** An answer is considered "grounded" only if it is derived directly from text provided by the `retriever` tool. The `system_prompt` forbids introducing any technical claim not explicitly supported by a cited source.
-   **Refusal to Guess:** The agent will refuse to answer if no supporting documentation is found. Speculation, generalization, or inference beyond what is stated in the documentation is forbidden by the prompt.
-   **Citation Enforcement:** The `system_prompt` requires the agent to "cite sources explicitly using the numbered references and filenames provided." This is a prompt-level instruction, meaning enforcement is delegated to the LLM's adherence to its instructions, not through code.

## 5. State & Turn Guarantees

The agent's state is explicitly managed and constrained to prevent runaway execution.

-   **State Evolution:** The agent's state (`AgentState`) consists of `messages` (the conversation history), `turns` (number of LLM-tool cycles), and `tool_calls` (number of tool executions). The state evolves through a `StateGraph` that transitions between an `llm` node and a `tools` node.
-   **Infinite Loop Prevention:** Infinite loops are prevented by two hard limits defined in `config.py`:
    -   `MAX_TURNS` (6): The `llm_node` terminates execution if the turn count reaches this limit, exiting with reason `MAX_TURNS_REACHED`.
    -   `MAX_TOOL_CALL` (3): The `tool_node` terminates execution if the tool call count reaches this limit, exiting with reason `MAX_TOOL_CALLS_REACHED`.
-   **State Transitions:** The agent guarantees that each state transition involves either a call to the LLM or an execution of a tool. The loop continues as long as the LLM generates tool calls and terminates when it generates a final text response.
- **Single-Termination Guarantee:**
Every agent invocation terminates in exactly one exit_reason. Partial or ambiguous termination states are not exposed to clients.

## 6. Context & Safety Limits

The agent enforces strict context limits to ensure safe and predictable LLM calls.

-   **Context Trimming:** Before each LLM call, the conversation history is passed to the `trim_messages` utility. This function calculates the total character count of messages in reverse chronological order and includes messages only until the `MAX_CONTEXT_CHARS` (12,000) limit is reached. Older messages are discarded.
-   **Exceeding Context Limits:** If the trimming process discards any messages (i.e., the original history was longer than the trimmed history), the agent considers the context to have overflowed.
-   **Exit on Overflow:** In the event of a context overflow, the `llm_node` immediately terminates the process with an exit reason of `MAX_CONTEXT_REACHED`. This is a critical safety feature to prevent the LLM from generating a response based on an incomplete or truncated conversational history, which could lead to inaccurate or out-of-context answers.

## 7. Exit Reasons (Authoritative List)

The `exit_reason` field provides a definitive, machine-readable explanation for why the agent stopped.

| `exit_reason`             | Cause                                                                                                                                                               | Retryable? | Display Message Verbatim?                                                                   |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------- |
| `COMPLETED`               | **Normal Exit:** The LLM generated a final response without needing further tool calls.                                                                             | N/A        | Yes                                                                                         |
| `MAX_TURNS_REACHED`         | The agent exceeded the `MAX_TURNS` limit (6) of LLM-tool cycles. This prevents infinite reasoning loops.                                                              | Yes        | Yes, the message explains the situation and advises the user to rephrase.                   |
| `MAX_TOOL_CALLS_REACHED`    | The agent exceeded the `MAX_TOOL_CALL` limit (3). This prevents excessive, non-productive tool usage.                                                                 | Yes        | No, the agent produces a `ToolMessage` not intended for the user. A final LLM response follows. |
| `MAX_CONTEXT_REACHED`     | The total length of the conversation history exceeded `MAX_CONTEXT_CHARS` (12,000). The agent exits to avoid answering with incomplete context.                          | No         | Yes, the message explains the context limit was hit and advises starting over.              |
| `EMPTY_INPUT`             | The user submitted an empty or whitespace-only query.                                                                                                               | Yes        | No, the agent produces no message. The client should prompt the user for input.           |
| `RATE_LIMITED`            | The LLM provider (Google) returned a rate limit error (e.g., 429) after internal retries were exhausted.                                                            | Yes        | Yes, the message informs the user of a temporary rate limit issue.                          |
| `LLM_ERROR`               | An unhandled exception occurred during the `llm.invoke` call after internal retries were exhausted, other than a rate limit error.                                  | Maybe      | Yes, a generic "internal error" message is provided.                                        |
| `LLM_GENERATION_FAILURE`  | The LLM produced an unusable output (e.g., empty content) or retrieval yielded no usable context. This indicates a failure to ground an answer, not necessarily a malformed query.                                                                     | Yes        | No, this is an internal state. The LLM is re-invoked to generate the final user message.    |
| `INVALID_TOOL_CALL`       | This exit reason is defined in the `AgentState` type but is not currently implemented in any code path. Its behavior is undefined.                                    | Unknown    | Unknown                                                                                     |

## 8. Caching & Resilience

To improve performance and reliability, the agent implements several production-grade features.

-   **Retrieval Caching:** Successful retrieval results are cached in-memory, keyed by a deterministic hash of the query and retriever configuration. This reduces latency and prevents redundant vector store queries. Empty results are not cached.
-   **LLM Response Caching:** Non-streaming LLM responses are cached based on the model name and the full message payload. This ensures consistent responses for identical inputs and reduces API costs.
-   **Note on Streaming & Caching:** Using cached LLM responses bypasses the real-time token generation process. While the final state remains consistent, intermediate `on_llm_stream` events will not be emitted for cache hits.
-   **Automatic Tool Retries:** The agent performs automatic retries for transient failures (e.g., network timeouts, 5xx errors) encountered during tool execution or LLM calls.
    -   **Strategy:** Exponential backoff with jitter.
    -   **Limit:** Maximum of 3 retries for tools and 2 retries for LLM calls.
    -   **Counter Integrity:** Internal retries of the same tool call do not increment the `tool_calls` limit; only unique tool call requests from the LLM count towards the limit.

## 9. Streaming Behavior

The agent supports real-time event streaming via LangGraph's `astream_events` (v2) protocol. This allows clients to observe the agent's reasoning process as it happens.

-   **Streamed Events:** The agent guarantees the emission of the following event types:
    -   `on_chat_model_stream`: Incremental LLM tokens during answer generation.
    -   `on_tool_start`: Notification that a tool (e.g., `retriever`) has been invoked, including its input arguments.
    -   `on_tool_end`: The raw output of a tool execution.
    -   `on_chain_end`: The final `AgentState` containing the complete message history and the `exit_reason`.
-   **Event Ordering:** While `on_tool_start` will always precede `on_tool_end` for a given call, and `on_chain_end` is always the terminal event, the interleaved order of tokens and tool events is determined by the LLM's reasoning path.
-   **Caching Trade-off:** Cache hits for non-streaming LLM calls (see Section 8) **do not emit token-by-token streaming events**. Instead, they produce an immediate response followed by the final state. This is an intentional design decision to prioritize latency and determinism for repeated queries.
-   **Non-Guarantees:**
    -   **Token Granularity:** The size and frequency of chunks in `on_chat_model_stream` are not guaranteed and depend on the underlying provider.
    -   **Concurrency:** If multiple tool calls are triggered in parallel, their start/end events may interleave.

## 10. Execution Modes (Contractual Differences)

The agent provides two primary interfaces with distinct behavioral profiles.

| Feature | `invoke` (Non-Streaming) | `astream_events` (Streaming) |
| :--- | :--- | :--- |
| **Primary Use Case** | Background tasks, batch processing, simple API responses. | Interactive UIs, real-time developer assistance. |
| **Caching** | Fully supported for both retrieval and LLM calls. | LLM caching is supported but bypasses token events. |
| **Latency** | Highest perceived (waits for full completion). | Lowest perceived (immediate feedback via tokens/events). |
| **Termination Signal** | Function return. | Emission of the final state event. |

## 11. Failure Modes & Non-Goals

The agent is designed with specific trade-offs that intentionally limit its capabilities.

-   **Will Not Speculate:** The agent is explicitly forbidden by its `system_prompt` from guessing, speculating, or providing information not found in the provided documentation. It will state it doesn't know rather than invent an answer.
-   **No General Conversation:** The agent is not a general-purpose chatbot. Its prompt and structure are designed for technical Q&A. It is not intended for chit-chat or off-topic conversation.
-   **No Long-Term Memory:** The agent's memory is scoped to a single invocation. Each new query starts a new, stateless session.
-   **Correctness over Helpfulness:** The agent prioritizes correctness and verifiability above all else. It will appear "unhelpful" if that is required to remain truthful to its source documentation.
-   **No Code Execution:** The agent can write and display code, but it cannot execute or validate it.

## 12. Client Integration Expectations

Downstream consumers (e.g., CLI, API, UI) must adhere to the following contract.

-   **Rely On `exit_reason`:** The `exit_reason` field is the authoritative source for understanding the agent's termination status. Use it to determine if the request completed successfully, failed, or hit a limit.
-   **Termination in Streaming:** When using `astream_events`, clients **must not** assume the last received token indicates completion. The only authoritative signal for termination is the emission of the final `AgentState` in the terminal event.
-   **Handling Cached Responses:** Clients must be designed to handle "instant" responses. If a query hits the LLM cache, the client will receive the final state without a preceding stream of tokens. UI layers should transition gracefully from a "thinking" state to the final answer in these cases.
-   **Display the Final Message:** The content of the final message in the `messages` list is intended for user display. In cases like `MAX_TURNS_REACHED` and `MAX_CONTEXT_REACHED`, this message is a canned response that should be shown verbatim.
-   **Handle Retryable Exits:** For `RATE_LIMITED`, the client should implement a backoff-and-retry strategy. For other retryable exits, the client should inform the user they can try again, possibly with a modified prompt.
-   **Do Not Assume a Definitive Answer:** The agent may validly respond that it does not have the information. Clients should be prepared to handle this "I don't know" state gracefully.
-   **Do Not Assume a Short Latency:** A single query may involve multiple sequential LLM and tool calls, leading to high latency. Clients should be designed to handle this asynchronous, multi-step process.
-   **Treat the Agent as Stateless:** Each call to the agent is independent. Clients are responsible for managing conversation history and passing it in the `messages` field if multi-turn conversation is desired.
