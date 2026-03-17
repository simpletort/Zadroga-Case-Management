FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for principle of least privilege
RUN adduser --disabled-password --gecos "" appuser
USER appuser

ENV PORT=8080

CMD ["functions-framework", "--target=sync_drive_files", "--signature-type=http", "--port=8080"]
