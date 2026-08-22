#!/usr/bin/env bash
# Pre-flight: можно ли безопасно потерять это окружение?
#
# Проверяет всё, что должно пережить смерть песочницы. Одна команда вместо
# чек-листа из docs/DISASTER_RECOVERY.md.
#
#   ./scripts/recovery_check.sh
#
# Exit 0 = всё сохранено, окружение можно терять без потерь.
# Exit 1 = есть проблемы (перечислены все, не только первая).

set -uo pipefail   # без -e: собираем ВСЕ проблемы за один прогон
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

fails=0
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; fails=$((fails+1)); }

echo "Pre-flight восстановления окружения (что переживёт смерть песочницы)"

# 1. Рабочее дерево чисто — иначе незапушенное пропадёт.
if [[ -z "$(git status --porcelain)" ]]; then
  ok "рабочее дерево чисто (всё закоммичено)"
else
  bad "есть незакоммиченные изменения → ./scripts/save.sh \"описание\""
  git status --short | sed 's/^/        /'
fi

# 2. Хранилище секретов создано И закоммичено.
if [[ -f secrets/vault.enc ]]; then
  if git ls-files --error-unmatch secrets/vault.enc >/dev/null 2>&1; then
    ok "secrets/vault.enc есть и в git (секреты восстановятся)"
  else
    bad "secrets/vault.enc НЕ закоммичен → git add secrets/vault.enc && git commit"
  fi
else
  bad "secrets/vault.enc отсутствует — секреты (GITHUB_TOKEN и др.) НЕ восстановятся."
  echo "        → одноразово: export VAULT_PASSPHRASE='...' && ./scripts/vault.sh init && ./scripts/vault.sh edit"
  echo "          затем: git add secrets/vault.enc && ./scripts/save.sh \"chore(secrets): vault создан\""
fi

# 3. Шифрованный бэкап данных актуален.
if [[ -f secrets/data-backup.tar.gz.enc ]]; then
  if [[ -f data/ledger.json && data/ledger.json -nt secrets/data-backup.tar.gz.enc ]]; then
    bad "data/ledger.json новее бэкапа → ./scripts/backup.sh save"
  else
    ok "бэкап данных актуален (secrets/data-backup.tar.gz.enc)"
  fi
else
  bad "бэкапа данных нет → ./scripts/backup.sh save"
fi

# 4. Регрессионные тесты проходят.
if python3 tests/test_tools.py >/tmp/_rc_tests.log 2>&1; then
  ok "$(grep -oE 'Ran [0-9]+ tests' /tmp/_rc_tests.log) — OK"
else
  bad "тесты падают"
  tail -15 /tmp/_rc_tests.log | sed 's/^/        /'
fi
rm -f /tmp/_rc_tests.log

# 5. Открытых секретов в истории коммитов нет.
hist=$(git log --all -G'ghp_[A-Za-z0-9]{20,}' --oneline 2>/dev/null || true)
if [[ -n "$hist" ]]; then
  bad "в истории коммитов найден ghp_-токен — отозвать и перевыпустить:"
  echo "$hist" | sed 's/^/        /'
else
  ok "открытых секретов в истории коммитов нет"
fi

echo
if [[ $fails -eq 0 ]]; then
  echo "✓ Окружение можно терять без потерь: всё восстановится через"
  echo "  git clone && VAULT_PASSPHRASE=... && ./scripts/backup.sh restore && ./scripts/bootstrap.sh"
else
  echo "✗ Найдено проблем: $fails. Исправь и запусти заново."
fi
exit $((fails > 0))
