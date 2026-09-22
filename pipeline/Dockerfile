FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY flows/ /app/flows/

RUN useradd -m -u 1000 caged && chown -R caged:caged /app
USER caged

CMD ["python", "flows/ingest_caged.py"]
