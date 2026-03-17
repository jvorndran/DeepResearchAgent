"""
API Dependencies

This file provides shared dependencies used across FastAPI route handlers.

Purpose:
- Verify Clerk JWT tokens for authentication
- Extract user_id from authenticated requests
- Provide reusable dependency functions

Main dependency:
- verify_clerk_token(): Validates the Bearer token in Authorization header
  - Extracts JWT from "Bearer <token>" format
  - Verifies signature using Clerk secret key
  - Checks expiration
  - Returns user_id for use in route handlers
  - Raises HTTPException for invalid/missing tokens

This ensures all protected endpoints require valid authentication before
processing requests, preventing unauthorized access to research jobs and artifacts.
"""

# TODO: Implement verify_clerk_token dependency
# TODO: Add JWT parsing and verification logic
# TODO: Extract user_id from token claims
# TODO: Handle token expiration and invalid signatures
# TODO: Return proper HTTPException errors for auth failures
