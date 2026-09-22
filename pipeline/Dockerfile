FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flows/ /app/flows/
COPY prefect.yaml /app/prefect.yaml
COPY start.sh /app/start.sh
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /app/start.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd -m -u 1000 caged

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["/app/start.sh"]
