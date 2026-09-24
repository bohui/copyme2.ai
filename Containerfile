FROM node:26-bookworm-slim

ARG CODEX_VERSION=0.156.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY docs ./docs
COPY infra ./infra
COPY scripts ./scripts

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/memory-spark-venv \
    && /opt/memory-spark-venv/bin/pip install --no-cache-dir --upgrade pip \
    && npm install --global --no-audit --no-fund npm@latest @openai/codex@${CODEX_VERSION} \
    && /opt/memory-spark-venv/bin/pip install --no-cache-dir .

ENV PATH=/opt/memory-spark-venv/bin:$PATH

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
