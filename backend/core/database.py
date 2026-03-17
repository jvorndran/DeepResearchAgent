"""
Database Configuration and Models

This file sets up SQLAlchemy for database connections and defines the data models
for persisting job state and metadata.

Purpose:
- Configure SQLAlchemy engine and session
- Define database models (tables)
- Provide database session dependency for FastAPI routes
- Handle both SQLite (local) and PostgreSQL (production) connections

Models:
- ResearchJob: Tracks each research request with fields:
  - id (job_id)
  - user_id (from Clerk)
  - query (user's research question)
  - status (pending, running, completed, failed)
  - current_node (which LangGraph node is executing)
  - timestamps (created_at, updated_at, completed_at)
  - artifact URLs (markdown_url, chart_data_url)
  - error messages
  - state snapshot (JSON of LangGraph state for resume/debugging)

The database allows:
- Job status polling by frontend
- Resume interrupted jobs using LangGraph checkpointing
- User history and artifact retrieval
- Error tracking and debugging
"""

# TODO: Implement SQLAlchemy engine configuration
# TODO: Create SessionLocal factory
# TODO: Define Base declarative class
# TODO: Define ResearchJob model with all fields
# TODO: Implement get_db() dependency function for FastAPI
# TODO: Add database initialization logic
