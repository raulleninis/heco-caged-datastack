#!/bin/bash
set -e

# Alinha o UID/GID do usuário 'caged' com o dono real dos bind mounts.
# Sem isso, se o host não usa UID 1000, baixar_arquivo() e dbt run falham
# com PermissionError ao escrever em /data e /dbt.
for mount in /data /dbt; do
    [ -d "$mount" ] || continue

    OWNER_UID=$(stat -c '%u' "$mount")

    if [ "$OWNER_UID" = "0" ]; then
        # Bind mount recém-criado pelo Docker (ainda dono de root) — não há
        # UID real do host pra copiar. Toma posse como 'caged' (UID 1000) e
        # segue; da próxima vez já vai ser o dono real.
        chown -R caged:caged "$mount"
        continue
    fi

    CURRENT_UID=$(id -u caged)
    if [ "$OWNER_UID" != "$CURRENT_UID" ]; then
        OWNER_GID=$(stat -c '%g' "$mount")
        usermod -u "$OWNER_UID" caged
        groupmod -g "$OWNER_GID" caged
    fi
done

# Garante a estrutura de diretórios que o pipeline espera. DuckDB não cria
# diretórios pais ao conectar — profiles.yml aponta pra
# /data/warehouse/caged.duckdb, e sem essa pasta existir de antemão, dbt run
# falha com "IO Error: ... No such file or directory" (visto em validação
# real: backfill baixa tudo certo, mas dbt run quebra num clone limpo onde
# ninguém criou /data/warehouse manualmente).
#
# Roda DEPOIS do bloco de UID/GID acima, e sempre faz chown explícito —
# mkdir como root cria subdiretório novo dono de root mesmo quando o mount
# point /data já é caged:caged de uma execução anterior (o bloco acima só
# corrige o dono do mount point em si, não recria subdiretórios).
mkdir -p /data/warehouse /data/raw
chown -R caged:caged /data/warehouse /data/raw

chown -R caged:caged /app

exec gosu caged "$@"
