#!/usr/bin/env python3
"""
Трекер дедлайнов Buyer Protection на AliExpress.

⚠ УСТАРЕЛ (T-065, 2026-08-17): функциональность полностью покрыта `order_ledger.py`
(дедлайны + P&L + FX + споры в одном месте) и `remind.py` (напоминания).
Оставлен рабочим для совместимости, но НЕ развивать — новые фичи только в ledger.
Миграция: заказы отсюда можно перенести через `order_ledger.py add`.

Задача: не потерять окно спора. Пропущенный дедлайн закрывает возврат навсегда,
независимо от качества доказательств.

Хранилище: orders.json рядом со скриптом (можно переопределить через --db).

Примеры:
    python3 dispute_deadline_tracker.py add --id 8012345678901234 \
        --title "Наушники TWS" --amount 24.90 --shipped 2026-08-01 \
        --free-return --note "видео распаковки снято"

    python3 dispute_deadline_tracker.py delivered --id 8012345678901234 --date 2026-08-15
    python3 dispute_deadline_tracker.py list
    python3 dispute_deadline_tracker.py check --days 7
    python3 dispute_deadline_tracker.py close --id 8012345678901234

Замечание: сроки — типовые ориентиры. Обязывающая цифра — счётчик на странице заказа.
Настраивается через --bp-days / --after-delivery-days.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path

DB_DEFAULT = Path(__file__).with_name("orders.json")

# Типовые окна (см. research/01-buyer-protection-rules.md)
BP_DAYS_DEFAULT = 60           # защита от даты отправки, если получение не подтверждено
AFTER_DELIVERY_DAYS = 15       # окно после подтверждения получения
FREE_RETURN_DAYS = 15          # окно бесплатного возврата от получения
EARLY_DISPUTE_DAYS = 10        # раньше спор обычно открыть нельзя


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass
class Order:
    order_id: str
    title: str
    amount: float = 0.0
    currency: str = "USD"
    shipped: str | None = None
    delivered: str | None = None
    confirmed: str | None = None
    free_return: bool = False
    bp_days: int = BP_DAYS_DEFAULT
    after_delivery_days: int = AFTER_DELIVERY_DAYS
    status: str = "open"          # open | closed | disputed
    notes: list[str] = field(default_factory=list)

    # ---- расчёт дедлайнов -------------------------------------------------

    def dispute_opens_at(self) -> date | None:
        if not self.shipped:
            return None
        return parse_date(self.shipped) + timedelta(days=EARLY_DISPUTE_DAYS)

    def deadline(self) -> tuple[date | None, str]:
        """Возвращает (дата, объяснение) для ближайшего критичного дедлайна."""
        if self.confirmed:
            d = parse_date(self.confirmed) + timedelta(days=self.after_delivery_days)
            return d, f"{self.after_delivery_days} дн. после подтверждения получения"
        if self.delivered and self.free_return:
            d = parse_date(self.delivered) + timedelta(days=FREE_RETURN_DAYS)
            return d, f"{FREE_RETURN_DAYS} дн. Free Return от доставки"
        if self.delivered:
            d = parse_date(self.delivered) + timedelta(days=self.after_delivery_days)
            return d, f"{self.after_delivery_days} дн. после доставки (получение не подтверждено)"
        if self.shipped:
            d = parse_date(self.shipped) + timedelta(days=self.bp_days + AFTER_DELIVERY_DAYS)
            return d, f"BP {self.bp_days} дн. от отправки + {AFTER_DELIVERY_DAYS} дн. на спор"
        return None, "нет даты отправки"

    def days_left(self, today: date | None = None) -> int | None:
        today = today or date.today()
        d, _ = self.deadline()
        return None if d is None else (d - today).days

    def urgency(self, today: date | None = None) -> str:
        left = self.days_left(today)
        if self.status != "open":
            return "—"
        if left is None:
            return "?"
        if left < 0:
            return "ПРОСРОЧЕНО"
        if left <= 3:
            return "КРИТИЧНО"
        if left <= 7:
            return "СРОЧНО"
        return "ок"


def load(db: Path) -> list[Order]:
    if not db.exists():
        return []
    raw = json.loads(db.read_text(encoding="utf-8"))
    return [Order(**item) for item in raw]


def save(db: Path, orders: list[Order]) -> None:
    db.write_text(
        json.dumps([asdict(o) for o in orders], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find(orders: list[Order], order_id: str) -> Order:
    for o in orders:
        if o.order_id == order_id:
            return o
    raise SystemExit(f"Заказ {order_id} не найден")


def render(orders: list[Order]) -> str:
    if not orders:
        return "Заказов нет."
    rows = []
    header = f"{'ЗАКАЗ':<20} {'ТОВАР':<26} {'СУММА':>9}  {'ДЕДЛАЙН':<12} {'ОСТ.':>5}  {'СТАТУС':<11} FR"
    rows.append(header)
    rows.append("-" * len(header))
    for o in sorted(orders, key=lambda x: (x.days_left() is None, x.days_left() or 0)):
        d, _ = o.deadline()
        rows.append(
            f"{o.order_id:<20} {o.title[:26]:<26} {o.amount:>7.2f} {o.currency[:2]}  "
            f"{(d.isoformat() if d else '—'):<12} "
            f"{(str(o.days_left()) if o.days_left() is not None else '—'):>5}  "
            f"{o.urgency():<11} {'да' if o.free_return else '—'}"
        )
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Трекер дедлайнов споров AliExpress")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="добавить заказ")
    a.add_argument("--id", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--amount", type=float, default=0.0)
    a.add_argument("--currency", default="USD")
    a.add_argument("--shipped", help="YYYY-MM-DD, дата отправки")
    a.add_argument("--free-return", action="store_true")
    a.add_argument("--bp-days", type=int, default=BP_DAYS_DEFAULT)
    a.add_argument("--note")

    d = sub.add_parser("delivered", help="отметить доставку")
    d.add_argument("--id", required=True)
    d.add_argument("--date", required=True)

    c = sub.add_parser("confirm", help="отметить подтверждение получения (осторожно!)")
    c.add_argument("--id", required=True)
    c.add_argument("--date", required=True)

    n = sub.add_parser("note", help="добавить заметку")
    n.add_argument("--id", required=True)
    n.add_argument("--text", required=True)

    cl = sub.add_parser("close", help="закрыть заказ (претензий нет)")
    cl.add_argument("--id", required=True)

    ds = sub.add_parser("dispute", help="отметить, что спор открыт")
    ds.add_argument("--id", required=True)

    sub.add_parser("list", help="показать все заказы")

    ch = sub.add_parser("check", help="показать горящие дедлайны")
    ch.add_argument("--days", type=int, default=7)

    args = p.parse_args()
    orders = load(args.db)

    if args.cmd == "add":
        if any(o.order_id == args.id for o in orders):
            raise SystemExit(f"Заказ {args.id} уже есть")
        o = Order(
            order_id=args.id, title=args.title, amount=args.amount,
            currency=args.currency, shipped=args.shipped,
            free_return=args.free_return, bp_days=args.bp_days,
            notes=[args.note] if args.note else [],
        )
        orders.append(o)
        save(args.db, orders)
        dl, why = o.deadline()
        print(f"Добавлен {o.order_id}. Дедлайн: {dl} ({why})")
        opens = o.dispute_opens_at()
        if opens:
            print(f"Спор обычно можно открыть с: {opens}")

    elif args.cmd == "delivered":
        o = find(orders, args.id)
        o.delivered = args.date
        save(args.db, orders)
        dl, why = o.deadline()
        print(f"Доставка {args.date}. Новый дедлайн: {dl} ({why})")
        print("Напоминание: не подтверждай получение, пока товар не проверен.")

    elif args.cmd == "confirm":
        o = find(orders, args.id)
        o.confirmed = args.date
        save(args.db, orders)
        dl, why = o.deadline()
        print(f"Получение подтверждено {args.date}. Осталось окно до {dl} ({why})")

    elif args.cmd == "note":
        o = find(orders, args.id)
        o.notes.append(f"{date.today().isoformat()}: {args.text}")
        save(args.db, orders)
        print("Заметка добавлена")

    elif args.cmd == "close":
        o = find(orders, args.id)
        o.status = "closed"
        save(args.db, orders)
        print(f"Заказ {args.id} закрыт")

    elif args.cmd == "dispute":
        o = find(orders, args.id)
        o.status = "disputed"
        save(args.db, orders)
        print(f"Заказ {args.id} помечен как спорный. Не закрывай спор до решения.")

    elif args.cmd == "list":
        print(render(orders))

    elif args.cmd == "check":
        hot = [o for o in orders if o.status == "open"
               and o.days_left() is not None and o.days_left() <= args.days]
        if not hot:
            print(f"Горящих дедлайнов в ближайшие {args.days} дн. нет.")
        else:
            print(f"Горящие дедлайны (≤ {args.days} дн.):\n")
            print(render(hot))
            print("\nДействие: если есть сомнения — открывай спор ДО истечения окна.")
            print("Открытый спор можно уточнить, истёкшее окно — нельзя.")


if __name__ == "__main__":
    main()
