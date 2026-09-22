#!/bin/bash
set -e

echo "Aguardando Prefect Server..."
until curl -sf "${PREFECT_API_URL}/health" > /dev/null 2>&1; do
    sleep 2
done

echo "Criando work pool 'default' (se ainda não existir)..."
prefect work-pool create default --type process 2>/dev/null || echo "Work pool 'default' já existe."

echo "Aplicando deployments de prefect.yaml..."
prefect deploy --all

echo "Iniciando worker..."
exec prefect worker start --pool default
