# Use a small, stable Debian-based python image (good balance of minimal and compatibility)
FROM python:3.12-slim

# Avoid generation of .pyc files and buffer stdout so logs show up immediately
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install only what we need. watchdog wheel is available for many platforms, so no build tools typically required.
# If pip needs to compile, you can add build deps; but that increases image size.
RUN pip install --no-cache-dir watchdog

# Copy app
COPY watch_and_copy.py /app/watch_and_copy.py

# Use a non-root user by default? We'll keep root but recommend running container with --user to match host UID/GID.
# Expose nothing (this is a worker)
CMD ["python", "watch_and_copy.py"]

