# Multi-stage build: keep the runtime image lean by installing deps in a
# builder stage and copying only the resolved virtualenv into the final image.
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN pip install --no-cache-dir "poetry>=1.8"

WORKDIR /app

# Install dependencies first so iterative source edits don't bust the cache.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

# Now copy the source and install the package itself.
COPY src ./src
RUN poetry install --only main

# ---- runtime stage ----------------------------------------------------------

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Pull in the resolved venv + the package source.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY pyproject.toml poetry.lock ./

# Cache + traces live under a mounted volume by default.
RUN mkdir -p /root/.oqe

ENTRYPOINT ["oqe"]
CMD ["--help"]
