"""
Status and Artifacts API Routes

This file handles job status polling and artifact retrieval.

Endpoints:
1. GET /api/status/{job_id}
2. GET /api/artifacts/{job_id}

Purpose:
- Allow frontend to poll for job progress
- Provide access to completed artifacts (Markdown, chart data)
- Ensure users can only access their own jobs

GET /api/status/{job_id}:
- Returns current job status and active LangGraph node
- Response: {"status": "running", "current_node": "code_gen", "error_message": null}
- Frontend polls this endpoint every few seconds

GET /api/artifacts/{job_id}:
- Returns signed GCS URLs for Markdown report and chart_data.json
- Only available when status is "completed"
- Response: {"markdown_url": "...", "chart_data_url": "..."}
- URLs are time-limited signed URLs for security

Both endpoints:
- Require authentication (Clerk JWT)
- Verify user owns the job (user_id match)
- Return 404 if job not found
- Return 403 if user doesn't own the job
"""

# TODO: Implement GET /api/status/{job_id} endpoint
# TODO: Implement GET /api/artifacts/{job_id} endpoint
# TODO: Add Clerk token verification
# TODO: Verify job ownership (user_id match)
# TODO: Generate GCS signed URLs for artifacts
# TODO: Define response Pydantic models
