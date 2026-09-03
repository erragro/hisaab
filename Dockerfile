# Hisaab — single Cloud Run service (API + static frontend)
# Before the final submission, pin the digest:
#   docker pull python:3.13.7-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.13.7-slim
# then replace the tag with python:3.13.7-slim@sha256:<digest>
FROM python:3.13.7-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PORT=8080

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

# non-root
RUN useradd -m runner && chown -R runner /app
USER runner

EXPOSE 8080
# --workers 1: rate-limit burst state is per-process; the authoritative caps
# are in Firestore. Blocking work runs in Starlette's threadpool.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
