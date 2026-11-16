#!/bin/sh
# Prepara o volume de dados e executa o painel com um usuário sem privilégios.
set -eu

DADOS="${PAINEL_DADOS:-/app/dados}"
USUARIO="${PAINEL_USUARIO:-painel}"

mkdir -p "$DADOS"

# Volumes nomeados e bind mounts podem chegar como root; ajusta o dono apenas
# quando necessário, para o processo conseguir gravar banco, cache e logo.
if [ "$(id -u)" = "0" ]; then
  if [ "$(stat -c '%u' "$DADOS")" != "10001" ]; then
    chown -R 10001:10001 "$DADOS"
  fi
  exec gosu "$USUARIO" python /app/servidor.py "$@"
fi

exec python /app/servidor.py "$@"
