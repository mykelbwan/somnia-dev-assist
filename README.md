# Somnia RAG API

## 1. Project Overview

This project exposes the Somnia RAG (Retrieval-Augmented Generation) agent through a FastAPI-based API. It provides both streaming endpoint for interacting with the agent, allowing developers to integrate its advanced question-answering capabilities into their applications.

The core of the project is a sophisticated RAG agent built with LangChain and LangGraph that can answer questions about a knowledge base. This API layer provides a clean, modern interface to that agent without duplicating its logic.

## 2. Architecture

The project is divided into two main components:

- **`rag/`**: The core RAG agent. This directory contains all the logic for the LangChain graph, including the LLM, retrievers, state management, and tool definitions. It is a self-contained Python package that can be used independently of the API.
- **`api/`**: The FastAPI application that wraps the RAG agent. This layer is responsible for handling HTTP requests, validating data, and exposing the agent's functionality over the web. It is designed to be a thin and clean interface, with all business logic remaining within the `rag/` directory.

This separation of concerns ensures that the agent's logic can be developed and tested independently from the API, and that the API can be evolved without impacting the core agent.

## 3. How to Run Locally

### Prerequisites

- Python 3.9+
- `uv`

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/mykelbwan/somnia-dev-assist
    cd somnia-dev-assist
    ```

2.  **Set up the environment:**
    Create a `.env` file from the example and add your `GEMINI_API_KEY`:
    ```bash
    cp .env.example .env
    echo "GEMINI_API_KEY=your_api_key_here" >> .env
    ```

3.  **Install dependencies:**
```bash
    uv add -r requirements.txt
 ```
    *(If you don't have `uv`, you can use `pip install -r requirements.txt`)*

### Running the CLI

The original CLI functionality remains intact. You can run it to interact with the agent directly from your terminal.

first ingest the documents via this command:
```bash
uv run rag/ingest.py
```

- **Non Streaming.**
```bash
uv run rag/cli.py
```

-   **Streaming:**
 ```bash
uv run rag/cli.py --stream
```

### Running the API

To run the FastAPI server:

```bash
PYTHONPATH=$(pwd):$(pwd)/rag uv run python -m main
```

The API will be available at `http://0.0.0.0:8000`.

## 4. Example API Usage

### Streaming (`/api/chat/stream`)

This endpoint uses Server-Sent Events (SSE) to stream the agent's response as it's being generated. This is ideal for real-time applications.

**Request:**

```bash
curl -N -X 'POST' 
  'http://0.0.0.0:8000/api/chat/stream' 
  -H 'accept: application/json' 
  -H 'Content-Type: application/json' 
  -d '{
  "query": "What are the main features of the Somnia RAG agent?"
}'
```

**Response Stream:**

The response is a stream of events. Here is an example:

```
data: {"type": "token", "content": "The"}

data: {"type": "token", "content": " Somnia"}

data: {"type": "token", "content": " RAG"}

data: {"type": "tool_start", "name": "retriever", "input": {"query": "Somnia RAG agent features"}}

data: {"type": "tool_end", "name": "retriever", "output": "..."}

data: {"type": "token", "content": " agent"}

data: {"type": "token", "content": " has"}

data: {"type": "token", "content": " several"}

data: {"type": "token", "content": " key"}

data: {"type": "token", "content": " features..."}

data: {"type": "final_reason", "exit_reason": "COMPLETED"}
```

## 5. Caching and Streaming Behavior

The agent uses an in-memory cache for both LLM responses and tool calls to improve performance and reduce costs.

-   **Live Response:** When a query is not in the cache, the agent processes it live. The streaming endpoint will yield events as they happen: `token` events as the LLM generates text, `tool_start` and `tool_end` as tools are called, and finally a `final_reason` event.
-   **Cached Response:** If the same query is made again, the agent may return a cached response. For the streaming endpoint, the API simulates a stream by dispatching a `cached_response` event containing the full text. This ensures that clients can handle both live and cached responses with the same logic. A `final_reason` event is still sent at the end.

## 6. Understanding `exit_reason`

Every response, whether streaming or non-streaming, includes an `exit_reason`. This field tells the client why the agent stopped processing. Clients should use this to understand the outcome of their query.

Common `exit_reason` values:

-   `COMPLETED`: The agent finished successfully.
-   `MAX_TURNS_REACHED`: The agent took too many steps and was stopped to prevent infinite loops.
-   `RATE_LIMITED`: The underlying AI model is temporarily rate-limited. The client should retry after a short delay.
-   `MAX_CONTEXT_REACHED`: The conversation history is too long. The client should suggest starting a new conversation.
-   `EMPTY_INPUT`: The query was empty or contained only whitespace.
-   `LLM_ERROR`: An unexpected error occurred in the language model.

By inspecting the `exit_reason`, clients can build more robust and user-friendly applications.
