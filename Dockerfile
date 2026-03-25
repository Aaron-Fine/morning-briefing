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

# Default: run on schedule.
# Override with: docker compose run morning-digest python digest.py --dry-run
CMD ["python", "entrypoint.py"]
