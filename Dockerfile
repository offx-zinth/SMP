FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY smp/ ./smp/

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8420

CMD ["python3.11", "-m", "smp.cli", "serve", "--host", "0.0.0.0", "--port", "8420"]