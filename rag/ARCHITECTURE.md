## Overview

This document outlines the architecture of the Somnia RAG (Retrieval-Augmented Generation) agent. This system is designed to provide accurate, citation-backed developer support for the Somnia ecosystem. It is engineered for determinism, debuggability, and resilience in the face of common failure modes.

A key architectural constraint is deterministic execution: given the same input state and retrieved context, the agent must follow the same execution path and termination behavior. This property is critical for debugging, observability, and downstream API integration.

Throughout this document, ‘agent’ refers to a LangGraph-based state machine composed of deterministic nodes operating over a shared AgentState.

The core of the agent is a state machine implemented using LangGraph. This choice was deliberate. While linear chains are simpler, they lack the flexibility required for a robust agent. LangGraph allows us to define a cyclical graph where the agent can loop, retry operations, and gracefully exit based on explicit conditions. This is critical for handling the unpredictable nature of user queries and external dependencies like LLM APIs and vector stores.

Our primary design goals are accuracy, safety, and observability. We prioritize providing grounded answers over speculative ones. Non-goals include open-ended conversational abilities or proactive task execution beyond answering developer questions based on provided documentation.

## High-Level Architecture

The system is modeled as a cyclic graph of nodes that manipulate a central state object. This architecture ensures a clear and predictable flow of data, making the agent's behavior easier to reason about.

-   **Agent Graph:** The central `StatefulGraph` instance orchestrates the entire process. It defines the nodes (logic) and edges (transitions) of our state machine.

-   **State Object:** An `AgentState` TypedDict holds all data relevant to a single query execution. This includes the conversation history, the number of turns, recent tool calls, and the final exit reason. The state is passed between nodes, each of which can modify it.

-   **LLM Node:** This node is responsible for invoking the Google Gemini chat model. It takes the current message history from the state, calls the LLM, and appends the model's response (which could be a direct answer or a tool-use request) back to the state.

-   **Tool Node (Retriever):** This node executes tool calls requested by the LLM. In our current implementation, its sole responsibility is to run vector-based document retrieval against our knowledge base. The results are then added to the state as a `ToolMessage`.

Data flows from the user's input, which initializes the agent state. The graph routes the state to the LLM node, which may decide to use the retriever tool. If so, the state is passed to the tool node, and the output is passed back to the LLM node for synthesis. This loop continues until the LLM generates a final answer or an exit condition is met.

## Agent State Model

The `AgentState` is a TypedDict that serves as the single source of truth for the agent's execution flow. We chose an explicit, centrally-managed state object over passing scattered parameters for clarity and debuggability. At any point in the graph's execution, the entire state of the world is inspectable.

Key fields include:

-   `messages`: A list of LangChain `BaseMessage` objects representing the full conversation history, including human, AI, and tool messages. This is the primary input for the LLM.
-   `turns`: An integer counter tracking the number of LLM-user interactions. This is a crucial safety mechanism to prevent infinite loops.
-   `tool_calls`: A list of tool calls made in the current turn. This allows the system to track tool execution and handle potential errors.
-   `exit_reason`: A string enum indicating why the agent terminated (e.g., `COMPLETED`, `MAX_TURNS_REACHED`). This is vital for observability and client-side handling of different outcomes.

By maintaining this explicit state, we can easily add new fields to track more complex behaviors without refactoring the core logic of every node. It also makes persistence and multi-turn conversation continuity (via a checkpointer) straightforward to implement.

## Execution Flow

The lifecycle of a single user query is a controlled loop within the LangGraph state machine. The agent can be executed in a blocking `invoke` mode or a real-time `astream_events` mode.

### Dual-Mode Execution: Synchronous and Asynchronous Paths

To support a wide range of integration patterns—from internal tools requiring quick, blocking responses to client-facing UIs demanding real-time updates—the agent is designed with dual synchronous (`.invoke()`) and asynchronous (`.ainvoke()` / `.astream_events()`) execution paths at the graph level.

This dual-mode capability is achieved using LangGraph's `RunnableLambda` with explicitly defined `func` (for synchronous execution) and `afunc` (for asynchronous execution) for each node (e.g., `llm_node`, `tool_node`). This pattern ensures:

*   **Synchronous Execution (`.invoke()`):** When the agent is invoked synchronously, LangGraph automatically dispatches calls to the `func` implementations of each node. This path uses `llm.invoke()` and `retriever.invoke()` for non-streaming, deterministic execution, suitable for environments where blocking calls are acceptable or even desired. Caching lookups and retry logic on this path are also synchronous.
*   **Asynchronous Execution (`.ainvoke()` / `.astream_events()`):** When the agent is invoked asynchronously (including streaming), LangGraph dispatches calls to the `afunc` implementations. This path uses `await llm.ainvoke()` and `await retriever.ainvoke()` to maintain non-blocking behavior and enables the `astream_events` mechanism for real-time token and event delivery. Asynchronous caching and retry mechanisms are engaged here.

This design ensures that the agent's core logic remains consistent across both modes, while the underlying I/O operations (LLM calls, tool execution, caching) are correctly handled in a blocking or non-blocking manner as appropriate for the invocation context.

### Preference for Streaming in External Clients

For external client-facing applications (e.g., web UIs, chat interfaces, CLI streaming output), asynchronous streaming (`.astream_events()`) is the preferred mode of interaction. This is primarily because:

1.  **Responsiveness:** Streaming provides a real-time, interactive user experience by delivering LLM tokens and tool events as they are generated, rather than waiting for the entire response to be synthesized.
2.  **Perceived Performance:** Users perceive the application as faster and more responsive when they see incremental progress, even if the total processing time is similar.
3.  **Non-Blocking I/O:** Asynchronous execution prevents blocking of the main application thread, crucial for scalable web servers and interactive UIs that need to handle multiple concurrent requests without degradation in performance.
4.  **Observability:** The event-driven pipeline offers granular insight into the agent's internal workings (e.g., tool calls, cache hits, intermediate thoughts), which can be surfaced to users for transparency and debugging.

While synchronous execution is fully supported and valuable for specific internal use cases (e.g., batch processing, unit testing, or simple script integrations), streaming is highly recommended for any scenario where user interaction or application responsiveness is critical.

1.  **Input:** A user query is received and used to initialize the `AgentState`.
2.  **LLM Invocation:** The state is passed to the LLM node. If a cached response exists, it is returned immediately. Otherwise, the model is invoked (optionally streaming tokens).
3.  **Conditional Edge (Tool Use):** If the LLM requests a tool (e.g., retrieval), the graph routes to the Tool Node.
4.  **Tool Execution:** The Tool Node executes document retrieval, utilizing caching and retries as necessary.
5.  **Looping:** The results are passed back to the LLM for synthesis.
6.  **Termination:** The loop concludes when a final answer is generated or a safety limit is hit. The `exit_reason` is set in the final state.

## Streaming & Event Pipeline

To support interactive user experiences, the agent implements a unified event-driven streaming pipeline using the `astream_events` protocol. This pipeline ensures that consumers receive a consistent stream of information, regardless of whether the LLM response is generated live or served from a cache.

-   **Event Emission:** During execution, the graph emits a sequence of events:
    -   `on_chat_model_stream`: Real-time token delivery when invoking the LLM live.
    -   `on_custom_event(name="cached_response")`: A single event containing the full assistant message when a response is served from the cache.
    -   `on_tool_start/end`: Observability into the retrieval process.
    -   `on_chain_end`: Delivery of the definitive final `AgentState`.

-   **Caching and Streaming Interplay:** An intentional architectural trade-off is made to balance performance, cost, and user experience:
    -   **Live Invocations:** When the LLM is called, tokens are streamed incrementally via `on_chat_model_stream` for a responsive UI.
    -   **Cached Invocations:** To avoid the latency and cost of re-invoking the LLM, cached responses are delivered in a single `cached_response` event. This avoids simulating token-by-token streaming, which would be inefficient and misleading.

This dual-path approach provides the responsiveness of live streaming with the efficiency of caching, all while presenting a unified event structure to the client.

-   **State as Source of Truth:** Regardless of the streaming events emitted, the final `AgentState` remains the single authoritative source of truth for the completion of a request and the final answer.

## Context Management & Safety

Aggressive context management is non-negotiable for a production RAG system. The LLM's context window is a finite and expensive resource. We employ several safety layers to manage it.

First, we use a message trimming mechanism. Before each LLM call, we calculate the expected character count of the `messages` list. If it exceeds `MAX_CONTEXT_CHARS` (12,000), we begin trimming messages. The system prompt is injected after trimming user and tool messages. This ensures that safety and behavioral constraints are never removed, even under aggressive context pressure. This preserves the most recent and relevant turns of the conversation.

Second, we have a hard guardrail. If, even after trimming, the context still exceeds the model's limit, we do not invoke the LLM. Instead, the agent exits immediately with the `exit_reason` set to `MAX_CONTEXT_REACHED`. This prevents API errors and ensures we fail safely and predictably.

## Caching & Reliability

The agent incorporates production-grade caching and retry logic to improve latency, reduce costs, and enhance resilience.

-   **Deterministic Caching:** Both retrieval results and LLM responses are cached using an in-memory `InMemoryCache`. Cache keys are generated via deterministic SHA-256 hashes of the request parameters (e.g., query, model, message payload). This ensures that identical requests yield consistent results and bypass expensive external calls.
-   **Tool & LLM Retries:** To handle transient network or service failures, the agent implements automatic retries with exponential backoff and jitter. This hardening layer ensures that the agent can recover from temporary hiccups in the LLM provider or vector store API without failing the entire reasoning turn.
-   **Abstraction for Scale:** The caching layer is designed with a clean `BaseCache` interface, allowing for future seamless replacement of the in-memory store with Redis or a disk-based solution as the system scales.

## Failure Modes & Exit Reasons

We explicitly model failure modes as terminal states in our graph. This is a core tenet of the agent's design, providing superior observability compared to letting exceptions bubble up. Each execution concludes with a clear `exit_reason`.

Known exit reasons include:
-   `COMPLETED`: The agent successfully answered the query.
-   `MAX_TURNS_REACHED`: The agent entered a loop and was terminated by the turn limit safety rail. This often points to a circular reasoning pattern in the LLM.
-   `RATE_LIMITED`: An API call to the LLM failed due to rate limiting. Capturing this allows a client to implement its own backoff-and-retry logic.
-   `MAX_CONTEXT_REACHED`: The conversation history grew too large to be safely handled, even after trimming.

Explicit exit reasons are invaluable for debugging and monitoring. An increase in `MAX_TURNS_REACHED` might flag an issue with the retrieval prompt or the quality of the documents. A spike in `RATE_LIMITED` indicates a need to adjust API usage patterns. This structured approach to failure makes the system transparent and easier to maintain.

Exit reasons form a stable contract between the agent and downstream clients, allowing UI layers, APIs, and DevRel tooling to react programmatically rather than parsing natural language output.

## Citations & Grounding

The agent's primary directive is to act as a faithful interface to the Somnia documentation. It is explicitly instructed to ground its answers in the documents retrieved by the tool.

We treat the retrieved context as the source of truth for a given query. The system prompt heavily penalizes speculation. If the answer is not present in the retrieved documents, the agent is designed to state that it does not have the information, rather than attempting to guess. This discipline is essential for building trust with developers, who rely on the accuracy of the provided information.

This refusal to speculate is a deliberate design choice. While a more conversational AI might try to provide a "helpful" but unverified answer, our RAG system prioritizes trustworthiness and reliability above all else. Every piece of information provided should be traceable back to a specific document.

The LLM is instructed to treat retrieved documents as authoritative context and to decline answers when relevant context is absent, rather than extrapolating from prior knowledge.

## Extensibility

The agent's graph-based architecture was chosen with extensibility in mind.

Adding new tools is straightforward. A developer can define a new tool function and add it to the list of tools available to the LLM. A corresponding node can be added to the graph to handle its execution, and new conditional edges can route the state accordingly. For instance, a tool that queries a live API for a service's status could be added alongside the document retriever.

The agent's invocation logic is self-contained, making it highly suitable for integration with various interfaces. For a REST API using FastAPI, a request handler would simply create an `AgentState` and invoke the graph, then return the final state as a JSON response. For a real-time chat application (e.g., Discord, Telegram), the same invocation logic can be wrapped in a task that streams back `AIMessage` and `ToolMessage` events as they are generated.

Because the state and execution are decoupled from the presentation layer, the core agent can be deployed across multiple platforms with minimal changes.

## Trade-offs & Future Improvements



This architecture represents a set of deliberate trade-offs aimed at building a robust and maintainable system.



While we have implemented in-memory caching and basic tool-retries, further improvements could include:

-   **Persistent Caching:** Migrating from in-memory to Redis or disk-based caching for persistence across restarts.

-   **Multi-Retriever System:** Evolving the single retriever into a multi-retriever system that can route queries to different specialized knowledge bases.

-   **Advanced Context Trimming:** Moving from character-based trimming to token-based trimming for even more precise context window management.



These features were intentionally deferred or implemented as simple abstractions to prioritize getting the core state management and grounding logic right first.



Premature optimization was intentionally avoided in favor of correctness, debuggability, and explicit failure handling, which are significantly harder to retrofit later.
