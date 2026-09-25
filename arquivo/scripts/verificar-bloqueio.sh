#!/usr/bin/env bash
# Teste de aceite do bloqueio (F15, itens 1, 6 e 7). Roda de FORA, sem cookie.
#
# Uso: scripts/verificar-bloqueio.sh https://SEU-SITE.netlify.app [caminho-extra ...]
#
# Rode: antes de publicar qualquer arquivo real; depois de cada mudança na
# configuração; e também contra o endereço permanente de um deploy antigo
# (https://<id-do-deploy>--SEU-SITE.netlify.app) — deploys antigos continuam no ar.
# Caminhos extras (ex.: /2026-06/boletim-202606.pdf) entram na mesma checagem.
set -u

base="${1:?uso: $0 https://SEU-SITE.netlify.app [caminho-extra ...]}"
base="${base%/}"
shift
falhas=0

status() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$base$1"; }
destino() { curl -s -o /dev/null -w '%{redirect_url}' --max-time 20 "$base$1"; }

# Protegidos: nunca 200. Redirect só vale se for para o login.
for caminho in / /index.html /_teste/teste.pdf /_teste/teste.xlsx /sitemap.xml "$@"; do
  s=$(status "$caminho")
  if [ "$s" = 200 ] || [ -z "$s" ] || [ "$s" = 000 ]; then
    echo "FALHOU  $caminho -> $s (deveria ser bloqueado)"; falhas=$((falhas + 1))
  elif [ "$s" = 301 ] || [ "$s" = 302 ] || [ "$s" = 307 ] || [ "$s" = 308 ]; then
    d=$(destino "$caminho")
    case "$d" in
      */login.html) echo "ok      $caminho -> $s $d" ;;
      *) echo "FALHOU  $caminho -> $s $d (redirect para fora do login)"; falhas=$((falhas + 1)) ;;
    esac
  else
    echo "ok      $caminho -> $s"
  fi
done

# Públicos: só a allow-list, e tem de estar no ar (senão ninguém consegue entrar).
for caminho in /login.html /robots.txt; do
  s=$(status "$caminho")
  if [ "$s" = 200 ]; then echo "ok      $caminho -> 200 (público, esperado)"
  else echo "FALHOU  $caminho -> $s (deveria ser 200)"; falhas=$((falhas + 1)); fi
done

if curl -s --max-time 20 "$base/robots.txt" | grep -qi '^Disallow: */'; then
  echo "ok      robots.txt tem Disallow: /"
else
  echo "FALHOU  robots.txt sem Disallow: /"; falhas=$((falhas + 1))
fi

if curl -sI --max-time 20 "$base/login.html" | grep -qi '^x-robots-tag:.*noindex'; then
  echo "ok      X-Robots-Tag: noindex"
else
  echo "FALHOU  X-Robots-Tag: noindex ausente"; falhas=$((falhas + 1))
fi

echo
if [ "$falhas" -eq 0 ]; then echo "BLOQUEIO OK ($base)"; else echo "$falhas falha(s): NÃO publique nenhum arquivo real."; exit 1; fi
