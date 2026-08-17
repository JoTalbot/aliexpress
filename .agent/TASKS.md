# TASKS — бэклог и канбан

> Статусы: `TODO` · `IN-PROGRESS` · `REVIEW` · `DONE` · `BLOCKED` · `BLOCKED-SCOPE`
> Взял задачу → поставь `IN-PROGRESS` + свой AGENT_ID + лок. Закончил → `DONE` + коммит.

## Фаза 1 — каркас и базовое исследование

| ID | Задача | Статус | Агент |
|---|---|---|---|
| T-001 | README + AGENTS.md (протокол мультиагентной работы) | DONE | arena-agent-sandbox-20260817-1152 |
| T-002 | Система статуса/контекста `.agent/*` | DONE | arena-agent-sandbox-20260817-1152 |
| T-003 | Границы проекта `docs/SCOPE_AND_ETHICS.md` | DONE | arena-agent-sandbox-20260817-1152 |
| T-004 | Правила Buyer Protection, сроки, окна | DONE | arena-agent-sandbox-20260817-1152 |
| T-005 | Механика спора, доказательства, эскалация | DONE | arena-agent-sandbox-20260817-1152 |
| T-006 | Free Return / Choice / локальные возвраты | DONE | arena-agent-sandbox-20260817-1152 |
| T-007 | Методика отбора товаров с низким риском | DONE | arena-agent-sandbox-20260817-1152 |
| T-008 | Разбор hidden links и «скрытых товаров» | DONE | arena-agent-sandbox-20260817-1152 |
| T-009 | Threat intel по теневой рефанд-индустрии | DONE | arena-agent-sandbox-20260817-1152 |

## Фаза 2 — верификация и углубление

| ID | Задача | Статус | Агент | Приоритет |
|---|---|---|---|---|
| T-010 | Верифицировать `[TODO: проверить]` | DONE | arena-agent-sandbox-20260817-1152 | ✅ `research/12` |
| T-011 | Исходы споров 2024–2026 → `research/09-case-outcomes.md` | DONE | arena-agent-sandbox-20260817-1152 | ✅ |
| T-012 | Расширить `tools/listing_risk_score.py` реальными полями листинга | DONE | arena-agent-sandbox-20260817-1152 | 🟡 средний |
| T-013 | Сравнение AliExpress vs Temu vs Amazon по политике возвратов | DONE | arena-agent-sandbox-20260817-1152 | 🟡 средний |
| T-014 | Правовой разбор для Украины: закон о правах споживачів + трансграничная покупка | DONE | arena-agent-sandbox-20260817-1152 | 🟡 средний |
| T-015 | Чарджбэк: когда оправдан, риски для аккаунта, процедура по банкам UA/EU | DONE | arena-agent-sandbox-20260817-1152 | 🟡 средний |
| T-016 | Как AliExpress детектит злоупотребления (сигналы антифрода) — обзор | DONE | arena-agent-sandbox-20260817-1152 | 🟢 низкий |
| T-017 | Тексты обращений в поддержку на английском (для реальных проблем) | DONE | arena-agent-sandbox-20260817-1152 | 🟡 средний |

## Фаза 2.5 — инфраструктура и профиль владельца (сессия 2)

| ID | Задача | Статус | Агент |
|---|---|---|---|
| T-030 | Хранилище секретов + протокол v1.1 | DONE | arena-agent-sandbox-20260817-1152 |
| T-031 | `scripts/bootstrap.sh` — восстановление окружения | DONE | arena-agent-sandbox-20260817-1152 |
| T-032 | `tools/order_ledger.py` — учёт заказов, P&L, оборотка | DONE | arena-agent-sandbox-20260817-1152 |
| T-033 | Логистика UA / EU-forward / dropship | DONE | arena-agent-sandbox-20260817-1152 |
| T-034 | Операционка возвратов дропшиппера | DONE | arena-agent-sandbox-20260817-1152 |
| T-035 | Веб-дашборд над ledger (локальный, без внешних CDN) | DONE | arena-agent-sandbox-20260817-1152 |
| T-036 | Автонапоминания о дедлайнах (cron/systemd timer) | DONE | arena-agent-sandbox-20260817-1152 |
| T-037 | Импорт заказов из CSV-выгрузки AliExpress | DONE | arena-agent-sandbox-20260817-1152 |
| T-038 | Сравнение форвардеров UA↔EU: цена, фотофиксация, сроки (учесть сбор 3 €/подпозиция) | DONE | arena-agent-sandbox-20260817-1152 |
| T-041 | Пересчитать экономику EU-forward после отмены de minimis | DONE | arena-agent-sandbox-20260817-1152 |
| T-042 | Отслеживать customs handling fee ЕС (~€2/посылка, возможно с 11.2026) | DONE | arena-agent-sandbox-20260817-1152 |
| T-043 | Product Identifiers обязательны с 01.11.2026 — оценить влияние | DONE | arena-agent-sandbox-20260817-1152 |

## Фаза 3 — инструменты

| ID | Задача | Статус | Агент | Приоритет |
|---|---|---|---|---|
| T-020 | CLI/веб-дашборд учёта заказов | DONE | arena-agent-sandbox-20260817-1152 | ✅ ledger+dashboard |
| T-021 | Чек-лист распаковки и сбора доказательств (печатная форма) | DONE | arena-agent-sandbox-20260817-1152 | 🟢 низкий |
| T-022 | Скрипт напоминаний о дедлайнах | DONE | arena-agent-sandbox-20260817-1152 | ✅ remind.py |

## Отклонено по границам проекта

| ID | Задача | Статус | Причина |
|---|---|---|---|
| T-900 | Каталог «скрытых товаров» для гарантированного рефанда | BLOCKED-SCOPE | ADR-002, ADR-003 |
| T-901 | Шаблоны текстов спора под ложные причины | BLOCKED-SCOPE | ADR-002 |
| T-902 | Автоматизация массовых споров / мультиаккаунт | BLOCKED-SCOPE | ADR-002 |


## Фаза 4 — качество и устойчивость

| ID | Задача | Статус | Агент |
|---|---|---|---|
| T-047 | Регрессионные тесты + интеграция в bootstrap | DONE | arena-agent-sandbox-20260817-1152 |
| T-048 | Оплата как слой защиты: методы, валюты, обратный путь денег | DONE | arena-agent-sandbox-20260817-1330 |
| T-049 | FX-учёт в order_ledger (потери на конвертации) | DONE | arena-agent-sandbox-20260817-1330 |
| T-050 | evidence_pack — пакет доказательств для спора | DONE | arena-agent-sandbox-20260817-1330 |
| T-051 | remind: контроль зависших возвратов (ARN, 28 дн.) | DONE | arena-agent-sandbox-20260817-1330 |
| T-052 | order_ledger: команда today (сводка дня) | DONE | arena-agent-sandbox-20260817-1330 |
| T-053 | import_orders: FX-колонки из выписки | DONE | arena-agent-sandbox-20260817-1330 |
| T-054 | Дашборд: FX + алерт зависших возвратов | DONE | arena-agent-sandbox-20260817-1330 |
| T-039 | Дашборд: токен-авторизация | DONE | arena-agent-sandbox-20260817-1330 |
| T-055 | backup.sh покрывает data/evidence (без видео) | DONE | arena-agent-sandbox-20260817-1330 |
| T-056 | bootstrap проверяет evidence_pack/import_orders | DONE | arena-agent-sandbox-20260817-1330 |
| T-057 | Верификация TODO: Free Return 3/мес, PayPal UA | DONE | arena-agent-sandbox-20260817-1330 |
| T-058 | Telegram-напоминания под ключ (vault + cron/systemd) | DONE | arena-agent-sandbox-20260817-1330 |
| T-059 | Инструкция проверок владельца (docs/OWNER_CHECKS.md) | DONE | arena-agent-sandbox-20260817-1330 |
| T-060 | Мультивалютный P&L (раздельные итоги, предупреждение) | DONE | arena-agent-sandbox-20260817-1330 |
| T-061 | Атомарная запись ledger + advisory-лок | DONE | arena-agent-sandbox-20260817-1330 |
| T-062 | CI: GitHub Actions на каждый push | DONE | arena-agent-sandbox-20260817-1330 |
| T-063 | HTTP-тесты дашборда (авторизация, API, FX) | DONE | arena-agent-sandbox-20260817-1330 |
| T-064 | save.sh напоминает о бэкапе ledger | DONE | arena-agent-sandbox-20260817-1330 |
| T-065 | Деприкация dispute_deadline_tracker | DONE | arena-agent-sandbox-20260817-1330 |
| T-066 | claim → подсказка evidence_pack | DONE | arena-agent-sandbox-20260817-1330 |
| T-067 | Архив журналов .agent (ADR-005) | DONE | arena-agent-sandbox-20260817-1330 |
| T-068 | Карта живых тем сообществ: TG/форумы/блоги/GitHub | DONE | arena-agent-sandbox-20260817-1330 |
| T-069 | Синхронизация выводов T-068 в research/03, 04, 09 | DONE | arena-agent-sandbox-20260817-1330 |

## Постоянный мониторинг (не закрывается)

| ID | Что проверять | Периодичность | Где зафиксировано |
|---|---|---|---|
| T-040 | Законопроект №15460 (НДС на посылки в UA) | ежеквартально · **прогон 2026-08-17** | `research/12`, `research/10` |
| T-044 | Подтверждение handling fee €2 с 01.11.2026 | до ноября 2026 · **прогон 2026-08-17: не финализирован** | `research/14` §1.1 |
| T-045 | Национальные сборы стран ЕС при смене склада | перед сменой маршрута | `research/14` |
| T-046 | Изменения политики возвратов AliExpress | при аномалиях в исходах | `research/09` |

## Статус бэклога

**Все содержательные задачи фаз 1–3 закрыты** (сессии 1–7, 2026-08-17).
Открытыми остаются только задачи постоянного мониторинга — они по своей природе
не завершаются, а периодически перепроверяются.
