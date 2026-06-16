FROM python:3.11-slim

WORKDIR /app

# Install shared package from repo root (available when build context is repo root)
COPY shared/ /tmp/shared/
RUN pip install --no-cache-dir /tmp/shared/

COPY services/auth-rbac-cr/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/auth-rbac-cr/ .

RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
