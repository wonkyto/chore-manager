ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.8

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-slim AS base

COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS dev
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra dev
EXPOSE 5000
CMD ["uv", "run", "python", "-m", "chore_manager"]

FROM base AS production
RUN groupadd --system --gid 1000 chore \
    && useradd --system --uid 1000 --gid chore --create-home chore \
    && mkdir -p /app/data /app/instance \
    && chown -R chore:chore /app
COPY --chown=chore:chore pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project \
    && chown -R chore:chore /app/.venv
COPY --chown=chore:chore src/ ./src/
COPY --chown=chore:chore config/ ./config/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev \
    && chown -R chore:chore /app/.venv
USER chore
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:5000/ >/dev/null || exit 1
CMD ["uv", "run", "python", "-m", "chore_manager"]
