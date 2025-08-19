FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# Для применения SQL-миграций из контейнера API
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Сначала зависимости (кэш слоёв).
# ВАЖНО: requirements.txt лежит в api/, а build-контекст — КОРЕНЬ
COPY api/requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt

# Копируем ВЕСЬ репозиторий (и api/, и migration/)
COPY . /app

# Стартовый скрипт
RUN chmod +x /app/api/start.sh

EXPOSE 8000

# Healthcheck (одной строкой)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request, sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else sys.exit(1)"

ENTRYPOINT ["/app/api/start.sh"]
