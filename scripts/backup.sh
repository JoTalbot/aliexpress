#!/usr/bin/env bash
# Зашифрованный бэкап рабочих данных в git.
#
# Проблема, которую решает: data/ledger.json в .gitignore (там личные заказы),
# поэтому при потере окружения он исчезает вместе с песочницей.
# Решение: шифруем его тем же паролем, что и vault, и коммитим шифртекст.
#
#   ./scripts/backup.sh save      — зашифровать data/ + запушить
#   ./scripts/backup.sh restore   — расшифровать обратно в data/
#   ./scripts/backup.sh diff      — что изменилось с последнего бэкапа
#
# Пароль: $VAULT_PASSPHRASE или интерактивно.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

ARCHIVE="secrets/data-backup.tar.gz.enc"
CIPHER=(-aes-256-cbc -pbkdf2 -iter 240000 -salt)
SOURCES=(data/ledger.json)
# data/evidence: чек-листы, фото, скриншоты — тоже теряются с песочницей.
# Видео исключаем: слишком большие для git (для них — облако/локальный диск).
EVIDENCE_DIR="data/evidence"
EVIDENCE_EXCLUDE=(--exclude='*.mp4' --exclude='*.mov' --exclude='*.avi' --exclude='*.mkv' --exclude='*.webm')

_pass() { [[ -n "${VAULT_PASSPHRASE:-}" ]] && echo "-pass env:VAULT_PASSPHRASE" || echo "-pass stdin"; }

case "${1:-help}" in
  save)
    found=()
    for f in "${SOURCES[@]}"; do [[ -f "$f" ]] && found+=("$f"); done
    [[ -d "$EVIDENCE_DIR" ]] && found+=("$EVIDENCE_DIR")
    if [[ ${#found[@]} -eq 0 ]]; then echo "Нечего сохранять — нет data/ledger.json и data/evidence/"; exit 0; fi
    tar czf - "${EVIDENCE_EXCLUDE[@]}" "${found[@]}" | openssl enc "${CIPHER[@]}" $(_pass) -out "$ARCHIVE"
    echo "✓ Зашифровано: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
    echo "  Файлы: ${found[*]}"
    git add -f "$ARCHIVE"
    if git diff --cached --quiet; then echo "  Изменений нет."; exit 0; fi
    git commit -q -m "chore(backup): encrypted data snapshot $(date -u +%Y-%m-%dT%H:%MZ)

Agent: ${AGENT_ID:-unknown}"
    git pull -q --rebase origin main && git push -q origin main
    echo "✓ Запушено в GitHub."
    ;;
  restore)
    [[ -f "$ARCHIVE" ]] || { echo "Бэкап не найден: $ARCHIVE" >&2; exit 1; }
    if [[ -f data/ledger.json ]]; then
      cp data/ledger.json "data/ledger.json.before-restore-$(date +%s)"
      echo "  Текущий файл сохранён как data/ledger.json.before-restore-*"
    fi
    mkdir -p data
    openssl enc -d "${CIPHER[@]}" $(_pass) -in "$ARCHIVE" | tar xzf - -C .
    echo "✓ Восстановлено:"
    python3 tools/order_ledger.py list 2>/dev/null | head -5 || true
    ;;
  diff)
    [[ -f "$ARCHIVE" ]] || { echo "Бэкапа ещё нет."; exit 0; }
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    openssl enc -d "${CIPHER[@]}" $(_pass) -in "$ARCHIVE" | tar xzf - -C "$tmp"
    if diff -q "$tmp/data/ledger.json" data/ledger.json >/dev/null 2>&1; then
      echo "✓ Бэкап актуален."
    else
      echo "⚠ Есть незабэкапленные изменения. Запусти: ./scripts/backup.sh save"
      diff <(python3 -c "import json,sys;[print(o['order_id']) for o in json.load(open('$tmp/data/ledger.json'))]" 2>/dev/null) \
           <(python3 -c "import json,sys;[print(o['order_id']) for o in json.load(open('data/ledger.json'))]" 2>/dev/null) || true
    fi
    ;;
  *)
    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
esac
