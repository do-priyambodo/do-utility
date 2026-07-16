# Container Dockerfile for Cloud Run / Cloud Functions Gen 2
# Official Playwright Python image pre-loaded with Chromium and OS C libraries
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install minimal system tools required for weasyprint cairo binding
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies and install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Run our Python script directly (for Cloud Run Jobs / continuous background execution)
CMD ["python3", "main.py"]
