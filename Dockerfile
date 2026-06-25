# OrionBelt Ontology Builder — container image
#
# Build:  docker build -t ralforion/orionbelt-ontology-builder .
# Run:    docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder
# Open:   http://localhost:8501

FROM python:3.12-slim

# Streamlit / runtime defaults
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install dependencies first so they stay cached across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Install the application as a package (pulls in bundled samples/lib/assets).
COPY . .
RUN pip install --no-deps .

# Run as a non-root user.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else 1)"

ENTRYPOINT ["streamlit", "run", "app.py"]
