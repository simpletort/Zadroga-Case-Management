# # # Multi-stage build for ZAD Lead Intake API (Cloud Run)

# # # ── Stage 1: Build dependencies ──────────────────────────────────────────────
# # FROM python:3.12-slim AS builder

# # WORKDIR /build
# # RUN apt-get update && apt-get install -y --no-install-recommends \
# #     gcc libffi-dev && \
# #     rm -rf /var/lib/apt/lists/*

# # COPY services/lead-intake/api/requirements.txt .
# # COPY shared/ /build/shared/
# # RUN pip install --no-cache-dir -r requirements.txt && \
# #     pip install --no-cache-dir /build/shared/

# # # ── Stage 2: Runtime image ────────────────────────────────────────────────────
# # FROM python:3.12-slim AS runtime

# # WORKDIR /app

# # COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
# # COPY --from=builder /usr/local/bin /usr/local/bin
# # COPY services/lead-intake/api/ /app/
# # COPY shared/ /shared/

# # ENV PYTHONUNBUFFERED=1 \
# #     PYTHONDONTWRITEBYTECODE=1 \
# #     PORT=8080

# # RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
# # USER appuser

# # EXPOSE 8080

# # HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
# #     CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# # CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--log-level", "info"]


# # Multi-stage build for ZAD Lead Intake API (Cloud Run)

# # ── Stage 1: Build dependencies ──────────────────────────────────────────────
# FROM python:3.12-slim AS builder

# WORKDIR /build
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc libffi-dev && \
#     rm -rf /var/lib/apt/lists/*

# # Install Python dependencies
# COPY services/lead-intake/api/requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Install shared package from repo root
# COPY shared/ /build/shared/
# RUN pip install --no-cache-dir /build/shared/

# # ── Stage 2: Runtime image ────────────────────────────────────────────────────
# FROM python:3.12-slim AS runtime

# WORKDIR /app

# COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
# COPY --from=builder /usr/local/bin /usr/local/bin

# # Copy service code
# COPY services/lead-intake/api/ /app/

# ENV PYTHONUNBUFFERED=1 \
#     PYTHONDONTWRITEBYTECODE=1 \
#     PORT=8080

# RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
# USER appuser

# EXPOSE 8080

# HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
#     CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--log-level", "info"]

# Dockerfile for ZAD Lead Intake API (Cloud Run)
# Build context must be the repo root so we can COPY shared/.
# The cloudbuild.yaml already uses "." as the build context — this matches.

# ── Stage 1: Build dependencies ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install shared package first so it's available as an importable package
COPY shared/ /build/shared/
RUN pip install --no-cache-dir /build/shared/

# Install service dependencies
COPY services/lead-intake/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder (includes shared + all deps)
COPY --from=builder /usr/local/lib/python3.12/site-packages \
                    /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy service source
COPY services/lead-intake/api/ /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "2", "--log-level", "info"]