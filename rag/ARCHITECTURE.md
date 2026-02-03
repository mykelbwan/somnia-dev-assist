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

The lifecycle of a single user query is a controlled loop within the LangGraph state machine.

1.  **Input:** A user query is received and used to initialize the `AgentState`, populating the `messages` list with a `HumanMessage`.

2.  **LLM Invocation:** The state is passed to the LLM node. The model is prompted to either answer the user's question directly or to use the provided retriever tool if it needs more information.

3.  **Conditional Edge (Tool Use):** The graph's primary conditional edge checks the most recent `AIMessage`. If it contains a `tool_calls` request, the state is routed to the Tool Node. Otherwise, if it's a direct answer, the state is routed to the termination point.

4.  **Tool Execution:** The Tool Node executes the requested retrieval, fetching relevant documents from the vector store. The results are packaged into a `ToolMessage` and appended to the `messages` list in the state.

5.  **Looping:** The state is passed back to the LLM node. The model now has the user's query, its previous thought process (the tool call request), and the retrieved documents. It uses this context to synthesize a grounded answer.

6.  **Termination:** The loop continues until the LLM provides an answer without requesting further tool use, or a safety limit (like `max_turns`) is hit. The `exit_reason` is set, and the final state is returned. This controlled loop prevents runaway execution and ensures every query concludes deterministically.

## Context Management & Safety

Aggressive context management is non-negotiable for a production RAG system. The LLM's context window is a finite and expensive resource. We employ several safety layers to manage it.

First, we use a message trimming mechanism. Before each LLM call, we calculate the expected token count of the `messages` list. If it exceeds a predefined safety threshold (e.g., 80% of the model's maximum context), we begin trimming messages. The system prompt is injected after trimming user and tool messages. This ensures that safety and behavioral constraints are never removed, even under aggressive context pressure. This preserves the most recent and relevant turns of the conversation.

Second, we have a hard guardrail. If, even after trimming, the context still exceeds the model's limit, we do not invoke the LLM. Instead, the agent exits immediately with the `exit_reason` set to `MAX_CONTEXT_REACHED`. This prevents API errors and ensures we fail safely and predictably. Avoiding an unsafe LLM call is always preferable to risking a crash or receiving a truncated, nonsensical response.

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

The current implementation is not fully streaming; it waits for the complete LLM response at each step. This simplifies state management but increases perceived latency. A future improvement is to enable streaming from the LLM and tool nodes, which would provide a more responsive user experience.

We have also deferred implementing sophisticated caching and tool-retry logic. Caching LLM calls and retrieval results could significantly reduce costs and latency for repeated queries. A more robust tool node would include automatic retries with exponential backoff for transient network errors.

Finally, the system currently uses a single, monolithic retriever. We plan to evolve this into a multi-retriever system, where the agent can choose the most appropriate knowledge base to query based on the user's question (e.g., routing to different vector stores for different Somnia services).

These features were intentionally deferred to prioritize getting the core state management, safety, and grounding logic right first. The current architecture provides a solid foundation upon which these improvements can now be built.

Premature optimization was intentionally avoided in favor of correctness, debuggability, and explicit failure handling, which are significantly harder to retrofit later.