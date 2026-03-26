# Product Requirements Document: Asynchronous Deep Financial Research Agent

## 1. Executive Summary

The Asynchronous Deep Financial Research Agent is an advanced, orchestration-driven platform designed to answer complex macroeconomic and stock market questions. Moving away from standard synchronous LLM chat interfaces, this product utilizes a long-running, asynchronous backend to fetch massive financial datasets, write custom analytical code, and execute that code in a secure sandbox.

The platform avoids browser timeouts and API rate-limit crashes by decoupling user interaction from the computational workload. This updated MVP focuses on providing hallucination-free financial reports complete with interactive data visualizations, secured by robust authentication, and powered by a best-in-class multi-model AI architecture.

## 2. Mission

To provide institutional-grade, transparent, and mathematically accurate financial research by strictly isolating LLM reasoning from raw data processing, while delivering a modern, interactive user experience.

**Core Principles:**

* **Factuality Over Fluency:** The system must never guess a financial metric; all insights must be derived from deterministically executed code.
* **Best-in-Class Routing:** Leverage the strongest models for specific tasks (OpenAI for code generation, Gemini for multi-step reasoning and synthesis).
* **Interactive Data:** Financial data must be explorable; static artifacts are insufficient for deep research.
* **Observable State:** Every step of the agent's thought process and execution must be logged and visible to the user.

## 3. Target Users

* **Quantitative Analysts:** Users needing rapid, automated backtesting and correlation matrices across disparate financial data sources.
* **Software Engineers:** Technical users managing complex agentic AI workflows who require high visibility into the data pipeline and retrieval steps.
* **Technical Retail Investors:** Users comfortable defining strict macroeconomic parameters to generate custom investment thesis reports.

## 4. MVP Scope

### Core Functionality

* ✅ Multi-turn clarifying chat interface to define research parameters.
* ✅ Asynchronous job queuing and status polling.
* ✅ Automated data fetching from financial APIs (FMP, FRED).
* ✅ Pure-Python schema extraction to prevent LLM hallucination.
* ✅ LLM-driven Pandas/SciPy code generation (via OpenAI Agents SDK).
* ✅ Output of structured JSON data payloads for frontend interactive charting.
* ✅ Final report synthesis using a strict Markdown template (via Gemini).
* ❌ Real-time trading execution or broker integration.

### Technical & Deployment

* ✅ Next.js frontend utilizing `shadcn/ui` and Recharts for interactive visualizations.
* ✅ Clerk for user authentication and session management.
* ✅ GCP Cloud Tasks for job enqueuing.
* ✅ LangGraph state machine orchestration.
* ✅ Containerized local/server-side execution sandbox.
* ✅ Google Cloud Storage (GCS) for artifact retention (Markdown and JSON payloads).

## 5. User Stories

* **As a quantitative analyst,** I want to ask for the correlation between TSMC's CapEx and silicon wafer shipping volumes, so that I can identify lagging indicators in the semiconductor market.
* **As a user reading the report,** I want to hover over the generated data charts to see specific data points and dates, so that I can interactively verify the mathematical conclusions.
* **As a technical user,** I want the agent to ask me clarifying questions about my timeframes and target tickers before it starts executing, so that I don't waste time and compute on the wrong assumptions.
* **As a developer,** I want the OpenAI Code Gen agent to output structured JSON arrays instead of static images, so that my Next.js `shadcn/ui` components can natively render the visualizations.
* **As a registered user,** I want to log in securely using Clerk, so that my past research reports are saved and tied exclusively to my account.

## 6. Core Architecture & Patterns

The system utilizes an **Asynchronous Orchestration Pattern** deployed on Google Cloud Platform (GCP).

* **Auth & Handoff:** The Next.js frontend authenticates the user via Clerk. Authenticated requests are sent to the Cloud Run API Gateway, which offloads the heavy processing to Cloud Tasks and returns a `job_id`.
* **Multi-Agent Orchestration Pattern:** The Cloud Run Job operates a LangChain Deep Agents system with role-based subagents. An Orchestrator (Gemini) acts as Research Director, delegating to specialized subagents: Data Engineer, Quantitative Developer, Technical Writer, and Quality Analyst. Each subagent has its own model assignment (OpenAI o1/o3 for code, Gemini for everything else).
* **Data Decoupling:** Raw data is routed directly to GCS/disk. Only storage paths and compact schemas are passed between subagents to prevent context bloat.

## 7. Role-Based Subagents

### Orchestrator (Gemini 3.0 Flash)
**Role:** Project Manager / Research Director

The Orchestrator is the main coordinator of the entire workflow.

**Responsibilities:**
* Parse and understand complex research queries
* Break down queries into delegatable tasks
* Route tasks to appropriate subagents
* Manage retry logic and error recovery (max 3 retries per subagent)
* Maintain conversation context across subagent handoffs
* Return final artifacts to the user

### Data Engineer (Gemini 3.0 Flash)
**Role:** Data Engineer / Data Analyst

The Data Engineer handles all data operations.

**Capabilities:**
* Fetch financial data from FMP and FRED APIs
* Save raw data to storage (GCS or local filesystem)
* Extract exact schemas from saved data (deterministic, no LLM)
* Return ONLY storage paths and compact metadata (never raw data)

**Key Principle:** Prevents context window bloat by keeping raw data out of agent conversations.

### Quantitative Developer (OpenAI o1/o3)
**Role:** Quantitative Developer / Quant Analyst

The Quantitative Developer writes and executes Python code for analysis.

**Capabilities:**
* Generate pandas/numpy/scipy analysis code from schemas
* Receive ONLY schemas (exact column names, dtypes, sample rows)
* Validate code syntax before execution
* Execute code in isolated Docker sandbox (no network access)
* Handle execution errors and retry with fixes
* Output structured JSON compatible with Recharts

**Key Principle:** Schema-based prompts prevent hallucinated column names.

### Technical Writer (Gemini 3.0 Flash)
**Role:** Technical Writer / Research Analyst

The Technical Writer synthesizes the final research report.

**Capabilities:**
* Generate Markdown reports using strict templates
* Extract key findings from execution results
* Embed references to chart_data.json (not static images)
* Write clear, accessible explanations
* Include proper financial disclaimers

**Key Principle:** Report embeds interactive chart references for frontend rendering.

### Quality Analyst (Gemini 3.0 Flash)
**Role:** Quality Analyst / Compliance Officer

The Quality Analyst is the final gatekeeper before artifacts are released.

**Capabilities:**
* Validate Markdown formatting
* Cross-check findings with execution results (no hallucinations)
* Ensure no predictive financial advice (compliance requirement)
* Verify chart references are correct
* Approve or reject for final upload

**Key Principle:** Nothing reaches the user without Quality Analyst approval.

## 8. Technology Stack

* **Frontend:** Next.js (React), Tailwind CSS, `shadcn/ui` (Components & Recharts).
* **Authentication:** Clerk.
* **Backend API:** Python, FastAPI.
* **AI/Orchestration:** LangChain Deep Agents, OpenAI API (o1/o3), Google Gemini API.
* **Data Processing:** Python, Pandas, NumPy, SciPy.
* **Cloud Infrastructure (GCP):**
  * Cloud Run (Sync API Gateway)
  * Cloud Tasks (Queue)
  * Cloud Run Jobs (Async Worker)
  * Cloud SQL (MySQL for agent context persistence)
  * Google Cloud Storage (GCS for artifacts)



## 9. Security & Configuration

* **Authentication:** Clerk handles all identity verification. The frontend passes the Clerk JWT to the backend, where it is verified before any jobs are initiated or artifacts retrieved.
* **Sandbox Isolation:** The Python Execution Sandbox is strictly containerized. It has no network access to the wider internet or the internal database.
* **Configuration:** All API keys (FMP, FRED, OpenAI, Gemini, Clerk secret) are stored in GCP Secret Manager and injected into the Cloud Run instances as environment variables.

## 10. API Specification

| Endpoint | Method | Payload | Description |
| --- | --- | --- | --- |
| `/api/research` | `POST` | `{"query": "string"}` | Requires Bearer Token. Enqueues job in Cloud Tasks. Returns `{"job_id": "123", "status": "accepted"}`. |
| `/api/status/{job_id}` | `GET` | N/A | Requires Bearer Token. Returns state of LangGraph DAG (e.g., `{"status": "running", "current_node": "code_gen"}`). |
| `/api/artifacts/{job_id}` | `GET` | N/A | Requires Bearer Token. Returns signed URLs for the GCS artifacts (Markdown, `chart_data.json`) once completed. |

## 11. Success Criteria

* ✅ **Job Stability:** 90% of initiated research tasks successfully complete without Cloud Run timeout errors.
* ✅ **Interactive Data Integration:** 100% of generated charts are rendered dynamically via Recharts using the JSON outputs generated by the sandbox.
* ✅ **Secure Access:** Only authenticated users can trigger pipelines or view their historical artifacts.
* ✅ **Factual Consistency:** Zero instances of hallucinated financial metrics in the final output; all numbers must map directly to the sandbox output.

## 12. Implementation Phases

**Phase 1: Local Deep Agents & Multi-Model Routing**

* **Goal:** Prove the Coordinator Agent delegation, OpenAI code generation, and JSON data output logic.
* **Deliverables:** ✅ Coordinator Agent with delegation tools, ✅ Specialist agents (Research, Schema, CodeGen), ✅ Agent-to-agent communication via tool calls.
* **Validation:** Pipeline generates a valid `chart_data.json` and Markdown file locally based on mock CSVs.

**Phase 2: Secure Execution & Context Persistence**

* **Goal:** Containerize the execution and add agent context persistence.
* **Deliverables:** ✅ Dockerized Sandbox, ✅ Database storage for agent conversation history.
* **Validation:** LLM code executes safely inside the container; agent context can be restored for debugging.

**Phase 3: Frontend & Auth Integration**

* **Goal:** Build the Next.js UI, `shadcn/ui` components, and Clerk auth.
* **Deliverables:** ✅ Next.js chat and polling UI, ✅ Clerk setup, ✅ Recharts data visualization layer.
* **Validation:** End-to-end local workflow functional via browser; users can log in, request a report, and interact with the resulting charts.

**Phase 4: GCP Migration**

* **Goal:** Move to production infrastructure.
* **Deliverables:** ✅ Cloud SQL setup, ✅ GCS buckets, ✅ Cloud Tasks deployment, ✅ Cloud Run API Gateway and Worker deployed.
* **Validation:** System handles long-running authenticated jobs in the cloud.

## 13. Future Considerations

* **Redis Caching Layer:** Implement a Memorystore cache for the Research Agent to prevent duplicate API calls for frequently requested macro data.
* **Custom Charting Instructions:** Allow users to dictate the type of interactive chart (e.g., "Use a radar chart for these three metrics") in the clarification phase.

## 14. Risks & Mitigations

1. **Risk:** The Code Gen agent hallucinates JSON structures that break the Recharts frontend component.
* **Mitigation:** Provide the OpenAI Code Gen prompt with a strict JSON schema template that exactly matches the expected props of the `shadcn/ui` chart component.


2. **Risk:** Context Window Bloat crashing the LLM.
* **Mitigation:** Strict enforcement of the Data Decoupling rule. Raw data never enters the prompt.


3. **Risk:** Infinite error-correction loops burning API credits.
* **Mitigation:** The Coordinator Agent tracks retry attempts in the conversation context. If execution fails 3 times, the coordinator terminates the workflow and returns an error to the user.
