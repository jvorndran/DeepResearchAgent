"""
External Services Module

This module will contain clients for interacting with external APIs and cloud services.

Planned service modules:

1. fmp.py - Financial Modeling Prep API Client
   - Fetch stock prices, financial statements, company data
   - Handle API key authentication
   - Rate limiting and retry logic
   - Data normalization to consistent format

2. fred.py - Federal Reserve Economic Data (FRED) API Client
   - Fetch macroeconomic indicators (GDP, inflation, unemployment, etc.)
   - Time series data retrieval
   - Handle API key authentication
   - Data normalization

3. gcs.py - Google Cloud Storage Client
   - Upload artifacts (CSV, JSON, Markdown)
   - Generate signed URLs for frontend access
   - Manage bucket organization by user/job
   - Handle file lifecycle (retention, cleanup)

4. cloud_tasks.py - Google Cloud Tasks Client
   - Enqueue research jobs
   - Handle task creation and routing
   - Configure retry policies
   - Integration with Cloud Run Jobs

Each service module should:
- Provide a clean, typed interface
- Handle authentication and credentials
- Implement retry logic for transient failures
- Normalize data to consistent format
- Raise clear exceptions for errors
- Log API calls for debugging

These services are used by:
- Research Node (fmp.py, fred.py)
- Execution Node (gcs.py for data storage)
- API routes (cloud_tasks.py for job enqueuing, gcs.py for artifacts)
"""

# Service modules will be implemented as needed
# Each will be a separate .py file in this directory
