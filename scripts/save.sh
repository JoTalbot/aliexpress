#!/usr/bin/env bash
# Быстрое сохранение работы: коммит + push одной командой.
# Защита от потери окружения — использовать часто.
#
#   ./scripts/save.sh "research(dispute): добавил статистику исходов"
#   ./scripts/save.sh                      # автосообщение (WIP)

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AGENT_ID="${AGENT_ID:-unknown-agent-$(date +%Y%m%d-%H%M)}"
MSG="${1:-chore: WIP автосохранение $(date -u +%Y-%m-%dT%H:%MZ)}"

if git diff --quiet && git diff --cached --quiet && [[ -z "$(git status --porcelain)" ]]; then
  echo "Нечего сохранять — рабочее дерево чисто."
  exit 0
fi

git add -A
git commit -q -m "$MSG

Agent: $AGENT_ID"

git pull --rebase --quiet origin main || { echo "Конфликт при rebase — разреши вручную."; exit 1; }
git push --quiet origin main
echo "✓ Сохранено и запушено: $MSG"
git log --oneline -1

# T-064: ledger.json менялся после последнего шифрованного бэкапа? Напомнить.
LEDGER="data/ledger.json"; BACKUP="secrets/data-backup.tar.gz.enc"
if [[ -f "$LEDGER" ]]; then
  if [[ ! -f "$BACKUP" || "$LEDGER" -nt "$BACKUP" ]]; then
    echo "⚠ data/ledger.json новее бэкапа (save.sh его НЕ покрывает — он в .gitignore)."
    echo "  Сохрани данные: ./scripts/backup.sh save"
  fi
fi
