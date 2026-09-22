# Pinada por tag + digest (capturado em 22/09/2026 via
# `docker inspect --format='{{index .RepoDigests 0}}' python:3.11.10-slim-bookworm`).
# Reprodutibilidade máxima: mesmo se a tag for republicada, este build usa
# sempre os mesmos bytes.
FROM python:3.11.10-slim-bookworm@sha256:840e180ebcc6e5c8efab209c43f5e40fd2af98cb49db5c7103c90539c56bb30e

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY flows/ /app/flows/
COPY prefect.yaml /app/prefect.yaml
COPY start.sh /app/start.sh
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /app/start.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd -m -u 1000 caged

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["/app/start.sh"]
