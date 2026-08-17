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

## `dashboard.py`

Веб-интерфейс над `order_ledger.py`. Те же данные (`data/ledger.json`),
CLI и дашборд взаимозаменяемы.

```bash
python3 tools/dashboard.py                      # http://0.0.0.0:8080
python3 tools/dashboard.py --port 9000 --db data/ledger.json
```

Что показывает:
- **KPI-плитки:** итог, вложено, выручка, возвращено, ожидается, разрыв оборотки, доля споров;
- **Алерты:** горящие дедлайны, споры старше 30 дней, превышение доли споров, разрыв оборотки;
- **Таблица заказов** с сортировкой по срочности; клик по строке — детали, заметки и действия
  (доставлен / подтвердить / открыть спор / возврат получен / вернул клиенту / заметка / закрыть);
- **Разбивка по маршрутам** — какой канал доставки прибыльный, а какой генерирует споры.

Только стандартная библиотека, стили и скрипты инлайн — работает офлайн, без CDN.
Экспорт CSV: `GET /api/export`.

Данные пишутся сразу в `data/ledger.json`, автообновление раз в 30 секунд.

## `remind.py`

Напоминания о горящих дедлайнах — для запуска по расписанию.
Главный автоматизируемый риск: пропущенное окно спора закрывает возврат навсегда.

```bash
python3 tools/remind.py                 # отчёт в терминал
python3 tools/remind.py --days 5        # порог срочности
python3 tools/remind.py --quiet         # молчит, если всё спокойно (для cron)
python3 tools/remind.py --format json   # для интеграций
python3 tools/remind.py --install-cron  # готовая строка для crontab
```

Что отслеживает:
- 🔴 просроченные окна и критичные (≤3 дней);
- 🟡 приближающиеся дедлайны;
- 🟡 споры, висящие дольше 30 дней — пора эскалировать к платформе;
- ℹ доставленные, но не подтверждённые заказы (это правильное состояние — напоминание проверить товар);
- суммы: ожидается от поставщиков, разрыв оборотки.

**Коды возврата** для мониторинга: `0` — чисто, `1` — есть срочное, `2` — есть просроченное.

```bash
# уведомление в systemd/desktop
python3 tools/remind.py --quiet || notify-send "AliExpress: горит дедлайн"

# в Telegram
python3 tools/remind.py --quiet --telegram-token "$TG_TOKEN" --telegram-chat "$TG_CHAT"

# в Slack/Discord/свой сервис
python3 tools/remind.py --quiet --webhook https://hooks.example.com/...
```

Ежедневный запуск (crontab -e):
```
0 10 * * * cd /path/to/aliexpress && /usr/bin/python3 tools/remind.py --days 5 --plain --quiet >> logs/remind.log 2>&1
```

## `route_calc.py`

Калькулятор landed cost по четырём маршрутам доставки с учётом пошлин, НДС и пересылки.
Сопоставляет итоговую стоимость с качеством защиты возврата.

```bash
python3 tools/route_calc.py --price 40 --weight 0.6 --items 3
python3 tools/route_calc.py --price 200 --weight 2.5 --currency USD
python3 tools/route_calc.py --price 60 --items 2 --format json
```

⚠️ **`--items` — это число РАЗНЫХ товарных подпозиций, а не штук.**
Пять одинаковых футболок = 1 подпозиция = €3. Футболка + кабель = 2 подпозиции = €6.
После Регламента ЕС 2026/382 это главный драйвер стоимости на маршруте EU-forward.

Учитывает: украинский лимит €150 (10% пошлина + 20% НДС на превышение),
сбор ЕС €3/подпозиция, НДС Польши 23%, тарифы форвардеров PL→UA, двойную таможню.

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
