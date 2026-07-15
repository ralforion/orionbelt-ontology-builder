# OrionBelt Ontology Builder — container image
#
# Build:  docker build -t ralforion/orionbelt-ontology-builder .
# Run:    docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder
# Open:   http://localhost:8501

# uv provides the resolver; a pinned stage keeps the version reproducible and
# lets Dependabot bump it like any other base image.
FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.14-slim

COPY --from=uv /uv /uvx /bin/

# Streamlit / runtime defaults
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install dependencies first so they stay cached across code changes. --frozen
# installs exactly what uv.lock pins and fails if it has drifted from
# pyproject.toml, so the image matches the deployed app.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

# Install the application as a package (pulls in bundled samples/lib/assets).
COPY . .
RUN uv sync --frozen --no-editable

# uv installs into a project venv; put it first on PATH so `streamlit` resolves.
ENV PATH="/app/.venv/bin:$PATH"

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else 1)"

ENTRYPOINT ["streamlit", "run", "app.py"]
