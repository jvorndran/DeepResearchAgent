"""
Research API Routes

This file handles the creation of new research jobs.

Endpoint: POST /api/research

Purpose:
- Accept research queries from authenticated users
- Create unique job ID
- Store job in database with "pending" status
- Enqueue job in Cloud Tasks (production) or trigger locally (development)
- Return job ID to frontend for status polling

Flow:
1. Verify Clerk JWT token → extract user_id
2. Validate request body (query must be non-empty)
3. Generate unique job_id (UUID)
4. Create ResearchJob database record
5. Enqueue job in Cloud Tasks or trigger LangGraph workflow
6. Return {"job_id": "...", "status": "accepted"}

Request body:
- query: str (the financial research question)

Response:
- job_id: str (unique identifier for polling)
- status: str ("accepted" or "enqueued")
"""

# TODO: Implement POST /api/research endpoint
# TODO: Add Clerk token verification dependency
# TODO: Generate unique job IDs
# TODO: Save job to database
# TODO: Integrate with Cloud Tasks or local LangGraph runner
# TODO: Define request/response Pydantic models
