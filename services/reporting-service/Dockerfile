FROM python:3.11-slim

WORKDIR /app

# Install shared package first (available because build context is repo root)
COPY shared/ ./shared/
RUN pip install --no-cache-dir ./shared/

# Install service dependencies
COPY services/reporting-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY services/reporting-service/ .

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
