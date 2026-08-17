#!/usr/bin/env python3
"""
Напоминания о горящих дедлайнах Buyer Protection.

Запускается по расписанию (cron / systemd timer / Планировщик Windows).
Пропущенное окно спора закрывает возврат навсегда — это главный риск,
который автоматизация должна снимать.

    python3 tools/remind.py                      # текст в stdout
    python3 tools/remind.py --days 5             # порог срочности
    python3 tools/remind.py --format json        # для интеграций
    python3 tools/remind.py --quiet              # молчать, если нечего сообщить
    python3 tools/remind.py --webhook URL        # POST JSON (Slack/Discord/свой)
    python3 tools/remind.py --telegram-token T --telegram-chat ID
    python3 tools/remind.py --install-cron       # показать строку для crontab

Коды возврата: 0 — нет срочного, 1 — есть срочное, 2 — есть просроченное.
Удобно для мониторинга: `remind.py --quiet || notify-send "AliExpress: дедлайн!"`
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from order_ledger import load, DB_DEFAULT, ROUTES, REASONS, d  # noqa: E402


def collect(db: Path, days: int) -> dict:
    orders = load(db)
    active = [o for o in orders if o.status in ("open", "claimed")]

    overdue, critical, soon = [], [], []
    for o in active:
        left = o.days_left()
        if left is None:
            continue
        if left < 0:
            overdue.append((o, left))
        elif left <= 3:
            critical.append((o, left))
        elif left <= days:
            soon.append((o, left))

    stale = []
    for o in orders:
        if o.status == "claimed" and o.claim_opened:
            age = (date.today() - d(o.claim_opened)).days
            if age > 30:
                stale.append((o, age))

    unconfirmed = [o for o in active if o.delivered and not o.confirmed]
    gap = sum(o.capital_gap() for o in orders)
    pending = sum(o.pending_recovery() for o in orders)

    return {
        "date": date.today().isoformat(),
        "overdue": overdue, "critical": critical, "soon": soon,
        "stale": stale, "unconfirmed": unconfirmed,
        "gap": round(gap, 2), "pending": round(pending, 2),
        "total_active": len(active),
    }


def has_alerts(r: dict) -> bool:
    return bool(r["overdue"] or r["critical"] or r["soon"] or r["stale"])


def as_text(r: dict, plain: bool = False) -> str:
    B, X = ("", "") if plain else ("\033[1m", "\033[0m")
    RED, YEL, GRN = ("", "", "") if plain else ("\033[31m", "\033[33m", "\033[32m")
    out = [f"{B}AliExpress · дедлайны на {r['date']}{X}", "=" * 56]

    def block(title, items, color, fmt):
        if not items:
            return
        out.append("")
        out.append(f"{color}{B}{title}{X}")
        for it in items:
            out.append("  " + fmt(it))

    block("🔴 ПРОСРОЧЕНО — окно закрыто", r["overdue"], RED,
          lambda x: f"{x[0].order_id:<12} {x[0].title[:28]:<28} {abs(x[1])} дн. назад")
    block("🔴 КРИТИЧНО — открывай спор сегодня", r["critical"], RED,
          lambda x: f"{x[0].order_id:<12} {x[0].title[:28]:<28} осталось {x[1]} дн. → {x[0].deadline()[0]}")
    block("🟡 СРОЧНО", r["soon"], YEL,
          lambda x: f"{x[0].order_id:<12} {x[0].title[:28]:<28} осталось {x[1]} дн. → {x[0].deadline()[0]}")
    block("🟡 Споры висят дольше 30 дней — пора эскалировать", r["stale"], YEL,
          lambda x: f"{x[0].order_id:<12} {x[0].title[:24]:<24} {x[1]} дн., "
                    f"{REASONS.get(x[0].claim_reason, x[0].claim_reason)}")

    if r["unconfirmed"]:
        out.append("")
        out.append(f"{GRN}ℹ Доставлено, получение не подтверждено (это правильно):{X}")
        for o in r["unconfirmed"]:
            out.append(f"  {o.order_id:<12} {o.title[:28]:<28} проверь товар до {o.deadline()[0]}")

    if r["gap"] > 0 or r["pending"] > 0:
        out.append("")
        out.append(f"{B}Деньги в пути:{X}")
        if r["pending"]:
            out.append(f"  ожидается от поставщиков: {r['pending']:.2f}")
        if r["gap"]:
            out.append(f"  разрыв оборотки:          {r['gap']:.2f}")

    if not has_alerts(r):
        out.append("")
        out.append(f"{GRN}✓ Горящих дедлайнов нет.{X} Активных заказов: {r['total_active']}")
    else:
        out.append("")
        out.append("Открытый спор можно уточнить. Истёкшее окно — нельзя.")
    return "\n".join(out)


def as_json(r: dict) -> str:
    def pack(items, key):
        return [{"id": o.order_id, "title": o.title, "route": o.route,
                 key: v, "deadline": (o.deadline()[0].isoformat() if o.deadline()[0] else None),
                 "invested": round(o.invested(), 2), "status": o.status} for o, v in items]
    return json.dumps({
        "date": r["date"], "total_active": r["total_active"],
        "overdue": pack(r["overdue"], "days_overdue"),
        "critical": pack(r["critical"], "days_left"),
        "soon": pack(r["soon"], "days_left"),
        "stale_claims": pack(r["stale"], "claim_age_days"),
        "unconfirmed": [{"id": o.order_id, "title": o.title} for o in r["unconfirmed"]],
        "capital_gap": r["gap"], "pending_recovery": r["pending"],
    }, ensure_ascii=False, indent=2)


def post(url: str, payload: dict, timeout: int = 15) -> bool:
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as e:
        print(f"[!] Не удалось отправить: {e}", file=sys.stderr)
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Напоминания о дедлайнах Buyer Protection")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--days", type=int, default=7, help="порог 'скоро', дней")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--plain", action="store_true", help="без ANSI-цветов")
    p.add_argument("--quiet", action="store_true", help="молчать, если нечего сообщить")
    p.add_argument("--webhook", help="URL для POST JSON")
    p.add_argument("--telegram-token"), p.add_argument("--telegram-chat")
    p.add_argument("--install-cron", action="store_true")
    a = p.parse_args()

    if a.install_cron:
        here = Path(__file__).resolve()
        print("Добавь в crontab (crontab -e) — ежедневно в 10:00:\n")
        print(f"  0 10 * * * cd {here.parent.parent} && /usr/bin/python3 {here} "
              f"--days 5 --plain --quiet >> logs/remind.log 2>&1")
        print("\nWindows (Планировщик задач), действие:")
        print(f"  python3 {here} --days 5 --plain --quiet")
        print("\nС уведомлением в Telegram:")
        print(f"  0 10 * * * cd {here.parent.parent} && /usr/bin/python3 {here} "
              f"--days 5 --quiet --telegram-token $TG_TOKEN --telegram-chat $TG_CHAT")
        return 0

    if not a.db.exists():
        if not a.quiet:
            print(f"Файл данных не найден: {a.db}", file=sys.stderr)
        return 0

    r = collect(a.db, a.days)

    if a.quiet and not has_alerts(r):
        return 0

    body = as_json(r) if a.format == "json" else as_text(r, a.plain)
    print(body)

    if a.webhook:
        post(a.webhook, {"text": as_text(r, plain=True), "data": json.loads(as_json(r))})

    if a.telegram_token and a.telegram_chat:
        text = as_text(r, plain=True)
        url = f"https://api.telegram.org/bot{a.telegram_token}/sendMessage"
        post(url, {"chat_id": a.telegram_chat, "text": f"```\n{text[:3800]}\n```",
                   "parse_mode": "Markdown"})

    if r["overdue"]:
        return 2
    if r["critical"] or r["soon"] or r["stale"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
