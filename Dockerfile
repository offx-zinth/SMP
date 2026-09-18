FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY smp/ ./smp/

RUN pip install --no-cache-dir -e .

# Run as a non-root user for production hardening.
RUN useradd --create-home --uid 10001 smp && \
    mkdir -p /app/.smp && chown -R smp:smp /app
USER smp

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/health')" || exit 1

CMD ["python", "-m", "smp.cli", "serve", "--host", "0.0.0.0", "--port", "8420"]
