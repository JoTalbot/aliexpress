# tools/ — утилиты проекта

Python 3.11+, только стандартная библиотека. Зависимости добавлять только через ADR.

## `dispute_deadline_tracker.py`

Учёт заказов и дедлайнов Buyer Protection. Решает главную проблему возвратов:
пропущенное окно спора закрывает вопрос навсегда.

```bash
# добавить заказ сразу после отправки
python3 dispute_deadline_tracker.py add --id 8012345678901234 \
    --title "Наушники TWS" --amount 24.90 --shipped 2026-08-01 --free-return

# отметить доставку (получение НЕ подтверждать до проверки!)
python3 dispute_deadline_tracker.py delivered --id 8012345678901234 --date 2026-08-15

# что горит в ближайшую неделю
python3 dispute_deadline_tracker.py check --days 7

python3 dispute_deadline_tracker.py list
python3 dispute_deadline_tracker.py note --id 8012345678901234 --text "видео распаковки снято"
python3 dispute_deadline_tracker.py dispute --id 8012345678901234   # спор открыт
python3 dispute_deadline_tracker.py close --id 8012345678901234     # претензий нет
```

Данные: `tools/orders.json` (в `.gitignore` — не коммитить свои заказы).
Окна настраиваются: `--bp-days`. **Обязывающая цифра — счётчик на странице заказа.**

Рекомендация: повесить `check --days 5` в cron/Task Scheduler на ежедневный запуск.

## `listing_risk_score.py`

Оценка листинга по возвратопригодности до покупки. Методика — `research/04`.

```bash
python3 listing_risk_score.py --interactive

python3 listing_risk_score.py --free-return --choice --store-age 30 \
    --rating 4.8 --sales 2400 --price 32 --photo-reviews --size-chart

python3 listing_risk_score.py --json listing.json
python3 listing_risk_score.py --interactive --dump > listing.json
```

Шкала: ≥50 низкий риск · 20–49 приемлемо · 0–19 повышенный · <0 высокий.
