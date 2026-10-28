# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.13-slim-bookworm AS builder

COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /ledger \
    && chown -R app:app /app /ledger

COPY --chown=app:app --from=builder /app/.venv /app/.venv

USER app
EXPOSE 8000

ENTRYPOINT ["beancount-mcp", "--host", "0.0.0.0", "/ledger/main.bean"]
