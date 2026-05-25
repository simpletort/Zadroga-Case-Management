FROM python:3.11-slim

WORKDIR /app

# Install shared package from repo root (available when build context is repo root)
COPY shared/ /tmp/shared/
RUN pip install --no-cache-dir /tmp/shared/

COPY services/task-management/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/task-management/ .

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
