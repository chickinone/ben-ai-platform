FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install "fastapi>=0.115" "uvicorn>=0.32" && useradd --uid 10001 mock
COPY app.py .
USER mock
EXPOSE 8080
HEALTHCHECK --interval=3s --timeout=2s --retries=20 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=1)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
