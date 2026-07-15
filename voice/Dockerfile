# The voice workers (support agent + approval-call agent). One image, two commands —
# they share every dependency and differ only in which entrypoint they register.
#
# Build from the REPO ROOT:  docker build -f voice/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY voice/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY voice/ ./

# `start` is the production worker mode (`dev` adds hot-reload and verbose logs).
# The support agent auto-dispatches into rooms; the approver agent registers an
# explicit agent_name and is dispatched on demand — see docker-compose.yml.
CMD ["python", "agent.py", "start"]
