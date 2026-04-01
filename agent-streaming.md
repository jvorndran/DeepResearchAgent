# DeepResearchAgent: Frontend-Backend Architecture & Streaming Flow

This document outlines the architecture, communication protocols, and event streaming mechanisms used to connect the Next.js frontend to the FastAPI/LangGraph backend in the DeepResearchAgent application.

## 1. High-Level Architecture

The application uses a modern decoupled architecture:

- **Frontend**: Next.js (React) application utilizing the Vercel AI SDK (`@ai-sdk/react`). It manages the UI state, chat history, and renders the final research reports.
- **Backend**: FastAPI server running a LangChain/LangGraph "Deep Agent" orchestrator. It handles the heavy lifting of reasoning, delegating tasks to subagents (Data Engineer, Quant Developer, etc.), and executing tools via MCP (Model Context Protocol).

The two communicate over HTTP, specifically using **Server-Sent Events (SSE)** to stream real-time updates from the backend's agent graph directly into the frontend's UI.

---

## 2. The Communication Protocol: Vercel AI SDK Data Stream

To seamlessly integrate the complex, multi-agent backend with the React frontend, the backend formats its output to comply with the **Vercel AI SDK Data Stream Protocol**.

This protocol defines specific prefixes for different types of streamed data:

- `0:"..."\n` — **Text**: Standard LLM text tokens (what the user reads in the chat).
- `2:[{...}]\n` — **Data/Custom**: Structured JSON data arrays (used for subagent updates, tool calls, and state changes).
- `3:"..."\n` — **Error**: Error messages.

### Why this matters
By adhering to this protocol, the frontend can simply use the `useChat` hook from `@ai-sdk/react`. The hook automatically parses the incoming stream, appends text to the `messages` array, and places structured updates into the `data` array, completely abstracting away the complexity of SSE parsing.

---

## 3. The End-to-End Flow: From Question to Report

Here is the step-by-step lifecycle of a research request.

### Phase 1: Initialization & Chatting
1. **User Input**: The user enters a query in the `InitialPrompt` component on the frontend.
2. **Frontend Request**: The `useChat` hook's `sendMessage` function sends a `POST` request to `http://localhost:8000/api/chat/stream`. The payload includes the entire conversation history and a unique `job_id`.
3. **Backend Routing**: FastAPI receives the request in `main.py` (`@app.post("/api/chat/stream")`). It extracts the latest query and the `job_id`.
4. **Agent Invocation**: The backend calls `stream_research` from `orchestrator.py`. Crucially, it passes the *pre-initialized* agent (stored in `app.state.agent` during server startup) to avoid re-registering MCP tools on every request.
5. **Streaming Text**: As the Orchestrator agent thinks and responds (e.g., asking clarifying questions), LangGraph yields `messages` chunks. The FastAPI server formats these as `0:"text"` and yields them to the HTTP response.
6. **Frontend Render**: The `useChat` hook updates the `messages` state, and the `ChatPanel` renders the assistant's text bubble.

### Phase 2: Transitioning to the "Generating" Pipeline
1. **User Confirmation**: Once the scope is clarified, the user clicks "Begin research". The frontend sends a final message: *"I am ready. Please begin the research."*
2. **Agent Delegation**: The Orchestrator agent decides it has enough information and uses its `task()` tool to delegate work to a subagent (e.g., the `data-engineer`).
3. **Streaming Updates**: LangGraph detects the subagent invocation because we enabled `subgraphs=True` in the `astream` call. It yields an `updates` chunk containing the tool call details.
4. **FastAPI Formatting**: `main.py` catches this `updates` chunk, serializes the complex LangGraph state objects into pure JSON, and yields it as a data chunk: `2:[{"type": "update", "ns": ["tools:data-engineer"], ...}]`.
5. **Frontend Phase Shift**: The frontend has a `useEffect` hook listening to the `data` array from `useChat`. When it detects a data item where `type === "update"` and the namespace (`ns`) starts with `"tools:"`, it knows the backend has moved from chatting to background processing.
6. **UI Update**: The frontend immediately changes its internal `phase` state from `"chatting"` to `"generating"`. The chat UI hides, and the `GenerationLoading` component mounts, showing the progress tracker.

### Phase 3: Background Processing & Completion
1. **Subagent Execution**: The backend continues running the LangGraph workflow. The Data Engineer fetches data via FMP/FRED MCPs, the Quant Developer writes and runs Python code, and the Technical Writer generates the final markdown and JSON charts.
2. **Continuous Streaming**: Throughout this process, FastAPI continues to stream `updates` and `custom` events to the frontend, which could theoretically be used to update specific steps in the loading UI.
3. **Stream Closure**: Once the Quality Analyst approves the report and the Orchestrator finishes its final node, the LangGraph `astream` generator is exhausted. The FastAPI `StreamingResponse` closes the HTTP connection.
4. **Frontend Completion**: The `useChat` hook detects the closed connection and fires its `onFinish` callback.
5. **Final Render**: The frontend's `onFinish` handler changes the `phase` state to `"completed"`. The `ResultsPanel` mounts, reads the generated `report.json` and `charts.json` from the backend (or local storage, depending on implementation), and renders the final interactive research report.

---

## 4. Key Code Locations

- **Frontend State Management**: `frontend/app/chat/page.tsx` (Manages `phase` transitions and `useChat` configuration).
- **Backend Stream Formatting**: `backend/main.py` (`chat_stream` function handles the conversion of LangGraph chunks to Vercel AI SDK format).
- **Agent Streaming Config**: `backend/agents/orchestrator.py` (`stream_research` function configures `agent.astream` with `stream_mode=["updates", "messages", "custom"]` and `subgraphs=True`).