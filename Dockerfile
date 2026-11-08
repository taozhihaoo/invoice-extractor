# Pinned dependency set is verified on Python 3.13 (see CI matrix).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

LABEL org.opencontainers.image.title="AI Document Processor" \
      org.opencontainers.image.description="PDF ingestion, LLM structured invoice extraction, deterministic validation and CSV/JSON export" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY pyproject.toml README.md ./

# Non-root runtime user; data lives in a volume mounted at /app/data.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data /app/output \
    && chown -R appuser:appuser /app

USER appuser

ENV DATABASE_PATH=/app/data/processor.db \
    UPLOAD_DIR=/app/data/uploads \
    EXPORT_DIR=/app/output

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["python", "-m", "src.main", "--serve", "--host", "0.0.0.0", "--port", "8000"]
