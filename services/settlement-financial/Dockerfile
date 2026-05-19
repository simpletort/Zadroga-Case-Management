FROM python:3.11-slim

WORKDIR /app

# System libs required by reportlab (fonts) and pillow (image formats)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    libjpeg62-turbo \
    libpng16-16 \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Install shared package (build context must be repo root)
COPY shared/ ./shared/
RUN pip install --no-cache-dir ./shared/

# Install service dependencies
COPY services/settlement-financial/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY services/settlement-financial/ .

# Run as non-root
RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
