# syntax=docker/dockerfile:1.7
# Tastoria backend image: api, worker, migrate and scheduler run from it (ADR 0001, ADR 0003).
# Build context: repository root (see backend.Dockerfile.dockerignore).

FROM ghcr.io/astral-sh/uv:0.9.28 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Dependencies first (cached while only source changes). Both workspace members are installed:
# tastoria-ml carries the reference nutrition engine the catalog import uses (backend/README.md, slice 2).
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace
COPY backend/src backend/src
COPY ml/src ml/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-editable

FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 tastoria \
 && useradd --system --uid 10001 --gid tastoria --home-dir /app --shell /usr/sbin/nologin tastoria \
 && mkdir -p /app/data /var/lib/tastoria/storage \
 && chown -R tastoria:tastoria /var/lib/tastoria
COPY --from=build /opt/venv /opt/venv
# Catalog bundle + the composition tables the import reads (data/processed/{fct2007,usda}).
COPY data/kb /app/data/kb
COPY data/processed/fct2007 /app/data/processed/fct2007
COPY data/processed/usda /app/data/processed/usda
COPY deploy/scripts/scheduler.sh /app/scheduler.sh
COPY deploy/scripts/models-bootstrap.sh /app/models-bootstrap.sh
WORKDIR /app
USER tastoria
EXPOSE 8000
CMD ["uvicorn", "tastoria.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
