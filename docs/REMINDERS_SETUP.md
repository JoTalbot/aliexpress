# Напоминания в Telegram — настройка под ключ (T-058)

> Актуально на: 2026-08-17 · Инструмент: `tools/remind.py`
>
> Результат: каждый день в 10:00 в ваш Telegram приходит сводка — горящие дедлайны
> споров, зависшие возвраты (>28 дн. без зачисления → ARN), разрывы оборотки.
> Если всё спокойно — бот молчит (`--quiet`).

## Шаг 1. Создать бота (1 минута)

1. В Telegram открыть **@BotFather** → команда `/newbot`.
2. Имя: любое (например `AliLedger Reminder`); username: любой свободный, оканчивается на `bot`.
3. BotFather выдаст **токен** вида `1234567890:AA...`. Никому не показывать.

## Шаг 2. Узнать свой chat_id (30 секунд)

1. Написать своему новому боту любое сообщение (например `старт`) — без этого бот
   не может писать вам первым.
2. Открыть в браузере (подставив токен):
   `https://api.telegram.org/bot<ТОКЕН>/getUpdates`
3. В ответе найти `"chat":{"id":123456789,...}` — это ваш **chat_id**.

## Шаг 3. Положить секреты в vault (не в файлы!)

```bash
export VAULT_PASSPHRASE='ваш-пароль-vault'
./scripts/vault.sh edit          # откроется расшифрованный список KEY=value
```

Добавить две строки:

```
TG_TOKEN=1234567890:AA...
TG_CHAT=123456789
```

Сохранить — vault.sh сам зашифрует и предложит закоммитить шифртекст.

## Шаг 4. Проверить руками

```bash
eval "$(./scripts/vault.sh export)"     # подтянуть TG_TOKEN/TG_CHAT в окружение
python3 tools/remind.py --days 5        # remind сам возьмёт их из env
```

В Telegram должна прийти сводка. Если нет:
- бот создан, но вы ему **не написали первым** (шаг 2.1) — самая частая причина;
- проверить токен/chat_id: `curl -s https://api.telegram.org/bot$TG_TOKEN/getMe`.

## Шаг 5. Поставить на расписание

### cron (Linux/macOS)

```bash
crontab -e
```

```cron
0 10 * * * cd /путь/к/aliexpress && eval "$(VAULT_PASSPHRASE=пароль ./scripts/vault.sh export)" && /usr/bin/python3 tools/remind.py --days 5 --quiet --plain >> logs/remind.log 2>&1
```

⚠ Пароль vault в crontab — компромисс. Безопаснее: файл `~/.vault_pass` c правами `600`
и `VAULT_PASSPHRASE=$(cat ~/.vault_pass)`.

### systemd timer (альтернатива)

`~/.config/systemd/user/ali-remind.service`:

```ini
[Unit]
Description=AliExpress deadline reminders

[Service]
Type=oneshot
WorkingDirectory=/путь/к/aliexpress
ExecStart=/bin/bash -c 'eval "$(./scripts/vault.sh export)" && python3 tools/remind.py --days 5 --quiet --plain'
Environment=VAULT_PASSPHRASE=пароль
```

`~/.config/systemd/user/ali-remind.timer`:

```ini
[Unit]
Description=Daily AliExpress reminders

[Timer]
OnCalendar=*-*-* 10:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now ali-remind.timer
systemctl --user list-timers | grep ali    # проверить
```

## Что приходит и когда

| Ситуация | Сообщение |
|---|---|
| Дедлайн спора ≤ 3 дн. | 🔴 КРИТИЧНО — открывай спор сегодня |
| Дедлайн ≤ 5 дн. (`--days`) | 🟡 СРОЧНО |
| Спор висит > 30 дн. | 🟡 пора эскалировать |
| Возврат одобрен > 28 дн., зачисления нет | 🟡 проверь выписку → запроси ARN (research/17 §2) |
| Всё спокойно | ничего (`--quiet`) |

Коды возврата (`echo $?`): 0 — тихо · 1 — есть срочное · 2 — есть просроченное.
Удобно для связок: `remind.py --quiet || notify-send "AliExpress!"`.
