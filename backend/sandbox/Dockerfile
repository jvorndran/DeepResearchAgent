# ==========================================
# EXECUTION SANDBOX DOCKERFILE
# ==========================================
# Minimal Python environment for running generated code
# NO NETWORK ACCESS - Security isolated

FROM python:3.11-slim

# Set working directory
WORKDIR /workspace

# Install only necessary data science packages
RUN pip install --no-cache-dir \
    pandas==2.2.3 \
    numpy==2.2.0 \
    scipy==1.14.1 \
    matplotlib==3.9.0

# Create non-root user for execution
RUN useradd -m -u 1000 sandbox && \
    chown -R sandbox:sandbox /workspace

USER sandbox

# Default command (overridden at runtime)
CMD ["python", "--version"]
