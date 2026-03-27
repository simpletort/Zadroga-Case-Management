FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user (consistent with other services)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

ENV PYTHONUNBUFFERED=1

CMD ["functions-framework", "--target=on_build_event", "--signature-type=cloudevent", "--port=8080"]
