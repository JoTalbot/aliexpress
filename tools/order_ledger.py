#!/usr/bin/env python3
"""
Order Ledger — учёт заказов AliExpress для покупателя и дропшиппера.

Закрывает три задачи сразу:
  1. Дедлайны Buyer Protection (не потерять окно спора).
  2. P&L по заказу: закупка, доставка, продажа, возврат, маржа.
  3. Разрыв оборотного капитала дропшиппера: клиенту вернул сегодня,
     от поставщика получил через недели.

Хранилище: data/ledger.json (в .gitignore — личные данные не коммитятся).

    python3 order_ledger.py add --id AE-1001 --title "TWS наушники" \
        --cost 12.40 --ship 0 --shipped 2026-08-01 --free-return \
        --route ua-direct --sold 29.90 --customer "customer#417"

    python3 order_ledger.py delivered --id AE-1001 --date 2026-08-18
    python3 order_ledger.py claim --id AE-1001 --reason damaged --ask 12.40
    python3 order_ledger.py refunded --id AE-1001 --amount 12.40 --date 2026-09-02
    python3 order_ledger.py charged --id AE-1001 --amount 520.35 --currency UAH
    python3 order_ledger.py refund-received --id AE-1001 --amount 498.10
    python3 order_ledger.py fx
    python3 order_ledger.py list
    python3 order_ledger.py deadlines --days 7
    python3 order_ledger.py pnl
    python3 order_ledger.py exposure
    python3 order_ledger.py export --csv data/ledger.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path

DB_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "ledger.json"

BP_DAYS_DEFAULT = 60
AFTER_DELIVERY_DAYS = 15
FREE_RETURN_DAYS = 15
EARLY_DISPUTE_DAYS = 10

ROUTES = {
    "ua-direct":   "Прямо в Украину (Nova Poshta Global / Укрпошта / Meest)",
    "ua-local":    "С локального склада в Украине",
    "eu-forward":  "На адрес в ЕС + пересылка форвардером",
    "dropship":    "Прямая отправка конечному покупателю (дропшиппинг)",
    "other":       "Другое",
}

REASONS = {
    "not-received": "Товар не получен",
    "damaged":      "Повреждён при доставке",
    "wrong-item":   "Прислали не то",
    "not-working":  "Неисправен",
    "shortage":     "Недостача по количеству",
    "not-as-desc":  "Не соответствует описанию",
    "free-return":  "Free Return (без причины)",
}


def d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


@dataclass
class Order:
    order_id: str
    title: str
    cost: float = 0.0              # закупка у поставщика
    ship_cost: float = 0.0         # доставка/форвардинг/пошлина
    sold_price: float = 0.0        # цена продажи конечному клиенту (дропшиппинг)
    currency: str = "USD"
    route: str = "ua-direct"
    customer: str = ""
    shipped: str | None = None
    delivered: str | None = None
    confirmed: str | None = None
    free_return: bool = False
    bp_days: int = BP_DAYS_DEFAULT
    status: str = "open"           # open | claimed | refunded | closed | lost
    claim_reason: str = ""
    claim_asked: float = 0.0
    claim_opened: str | None = None
    refund_amount: float = 0.0
    refund_date: str | None = None
    customer_refunded: float = 0.0
    customer_refund_date: str | None = None
    # ---- FX: факты по карте (research/17) ----
    card_currency: str = "UAH"     # валюта карты, которой платили
    card_charged: float = 0.0      # факт списания с карты (по выписке)
    card_refunded: float = 0.0     # факт зачисления возврата на карту (по выписке)
    notes: list[str] = field(default_factory=list)

    # ---- дедлайны ----
    def dispute_opens_at(self) -> date | None:
        return d(self.shipped) + timedelta(days=EARLY_DISPUTE_DAYS) if self.shipped else None

    def deadline(self) -> tuple[date | None, str]:
        if self.confirmed:
            return d(self.confirmed) + timedelta(days=AFTER_DELIVERY_DAYS), \
                   f"{AFTER_DELIVERY_DAYS} дн. после подтверждения"
        if self.delivered and self.free_return:
            return d(self.delivered) + timedelta(days=FREE_RETURN_DAYS), \
                   f"{FREE_RETURN_DAYS} дн. Free Return"
        if self.delivered:
            return d(self.delivered) + timedelta(days=AFTER_DELIVERY_DAYS), \
                   f"{AFTER_DELIVERY_DAYS} дн. после доставки"
        if self.shipped:
            return d(self.shipped) + timedelta(days=self.bp_days + AFTER_DELIVERY_DAYS), \
                   f"BP {self.bp_days}+{AFTER_DELIVERY_DAYS} дн. от отправки"
        return None, "нет даты отправки"

    def days_left(self, today: date | None = None) -> int | None:
        dl, _ = self.deadline()
        return None if dl is None else (dl - (today or date.today())).days

    def urgency(self) -> str:
        if self.status in ("closed", "refunded", "lost"):
            return "—"
        left = self.days_left()
        if left is None:
            return "?"
        if left < 0:
            return "ПРОСРОЧЕНО"
        if left <= 3:
            return "КРИТИЧНО"
        if left <= 7:
            return "СРОЧНО"
        return "ок"

    # ---- деньги ----
    def invested(self) -> float:
        return self.cost + self.ship_cost

    def net(self) -> float:
        """Итог по заказу: выручка + возврат от поставщика − затраты − возврат клиенту."""
        return (self.sold_price + self.refund_amount
                - self.invested() - self.customer_refunded)

    def pending_recovery(self) -> float:
        """Ожидаемые к возврату деньги от поставщика (заявлено, но не получено)."""
        if self.status == "claimed":
            return self.claim_asked or self.invested()
        return 0.0

    def capital_gap(self) -> float:
        """Разрыв оборотки: вернул клиенту, от поставщика ещё не получил."""
        return max(0.0, self.customer_refunded - self.refund_amount)

    # ---- FX (research/17): потери на конвертации при возврате ----
    def purchase_rate(self) -> float | None:
        """Фактический курс покупки: единиц валюты карты за единицу валюты заказа."""
        if self.card_charged > 0 and self.invested() > 0:
            return self.card_charged / self.invested()
        return None

    def fx_loss(self) -> float | None:
        """Потеря на конвертации при возврате, в валюте карты.

        Сколько возврат «должен был» принести по курсу покупки минус сколько
        реально пришло на карту. Положительное значение = потеря.
        Считается только когда известны оба факта по выписке.
        """
        rate = self.purchase_rate()
        if rate is None or self.refund_amount <= 0 or self.card_refunded <= 0:
            return None
        return self.refund_amount * rate - self.card_refunded


def load(db: Path) -> list[Order]:
    if not db.exists():
        return []
    return [Order(**i) for i in json.loads(db.read_text(encoding="utf-8"))]


def save(db: Path, orders: list[Order]) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_text(json.dumps([asdict(o) for o in orders], ensure_ascii=False, indent=2),
                  encoding="utf-8")


def find(orders: list[Order], oid: str) -> Order:
    for o in orders:
        if o.order_id == oid:
            return o
    raise SystemExit(f"Заказ {oid} не найден")


def table(orders: list[Order]) -> str:
    if not orders:
        return "Заказов нет."
    h = (f"{'ЗАКАЗ':<12} {'ТОВАР':<22} {'МАРШРУТ':<11} {'ВЛОЖ':>7} {'ПРОД':>7} "
         f"{'ВОЗВР':>7} {'ИТОГ':>8}  {'ДЕДЛАЙН':<11} {'ОСТ':>4} {'СТАТУС':<9} {'СРОЧН':<10}")
    rows = [h, "-" * len(h)]
    for o in sorted(orders, key=lambda x: (x.days_left() is None, x.days_left() or 0)):
        dl, _ = o.deadline()
        rows.append(
            f"{o.order_id:<12} {o.title[:22]:<22} {o.route[:11]:<11} "
            f"{o.invested():>7.2f} {o.sold_price:>7.2f} {o.refund_amount:>7.2f} "
            f"{o.net():>8.2f}  {(dl.isoformat() if dl else '—'):<11} "
            f"{(str(o.days_left()) if o.days_left() is not None else '—'):>4} "
            f"{o.status:<9} {o.urgency():<10}")
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Учёт заказов AliExpress: дедлайны + P&L")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    s = p.add_subparsers(dest="cmd", required=True)

    a = s.add_parser("add")
    a.add_argument("--id", required=True); a.add_argument("--title", required=True)
    a.add_argument("--cost", type=float, default=0.0)
    a.add_argument("--ship", type=float, default=0.0)
    a.add_argument("--sold", type=float, default=0.0)
    a.add_argument("--currency", default="USD")
    a.add_argument("--route", choices=list(ROUTES), default="ua-direct")
    a.add_argument("--customer", default="")
    a.add_argument("--shipped"); a.add_argument("--free-return", action="store_true")
    a.add_argument("--bp-days", type=int, default=BP_DAYS_DEFAULT)
    a.add_argument("--note")

    for name in ("delivered", "confirm"):
        x = s.add_parser(name); x.add_argument("--id", required=True); x.add_argument("--date", required=True)

    c = s.add_parser("claim"); c.add_argument("--id", required=True)
    c.add_argument("--reason", choices=list(REASONS), required=True)
    c.add_argument("--ask", type=float, default=0.0)
    c.add_argument("--date", default=date.today().isoformat())

    r = s.add_parser("refunded"); r.add_argument("--id", required=True)
    r.add_argument("--amount", type=float, required=True)
    r.add_argument("--date", default=date.today().isoformat())

    cr = s.add_parser("customer-refund"); cr.add_argument("--id", required=True)
    cr.add_argument("--amount", type=float, required=True)
    cr.add_argument("--date", default=date.today().isoformat())

    ch = s.add_parser("charged", help="факт списания с карты по выписке")
    ch.add_argument("--id", required=True)
    ch.add_argument("--amount", type=float, required=True)
    ch.add_argument("--currency", default="UAH")

    rr = s.add_parser("refund-received", help="факт зачисления возврата на карту по выписке")
    rr.add_argument("--id", required=True)
    rr.add_argument("--amount", type=float, required=True)
    rr.add_argument("--date", default=date.today().isoformat())

    s.add_parser("fx", help="отчёт по конвертационным потерям")

    s.add_parser("today", help="сводка дня: дедлайны + зависшие возвраты + деньги в пути")

    n = s.add_parser("note"); n.add_argument("--id", required=True); n.add_argument("--text", required=True)
    cl = s.add_parser("close"); cl.add_argument("--id", required=True)
    lo = s.add_parser("lost"); lo.add_argument("--id", required=True)
    s.add_parser("list")
    dd = s.add_parser("deadlines"); dd.add_argument("--days", type=int, default=7)
    s.add_parser("pnl"); s.add_parser("exposure")
    sh = s.add_parser("show"); sh.add_argument("--id", required=True)
    ex = s.add_parser("export"); ex.add_argument("--csv", type=Path, required=True)

    args = p.parse_args()
    orders = load(args.db)

    if args.cmd == "add":
        if any(o.order_id == args.id for o in orders):
            raise SystemExit(f"Заказ {args.id} уже есть")
        o = Order(order_id=args.id, title=args.title, cost=args.cost, ship_cost=args.ship,
                  sold_price=args.sold, currency=args.currency, route=args.route,
                  customer=args.customer, shipped=args.shipped, free_return=args.free_return,
                  bp_days=args.bp_days, notes=[args.note] if args.note else [])
        orders.append(o); save(args.db, orders)
        dl, why = o.deadline()
        print(f"✓ {o.order_id} добавлен | маршрут: {ROUTES[o.route]}")
        print(f"  Дедлайн спора: {dl} ({why})")
        if o.dispute_opens_at():
            print(f"  Спор можно открыть с: {o.dispute_opens_at()}")

    elif args.cmd in ("delivered", "confirm"):
        o = find(orders, args.id)
        setattr(o, "delivered" if args.cmd == "delivered" else "confirmed", args.date)
        save(args.db, orders)
        dl, why = o.deadline()
        print(f"✓ {args.cmd} {args.date} | новый дедлайн: {dl} ({why})")
        if args.cmd == "delivered":
            print("  Напоминание: не подтверждай получение до проверки товара.")

    elif args.cmd == "claim":
        o = find(orders, args.id)
        o.status, o.claim_reason = "claimed", args.reason
        o.claim_asked = args.ask or o.invested(); o.claim_opened = args.date
        o.notes.append(f"{args.date}: заявка — {REASONS[args.reason]}, запрошено {o.claim_asked:.2f}")
        save(args.db, orders)
        print(f"✓ Заявка открыта: {REASONS[args.reason]} на {o.claim_asked:.2f} {o.currency}")
        print("  Не закрывай спор до решения. Отклоняй несоразмерные предложения.")

    elif args.cmd == "refunded":
        o = find(orders, args.id)
        o.refund_amount, o.refund_date, o.status = args.amount, args.date, "refunded"
        o.notes.append(f"{args.date}: возврат от поставщика {args.amount:.2f}")
        save(args.db, orders)
        print(f"✓ Возврат {args.amount:.2f} {o.currency} | итог по заказу: {o.net():+.2f}")

    elif args.cmd == "customer-refund":
        o = find(orders, args.id)
        o.customer_refunded, o.customer_refund_date = args.amount, args.date
        o.notes.append(f"{args.date}: возврат клиенту {args.amount:.2f}")
        save(args.db, orders)
        print(f"✓ Клиенту возвращено {args.amount:.2f} | разрыв оборотки: {o.capital_gap():.2f}")

    elif args.cmd == "charged":
        o = find(orders, args.id)
        o.card_charged, o.card_currency = args.amount, args.currency
        o.notes.append(f"{date.today().isoformat()}: списано с карты {args.amount:.2f} {args.currency}")
        save(args.db, orders)
        rate = o.purchase_rate()
        print(f"✓ Списание {args.amount:.2f} {args.currency}"
              + (f" | курс покупки: {rate:.4f} {args.currency}/{o.currency}" if rate else ""))

    elif args.cmd == "refund-received":
        o = find(orders, args.id)
        o.card_refunded = args.amount
        o.notes.append(f"{args.date}: возврат на карту {args.amount:.2f} {o.card_currency}")
        save(args.db, orders)
        loss = o.fx_loss()
        print(f"✓ На карту пришло {args.amount:.2f} {o.card_currency}")
        if loss is not None:
            sign = "потеря" if loss > 0 else "выигрыш"
            print(f"  FX-{sign} на конвертации: {abs(loss):.2f} {o.card_currency} (research/17 §3)")

    elif args.cmd == "fx":
        rows = [o for o in orders if o.fx_loss() is not None]
        print("=" * 58); print("FX: ПОТЕРИ НА КОНВЕРТАЦИИ ПРИ ВОЗВРАТАХ"); print("=" * 58)
        if not rows:
            print("Нет заказов с полной парой фактов (charged + refund-received).")
            print("Вноси суммы по выписке: charged / refund-received.")
        else:
            total = 0.0
            for o in rows:
                loss = o.fx_loss(); total += loss
                print(f"  {o.order_id:<12} {o.title[:20]:<20} "
                      f"курс {o.purchase_rate():.4f} | возврат {o.refund_amount:.2f} {o.currency} "
                      f"→ {o.card_refunded:.2f} {o.card_currency} | FX {loss:+.2f}")
            cur = rows[0].card_currency
            print("-" * 58)
            print(f"  ИТОГО FX-потери: {total:+.2f} {cur}")
            charged = sum(o.card_charged for o in rows)
            if charged:
                print(f"  Доля от оборота по этим заказам: {total / charged * 100:.2f}%")
            print("\n  Снижение потерь: USD-карта + валюта USD на сайте (research/17 §3.3).")

    elif args.cmd == "today":
        # Единая сводка дня. Логика живёт в remind.py — здесь только вызов,
        # чтобы не дублировать расчёты (импорт внутри ветки: remind сам импортирует ledger).
        import remind
        print(remind.as_text(remind.collect(args.db, days=7)))

    elif args.cmd == "note":
        o = find(orders, args.id)
        o.notes.append(f"{date.today().isoformat()}: {args.text}")
        save(args.db, orders); print("✓ Заметка добавлена")

    elif args.cmd in ("close", "lost"):
        o = find(orders, args.id); o.status = "closed" if args.cmd == "close" else "lost"
        save(args.db, orders); print(f"✓ {args.id} → {o.status}")

    elif args.cmd == "list":
        print(table(orders))

    elif args.cmd == "show":
        o = find(orders, args.id)
        print(json.dumps(asdict(o), ensure_ascii=False, indent=2))
        dl, why = o.deadline()
        print(f"\nДедлайн: {dl} ({why}) | осталось: {o.days_left()} дн. | {o.urgency()}")
        print(f"Вложено: {o.invested():.2f} | итог: {o.net():+.2f} | к возврату: {o.pending_recovery():.2f}")
        if o.fx_loss() is not None:
            print(f"FX-потеря на конвертации: {o.fx_loss():+.2f} {o.card_currency}")

    elif args.cmd == "deadlines":
        hot = [o for o in orders if o.status in ("open", "claimed")
               and o.days_left() is not None and o.days_left() <= args.days]
        if not hot:
            print(f"Горящих дедлайнов в ближайшие {args.days} дн. нет.")
        else:
            print(f"⚠ ГОРЯЩИЕ ДЕДЛАЙНЫ (≤ {args.days} дн.)\n")
            print(table(hot))
            print("\nЕсли есть сомнения — открывай спор ДО истечения окна.")

    elif args.cmd == "pnl":
        act = [o for o in orders if o.status != "lost"]
        inv = sum(o.invested() for o in act)
        rev = sum(o.sold_price for o in act)
        ref = sum(o.refund_amount for o in act)
        cref = sum(o.customer_refunded for o in act)
        net = sum(o.net() for o in act)
        pend = sum(o.pending_recovery() for o in orders)
        lost = sum(o.invested() for o in orders if o.status == "lost")
        print("=" * 58)
        print("P&L ПО ЗАКАЗАМ")
        print("=" * 58)
        print(f"  Заказов активных:            {len(act)}")
        print(f"  Вложено (закупка+доставка):  {inv:>10.2f}")
        print(f"  Выручка от продаж:           {rev:>10.2f}")
        print(f"  Возвращено поставщиком:      {ref:>10.2f}")
        print(f"  Возвращено клиентам:        -{cref:>10.2f}")
        print("-" * 58)
        print(f"  ИТОГО:                       {net:>+10.2f}")
        print(f"  Ожидается к возврату:        {pend:>10.2f}")
        print(f"  Списано в потери:            {lost:>10.2f}")
        if inv:
            print(f"  Маржинальность:              {net / inv * 100:>9.1f}%")
        rate = len([o for o in orders if o.status in ("claimed", "refunded")]) / len(orders) * 100 if orders else 0
        print(f"  Доля заказов с претензией:   {rate:>9.1f}%")
        fx_rows = [o for o in orders if o.fx_loss() is not None]
        if fx_rows:
            fx_total = sum(o.fx_loss() for o in fx_rows)
            print(f"  FX-потери на конвертации:    {fx_total:>10.2f} {fx_rows[0].card_currency} (см. команду fx)")
        if rate > 20:
            print("\n  ⚠ Высокая доля споров повышает риск ограничений на аккаунте.")
            print("    См. research/06 — платформа отслеживает поведенческие паттерны.")

    elif args.cmd == "exposure":
        gap = [(o, o.capital_gap()) for o in orders if o.capital_gap() > 0]
        pend = [(o, o.pending_recovery()) for o in orders if o.pending_recovery() > 0]
        print("=" * 58); print("ОБОРОТНЫЙ КАПИТАЛ / ЭКСПОЗИЦИЯ"); print("=" * 58)
        if gap:
            print("\nРазрыв (клиенту вернул, от поставщика — нет):")
            for o, g in sorted(gap, key=lambda x: -x[1]):
                print(f"  {o.order_id:<12} {o.title[:24]:<24} {g:>8.2f}")
            print(f"  {'ИТОГО':<37} {sum(g for _, g in gap):>8.2f}")
        else:
            print("\nРазрывов оборотки нет.")
        if pend:
            print("\nОжидается от поставщика:")
            for o, v in sorted(pend, key=lambda x: -x[1]):
                age = (date.today() - d(o.claim_opened)).days if o.claim_opened else 0
                flag = "  ⚠ висит долго" if age > 30 else ""
                print(f"  {o.order_id:<12} {o.title[:20]:<20} {v:>8.2f}  {age:>3} дн.{flag}")
            print(f"  {'ИТОГО':<33} {sum(v for _, v in pend):>8.2f}")

    elif args.cmd == "export":
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["order_id", "title", "route", "invested", "sold", "supplier_refund",
                        "customer_refund", "net", "status", "deadline", "days_left"])
            for o in orders:
                dl, _ = o.deadline()
                w.writerow([o.order_id, o.title, o.route, f"{o.invested():.2f}",
                            f"{o.sold_price:.2f}", f"{o.refund_amount:.2f}",
                            f"{o.customer_refunded:.2f}", f"{o.net():.2f}", o.status,
                            dl.isoformat() if dl else "", o.days_left()])
        print(f"✓ Экспортировано: {args.csv}")


if __name__ == "__main__":
    main()
