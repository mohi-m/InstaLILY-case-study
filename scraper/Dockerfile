# Build context is the repo root (see docker-compose.yml) so we can copy migrations.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

COPY scraper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium

COPY scraper/ ./
COPY backend/migrations ./migrations

# Headful Chromium needs a display; xvfb-run provides a virtual one in-container.
CMD ["xvfb-run", "-a", "python", "run.py"]
