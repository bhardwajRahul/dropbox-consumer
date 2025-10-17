# Use a small, stable Debian-based python image (good balance of minimal and compatibility)
FROM python:3.12-slim

# Metadata labels for Docker Hub
LABEL maintainer="john-lazarus"
LABEL org.opencontainers.image.title="Dropbox Consumer"
LABEL org.opencontainers.image.description="A robust file monitoring service for seamless document processing and file synchronization"
LABEL org.opencontainers.image.url="https://github.com/john-lazarus/dropbox-consumer"
LABEL org.opencontainers.image.source="https://github.com/john-lazarus/dropbox-consumer"
LABEL org.opencontainers.image.vendor="john-lazarus"
LABEL org.opencontainers.image.licenses="https://github.com/john-lazarus/dropbox-consumer/blob/main/LICENSE"
LABEL org.opencontainers.image.documentation="https://github.com/john-lazarus/dropbox-consumer#readme"

# Avoid generation of .pyc files and buffer stdout so logs show up immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install only what we need. watchdog wheel is available for many platforms, so no build tools typically required.
# If pip needs to compile, you can add build deps; but that increases image size.
RUN pip install --no-cache-dir watchdog

# Copy the Python modules and main application
COPY src/ /app/src/
COPY main.py /app/main.py

# Create state directory (logs are handled by Docker)
RUN mkdir -p /app/state
USER appuser

# Expose configuration via environment variables
ENV SOURCE=/source \
    DEST=/consume \
    PRESERVE_DIRS=false \
    RECURSIVE=true \
    COPY_EMPTY_DIRS=false

# Health check - verify service is running by checking health file freshness
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD test -f /tmp/health && [ $(( $(date +%s) - $(cat /tmp/health) )) -lt 60 ] || exit 1

# Run the application
CMD ["python", "main.py"]

