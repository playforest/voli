# syntax=docker/dockerfile:1.7
#
# Voli HTTP server image.
#
# Builds the slim runtime image used for `voli serve` deploys (Claude.ai +
# ChatGPT Custom GPTs). Single-stage on python:3.13-slim; installs Poetry,
# resolves dependencies via the lockfile, and switches to a non-root user
# before running the server.
#
# Build:
#   docker build -t voli-server .
#
# Run (local dev, no auth):
#   docker run --rm -it -p 8080:8080 voli-server \
#     voli serve --no-auth --server-url http://localhost:8080
#
# Run (production, auth on, secrets via env file):
#   docker run --rm -it -p 8080:8080 --env-file .env.deploy \
#     -v voli-data:/var/voli voli-server

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.5 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    VOLI_CACHE_PATH=/var/voli/cache.sqlite \
    VOLI_TRACE_DIR=/var/voli/traces

# System packages: curl for the Poetry installer, build-essential for any
# wheel-less native deps (httpx and friends ship wheels for slim, so this
# is mostly defensive). Both are removed before the final layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && apt-get purge -y --auto-remove curl build-essential \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Copy project metadata first so dependency resolution caches across edits
# to source code. README.md is referenced from pyproject.toml; including it
# here keeps Poetry from complaining during the build.
COPY pyproject.toml poetry.lock README.md ./

# Source code. .dockerignore strips everything that isn't shipped (tests,
# notebooks, examples, site builds, .git, etc.).
COPY src/ ./src/

# Install runtime dependencies + the mcp extra (which transitively pulls
# starlette and uvicorn for `voli serve`). --no-root then -e . in two
# steps avoids re-resolving when the source-only layers above change.
RUN poetry install --only main -E mcp --no-root \
    && pip install --no-deps -e .

# Non-root user owning the on-disk cache + trace directory. Containers
# orchestrators often mount /var/voli as a volume for persistence; this
# user UID (10001) needs to own that volume.
RUN useradd -r -u 10001 -m voli \
    && mkdir -p /var/voli/traces \
    && chown -R voli:voli /var/voli /app

USER voli
EXPOSE 8080

# Liveness check used by docker, compose, k8s, etc. Curl isn't installed
# in the slim image; using urllib avoids adding it back.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz', timeout=2).status == 200 else 1)" \
    || exit 1

# Entrypoint = the binary; CMD = its default args. Override either with
# `docker run voli-server <args>` to swap CMD, or `--entrypoint` to bypass.
ENTRYPOINT ["voli", "serve"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
