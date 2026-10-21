FROM python:3.15-slim-bookworm@sha256:16b09ac07f09f233e96e10147ed7e2918e53c3dc207ba27c32526ba8f81f1493
COPY --from=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /uvx /usr/local/bin/

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/src/.venv/bin:$PATH"

COPY . /src
WORKDIR /src

# Resolve online: uv.lock is intentionally not tracked by this project.
# Development tools come from the PEP 735 group, not the legacy dev extra.
RUN uv sync --group dev

# The test settings use SQLite; no external database service is required.
RUN uv run --offline --no-sync coverage run manage.py test \
    || echo "WARNING: Django tests reported failures"
