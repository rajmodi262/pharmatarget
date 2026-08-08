# Single container: FastAPI serves the API and the dashboard from one origin.
# One deploy, one URL, no CORS. Simpler to demo than a two-service split, and
# nothing here needs a separate frontend host.
#
# Data strategy: the deploy bundle (data/deploy/) is COPIED into the image at
# build time.  It is 36 MB of zstd-compressed parquet covering the top 50,000
# prescribers by opportunity plus every aggregate table -- small enough for a
# free-tier image layer and identical to the full dataset for all demo routes.
# PHARMATARGET_DATA_DIR tells the API where to find it.
#
# Frontend strategy: web/dist/ is pre-built on the host (tsc + vite, ~1.6 s)
# and COPY-d directly.  No Node stage in the image keeps the final layer count
# low and avoids pulling the Node toolchain into a Python runtime image.

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY config/ ./config/
COPY src/ ./src/
COPY api/ ./api/

# Pre-built React dashboard (built on the host with portable Node).
COPY web/dist/ ./web/dist/

# Slimmed deploy bundle: top 50k prescribers + all aggregates, 36 MB.
# The env var tells api/db.py which directory to open; it logs the choice
# at startup so a misconfigured path fails loudly rather than silently.
COPY data/deploy/ ./data/deploy/
ENV PHARMATARGET_DATA_DIR=/app/data/deploy

# Also copy the manifest so /api/summary and /api/meta return full-universe KPIs.
# (It is already inside data/deploy/ after make_deploy_bundle, but the config
#  module resolves it relative to ROOT which is /app, not the data dir.)
COPY data/manifest.json ./data/manifest.json

EXPOSE 8000
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

# Bind to 0.0.0.0 and honour $PORT so Render can inject its chosen port.
CMD python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
