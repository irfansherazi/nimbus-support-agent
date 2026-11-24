# One image serves the API and the website. Build context: the repository root.

# ---- 1. Build the frontend as static files (same-origin API: NEXT_PUBLIC_API_URL left unset) ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN rm -f .env.development && npm run build

# ---- 2. Backend ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv

WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY data/ /srv/data/
COPY --from=web /web/out /srv/frontend
ENV STATIC_DIR=/srv/frontend
# Bake the tokenizer used by the chunker so the release step doesn't download it at boot.
RUN uv run --no-sync python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

EXPOSE 8000
# release = migrate + reset the demo CRM + ingest any changed policy docs
CMD ["sh", "-c", "uv run --no-sync python -m app.cli release && exec uv run --no-sync uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
