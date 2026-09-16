# Build context: thư mục gốc repo. Tuần 2: chỉ chạy migration.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY services/control-plane /app
RUN pip install /app && useradd --create-home --uid 10001 ben

USER ben
CMD ["alembic", "upgrade", "head"]
