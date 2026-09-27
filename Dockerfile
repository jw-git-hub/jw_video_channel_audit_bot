# Образ аудита видеоканала (ТЗ, раздел 10, 14.3): Python 3.12, не root, внутри только код бота с полосами
# и зависимости. Версия закреплена точно: образ пересобирается одинаково. Слим-образ ставит ca-certificates
# сам — ими пользуются HTTPS-запросы к Google и Telegram; alpine или apt-get remove/purge убрали бы их.
FROM python:3.12.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot/ bot/

RUN groupadd --gid 10001 bot \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin bot \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data

USER 10001:10001
CMD ["python", "-m", "bot"]
