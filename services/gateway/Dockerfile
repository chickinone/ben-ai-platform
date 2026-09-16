# Build context: thư mục gốc repo (cần libs/)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY libs/ben_common libs/ben_common
COPY libs/ben_telemetry libs/ben_telemetry
COPY services/gateway services/gateway
RUN pip install ./libs/ben_common ./libs/ben_telemetry ./services/gateway \
    && useradd --create-home --uid 10001 ben

USER ben
WORKDIR /home/ben
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "ben_gateway.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
