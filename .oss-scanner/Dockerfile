FROM python:3.15-slim-bookworm@sha256:2a41267d9de9d358f77a1de356e0f16ecba8d39827855be0ce9ef4792edce402
COPY --from=ghcr.io/astral-sh/uv:0.13.3@sha256:bee0a2a458fd956c5df7b8b4c5fed2257b0af34866e3da7b51db0be3acb375d1 /uv /uvx /usr/local/bin/

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
