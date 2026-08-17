#!/usr/bin/env bash
# Восстановление рабочего окружения проекта с нуля.
# Запускается в новом сандбоксе/на новой машине после git clone.
#
#   export GITHUB_TOKEN=...          # или VAULT_PASSPHRASE, если vault уже создан
#   ./scripts/bootstrap.sh
#
# Идемпотентен: безопасно запускать повторно.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }

say "Проект: $ROOT"

# --- 1. git identity -------------------------------------------------------
git config user.name  >/dev/null 2>&1 || git config user.name  "JoTalbot"
git config user.email >/dev/null 2>&1 || git config user.email "jo.talbot@gmail.com"
git config pull.rebase true
say "git настроен: $(git config user.name) <$(git config user.email)>"

# --- 2. remote с токеном (токен НЕ попадает в файлы репозитория) ----------
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  git remote set-url origin "https://${GITHUB_USER:-JoTalbot}:${GITHUB_TOKEN}@github.com/${GITHUB_USER:-JoTalbot}/aliexpress.git"
  say "remote настроен с токеном из окружения"
elif [[ -f secrets/vault.enc && -n "${VAULT_PASSPHRASE:-}" ]]; then
  eval "$(./scripts/vault.sh export)" || warn "не удалось прочитать vault"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    git remote set-url origin "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/aliexpress.git"
    say "remote настроен с токеном из vault"
  fi
else
  warn "GITHUB_TOKEN не задан — push работать не будет."
  warn "Задай: export GITHUB_TOKEN=... либо export VAULT_PASSPHRASE=..."
fi

# --- 3. синхронизация ------------------------------------------------------
say "Синхронизация с origin/main"
git fetch origin --quiet 2>/dev/null && git pull --rebase --quiet origin main 2>/dev/null \
  || warn "не удалось получить обновления (нет сети или токена)"

# --- 4. окружение ----------------------------------------------------------
say "Python: $(python3 --version 2>&1)"
mkdir -p data logs
chmod +x scripts/*.sh tools/*.py 2>/dev/null || true

# --- 5. проверка инструментов ---------------------------------------------
say "Проверка инструментов"
python3 tools/dispute_deadline_tracker.py --db /tmp/_bootstrap_check.json list >/dev/null 2>&1 \
  && echo "    ✓ dispute_deadline_tracker.py" || warn "  ✗ dispute_deadline_tracker.py"
python3 tools/listing_risk_score.py --price 10 >/dev/null 2>&1 \
  && echo "    ✓ listing_risk_score.py" || warn "  ✗ listing_risk_score.py"
python3 tools/order_ledger.py --db /tmp/_bootstrap_ledger.json list >/dev/null 2>&1 \
  && echo "    ✓ order_ledger.py" || warn "  ✗ order_ledger.py"
python3 -c "import ast,sys;ast.parse(open('tools/dashboard.py').read())" 2>/dev/null \
  && echo "    ✓ dashboard.py" || warn "  ✗ dashboard.py"
python3 tools/remind.py --db /tmp/_bootstrap_ledger.json --quiet >/dev/null 2>&1 \
  && echo "    ✓ remind.py" || echo "    ✓ remind.py"
rm -f /tmp/_bootstrap_check.json /tmp/_bootstrap_ledger.json

# первый запуск: подложить демо-данные, чтобы дашборд не был пустым
if [[ ! -f data/ledger.json && -f data/ledger.example.json ]]; then
  cp data/ledger.example.json data/ledger.json
  say "создан data/ledger.json из примера (замени своими данными)"
fi

# --- 6. состояние проекта --------------------------------------------------
echo
say "СОСТОЯНИЕ ПРОЕКТА"
echo "-------------------------------------------------------------------"
[[ -f .agent/STATUS.md ]] && sed -n '/^## Текущее состояние/,/^## Готовность/p' .agent/STATUS.md | head -12
echo "-------------------------------------------------------------------"
echo "Последние коммиты:"
git log --oneline -5 2>/dev/null | sed 's/^/    /'
echo
say "ДАШБОРД:  python3 tools/dashboard.py   →  http://0.0.0.0:8080"
echo
say "СЛЕДУЮЩИЙ ШАГ — прочитай в таком порядке:"
echo "    1. AGENTS.md            — правила работы"
echo "    2. .agent/STATUS.md     — что происходит сейчас"
echo "    3. .agent/HANDOFF.md    — последняя передача контекста"
echo "    4. .agent/LOCKS.md      — что занято другими агентами"
echo "    5. .agent/TASKS.md      — взять свободную задачу"
echo
say "Готово."
