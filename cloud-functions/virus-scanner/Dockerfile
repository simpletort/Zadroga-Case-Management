# Cloud Function Gen 2 — custom container with ClamAV pre-installed.
#
# ClamAV virus definitions are updated at build time so cold-start
# latency stays low.  Cloud Build should rebuild this image at least
# weekly to keep definitions current.
#
# The functions-framework entry point must be "virus_scan" (the decorated
# function in main.py).

FROM python:3.11-slim

# Install ClamAV and update definitions at build time.
# hadolint ignore=DL3008,DL3015
RUN apt-get update \
    && apt-get install -y --no-install-recommends clamav clamav-daemon \
    && freshclam \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for principle of least privilege
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# functions-framework listens on 8080 by default
ENV PORT=8080

CMD ["functions-framework", "--target=virus_scan", "--signature-type=cloudevent", "--port=8080"]
