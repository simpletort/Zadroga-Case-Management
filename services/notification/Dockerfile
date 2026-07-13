FROM python:3.11-slim

WORKDIR /app

# Install shared middleware package (build context must be repo root)
COPY shared/ ./shared/
RUN pip install --no-cache-dir ./shared/

# Install service dependencies
COPY services/notification/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY services/notification/ .

# Run as non-root (matches storage-gateway pattern)
RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
