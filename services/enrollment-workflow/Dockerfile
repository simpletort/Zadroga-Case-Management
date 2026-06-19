FROM python:3.11-slim AS builder
WORKDIR /app

# Install shared package (build context is repo root so shared/ is accessible)
COPY shared/ /tmp/shared/
RUN pip install --no-cache-dir /tmp/shared/

COPY services/enrollment-workflow/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/gunicorn /usr/local/bin/gunicorn
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy application code
COPY services/enrollment-workflow/app.py services/enrollment-workflow/config.py services/enrollment-workflow/logging_config.py ./
COPY services/enrollment-workflow/routers/ ./routers/
COPY services/enrollment-workflow/models/ ./models/
COPY services/enrollment-workflow/services/ ./services/

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "120", "app:app"]
