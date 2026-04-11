FROM python:3.12-slim

LABEL maintainer="Aaron"
LABEL description="Morning Digest — daily briefing email generator"

# Avoid Python buffering (important for Docker logging)
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Denver

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create cache directory for weather data
RUN mkdir -p /app/cache/weather

# Copy application
COPY . .

# Health check: verify the log file was written to in the last 25 hours.
# This catches silent crashes or hangs in the entrypoint scheduler loop.
HEALTHCHECK --interval=1h --timeout=5s --start-period=30s --retries=1 \
  CMD find /app/output/digest.log -mmin -1500 | grep -q . || exit 1

# Default: run on schedule via entrypoint.py.
# Override with: docker compose run morning-digest python pipeline.py --dry-run
# Re-run a single stage: docker compose run morning-digest python pipeline.py --stage synthesize
CMD ["python", "entrypoint.py"]
