FROM python:3.12-slim

LABEL maintainer="Aaron"
LABEL description="Morning Digest — daily briefing email generator"

# Avoid Python buffering (important for Docker logging)
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Denver
# Shared Playwright browser location so browsers installed at build time (as
# root, which is required for the apt system libs) are usable by the non-root
# runtime user below.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Install dependencies and Playwright/crawl4ai browsers + system libs as root,
# then make the browser cache world-readable for the non-root runtime user.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && crawl4ai-setup \
    && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

# Run as a non-root user whose UID/GID match the host dev/prod user, so that
# bind-mounted output/ and cache/ files are owned by that user instead of root.
# Override APP_UID/APP_GID at build time for hosts where the user isn't 1000
# (e.g. `docker compose build --build-arg APP_UID=99 --build-arg APP_GID=100`).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /bin/bash app \
    && mkdir -p /app/cache/weather /app/output

# Copy application and hand the whole tree to the non-root user.
COPY . .
RUN chown -R app:app /app

USER app

# Health check: verify the scheduler process is alive.
# A simple process check avoids false "unhealthy" reports between daily digest runs.
HEALTHCHECK --interval=1h --timeout=5s --start-period=30s --retries=1 \
  CMD pgrep -f entrypoint.py || pgrep -f pipeline.py || exit 1

# Default: run on schedule via entrypoint.py.
# Override with: docker compose run morning-digest python pipeline.py --dry-run
# Re-run a single stage: docker compose run morning-digest python pipeline.py --stage synthesize
CMD ["python", "entrypoint.py"]
