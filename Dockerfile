# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo \
    HOST=0.0.0.0 \
    PORT=8090 \
    PAINEL_DADOS=/app/dados \
    PAINEL_INTERVALO_MINUTOS=20

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 painel \
    && useradd --uid 10001 --gid painel --create-home --shell /usr/sbin/nologin painel

WORKDIR /app

COPY . /app

RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/dados \
    && chown -R painel:painel /app

VOLUME ["/app/dados"]

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=8s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/status', timeout=5)" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["--tv", "--host", "0.0.0.0", "--porta", "8090"]
