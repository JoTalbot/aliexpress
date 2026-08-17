#!/usr/bin/env bash
# Хранилище секретов проекта. AES-256-CBC + PBKDF2, OpenSSL.
#
# ПРИНЦИП: в репозиторий попадает ТОЛЬКО зашифрованный файл.
# Мастер-пароль живёт в голове/менеджере паролей владельца и НИКОГДА не коммитится.
#
#   ./scripts/vault.sh init         — создать хранилище из шаблона
#   ./scripts/vault.sh edit         — расшифровать, открыть в $EDITOR, зашифровать обратно
#   ./scripts/vault.sh show         — вывести содержимое в stdout
#   ./scripts/vault.sh export       — вывести как `export KEY=value` для eval
#   ./scripts/vault.sh encrypt FILE — зашифровать произвольный файл в хранилище
#
# Пароль берётся из $VAULT_PASSPHRASE, иначе спрашивается интерактивно.
#
# Использование в новом окружении:
#   export VAULT_PASSPHRASE='...'
#   eval "$(./scripts/vault.sh export)"

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT="$ROOT/secrets/vault.enc"
TEMPLATE="$ROOT/secrets/vault.template.env"
CIPHER=(-aes-256-cbc -pbkdf2 -iter 240000 -salt)

pass_args() {
  if [[ -n "${VAULT_PASSPHRASE:-}" ]]; then
    printf '%s' "-pass"; printf '\0'; printf '%s' "env:VAULT_PASSPHRASE"
  else
    printf '%s' "-pass"; printf '\0'; printf '%s' "stdin"
  fi
}

_enc() { # stdin -> vault
  if [[ -n "${VAULT_PASSPHRASE:-}" ]]; then
    openssl enc "${CIPHER[@]}" -pass env:VAULT_PASSPHRASE -out "$VAULT"
  else
    openssl enc "${CIPHER[@]}" -out "$VAULT"
  fi
}

_dec() { # vault -> stdout
  [[ -f "$VAULT" ]] || { echo "Хранилище не найдено: $VAULT (запусти: vault.sh init)" >&2; exit 1; }
  if [[ -n "${VAULT_PASSPHRASE:-}" ]]; then
    openssl enc -d "${CIPHER[@]}" -pass env:VAULT_PASSPHRASE -in "$VAULT"
  else
    openssl enc -d "${CIPHER[@]}" -in "$VAULT"
  fi
}

cmd="${1:-help}"
case "$cmd" in
  init)
    if [[ -f "$VAULT" ]]; then echo "Хранилище уже существует. Используй edit." >&2; exit 1; fi
    _enc < "$TEMPLATE"
    echo "Создано: secrets/vault.enc"
    echo "ВАЖНО: запомни пароль. Без него данные не восстановить."
    ;;
  show)   _dec ;;
  export) _dec | grep -Ev '^\s*(#|$)' | sed 's/^/export /' ;;
  edit)
    tmp="$(mktemp)"; chmod 600 "$tmp"
    trap 'shred -u "$tmp" 2>/dev/null || rm -f "$tmp"' EXIT
    if [[ -f "$VAULT" ]]; then _dec > "$tmp"; else cp "$TEMPLATE" "$tmp"; fi
    "${EDITOR:-vi}" "$tmp"
    _enc < "$tmp"
    echo "Хранилище обновлено."
    ;;
  encrypt)
    src="${2:?укажи файл}"; _enc < "$src"; echo "Зашифровано в $VAULT"
    ;;
  *)
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    ;;
esac
