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

# Copy application
COPY . .

# Default: run on schedule via entrypoint.py.
# Override with: docker compose run morning-digest python pipeline.py --dry-run
# Re-run a single stage: docker compose run morning-digest python pipeline.py --stage synthesize
CMD ["python", "entrypoint.py"]
