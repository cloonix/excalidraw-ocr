# Multi-stage Dockerfile for OCR Application
# Pure Python implementation - no Node.js required

# Stage 1: Build stage with all build dependencies
FROM python:3.11-slim as builder

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy package files
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime stage (smaller final image)
FROM python:3.11-slim

# OCI Labels for metadata
LABEL org.opencontainers.image.title="AI-Powered OCR"
LABEL org.opencontainers.image.description="Extract text from handwritten images and Excalidraw drawings using AI vision models"
LABEL org.opencontainers.image.authors="OCR Project Contributors"
LABEL org.opencontainers.image.url="https://github.com/cloonix/excalidraw-ocr"
LABEL org.opencontainers.image.source="https://github.com/cloonix/excalidraw-ocr"
LABEL org.opencontainers.image.documentation="https://github.com/cloonix/excalidraw-ocr#readme"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.vendor="OCR Project"

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 ocruser && \
    mkdir -p /home/ocruser/.ocr/logs && \
    chown -R ocruser:ocruser /home/ocruser

# Set working directory
WORKDIR /app

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application files
COPY --chown=ocruser:ocruser *.py ./

# Create mount points
RUN mkdir -p /data && \
    chown ocruser:ocruser /data

# Switch to non-root user
USER ocruser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PATH="/app:${PATH}"

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=1 \
    CMD python --version || exit 1

# Default command shows help
CMD ["python", "ocr.py", "--help"]
