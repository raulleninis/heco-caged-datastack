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

chown -R caged:caged /app

exec gosu caged "$@"
