FROM python:3.12-slim

WORKDIR /app

# Only the API needs third-party wheels; the worker + core are pure stdlib and
# import from the same image, so one dependency install covers both services.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY yoe/ ./yoe/

# Shared data dir for the sqlite time-series store (mounted as a volume in compose).
RUN mkdir -p /data
ENV DATABASE_URL=sqlite:////data/yoe.db
VOLUME ["/data"]

EXPOSE 8000

# Default command is the API; the worker service overrides it in compose with
# `python -m yoe.worker`.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["uvicorn", "yoe.api:app", "--host", "0.0.0.0", "--port", "8000"]
