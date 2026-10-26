FROM node:26-bookworm-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates python3 python3-venv ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/memory-spark-venv \
    && /opt/memory-spark-venv/bin/pip install --no-cache-dir --upgrade pip

ENV PATH=/opt/memory-spark-venv/bin:$PATH

# Resolve dependencies from the manifest before frequently changing source files.
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -c 'import tomllib; m=tomllib.load(open("pyproject.toml", "rb")); p=m["project"]; print("\n".join(m["build-system"]["requires"] + p["dependencies"] + [d for e in ("photo-browser", "lifetime-memory") for d in p["optional-dependencies"][e]]))' > /tmp/memory-spark-requirements.txt \
    && pip install -r /tmp/memory-spark-requirements.txt \
    && rm /tmp/memory-spark-requirements.txt \
    && python -m playwright install --with-deps chromium

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Local Compose mounts application files onto this stable dependency image.
FROM runtime AS app

COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
RUN pip install --no-cache-dir --no-deps --no-build-isolation '.[photo-browser,lifetime-memory]'

COPY README.md ./
COPY apps/web/public ./apps/web/public
COPY skills ./skills
COPY experiments/novel-to-game ./experiments/novel-to-game
COPY deps ./deps
COPY docs ./docs
COPY infra ./infra
COPY scripts ./scripts
