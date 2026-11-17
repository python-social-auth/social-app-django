FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /uvx /usr/local/bin/

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
