# --- Stage 1: build the React console ---------------------------------------
FROM node:22-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ ./
RUN npm run build


# --- Stage 2: the API (serves the console it just built) ---------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code + migrations.
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini

# The policy docs ARE the RAG corpus — without them the policy engine silently
# falls back to its default thresholds, so routing would stop reflecting the docs.
COPY data ./data

# The built console (main.py prefers web/dist, falling back to ui/).
COPY --from=web /web/dist ./web/dist

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
