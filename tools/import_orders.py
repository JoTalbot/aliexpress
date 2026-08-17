#!/usr/bin/env python3
"""
Импорт заказов в ledger из CSV.

AliExpress не даёт стабильной официальной выгрузки для покупателя, поэтому
импортёр устойчив к разным форматам: сам угадывает колонки по типовым именам
(RU/EN/UA) и умеет работать с произвольным CSV, лишь бы был id и название.

    python3 tools/import_orders.py --file orders.csv --dry-run
    python3 tools/import_orders.py --file orders.csv
    python3 tools/import_orders.py --file orders.csv --route dropship --map "Заказ=order_id"
    python3 tools/import_orders.py --template          # создать образец CSV

Существующие заказы по умолчанию пропускаются (--update чтобы обновлять).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from order_ledger import Order, load, save, DB_DEFAULT, ROUTES  # noqa: E402

# Синонимы колонок: канон -> варианты написания
ALIASES: dict[str, list[str]] = {
    "order_id": ["order id", "order_id", "orderid", "order number", "номер заказа",
                 "заказ", "номер", "id", "номер замовлення", "замовлення"],
    "title": ["title", "product", "product name", "item", "name", "название",
              "товар", "наименование", "назва", "найменування"],
    "cost": ["cost", "price", "amount", "total", "order amount", "цена", "стоимость",
             "сумма", "ціна", "вартість", "сума"],
    "ship_cost": ["shipping", "shipping cost", "delivery", "доставка", "стоимость доставки"],
    "sold_price": ["sold", "sold price", "revenue", "продажа", "цена продажи", "выручка"],
    "shipped": ["shipped", "ship date", "dispatch", "shipped date", "отправлен",
                "дата отправки", "відправлено"],
    "delivered": ["delivered", "delivery date", "доставлен", "дата доставки", "доставлено"],
    "currency": ["currency", "валюта"],
    "customer": ["customer", "buyer", "клиент", "покупатель", "клієнт"],
    "free_return": ["free return", "free returns", "бесплатный возврат", "безкоштовне повернення"],
    "route": ["route", "маршрут"],
}

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y",
                "%Y/%m/%d", "%d-%m-%Y", "%b %d, %Y", "%d %b %Y"]

TRUTHY = {"1", "yes", "y", "true", "да", "так", "+", "free return", "free returns"}


def norm(s: str) -> str:
    return re.sub(r"[^a-zа-яїієґ0-9 ]", " ", (s or "").strip().lower()).strip()


def build_mapping(headers: list[str], manual: dict[str, str]) -> dict[str, str]:
    """Возвращает {канон: имя колонки в файле}."""
    found: dict[str, str] = {}
    normalized = {h: norm(h) for h in headers}

    for canon, variants in ALIASES.items():
        if canon in manual.values():
            for src, dst in manual.items():
                if dst == canon and src in headers:
                    found[canon] = src
            continue
        for h, nh in normalized.items():
            if nh in variants:
                found[canon] = h
                break
        if canon not in found:  # частичное совпадение
            for h, nh in normalized.items():
                if any(v in nh for v in variants):
                    found[canon] = h
                    break
    return found


def parse_date(v: str) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    v = re.sub(r"\s+\d{1,2}:\d{2}(:\d{2})?$", "", v)  # отрезать время
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(v, f).date().isoformat()
        except ValueError:
            continue
    return None


def parse_money(v: str) -> float:
    if not v:
        return 0.0
    s = re.sub(r"[^\d.,\-]", "", str(v)).replace(",", ".")
    if s.count(".") > 1:  # 1.234.56 -> 1234.56
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return abs(float(s)) if s not in ("", ".", "-") else 0.0
    except ValueError:
        return 0.0


def main() -> int:
    p = argparse.ArgumentParser(description="Импорт заказов из CSV в ledger")
    p.add_argument("--file", type=Path)
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--route", choices=list(ROUTES), default="ua-direct",
                   help="маршрут по умолчанию, если нет в файле")
    p.add_argument("--currency", default="USD")
    p.add_argument("--delimiter", default=None, help="по умолчанию определяется автоматически")
    p.add_argument("--map", action="append", default=[],
                   help='ручное сопоставление: --map "Колонка=order_id"')
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--update", action="store_true", help="обновлять существующие заказы")
    p.add_argument("--template", action="store_true", help="создать образец CSV и выйти")
    a = p.parse_args()

    if a.template:
        path = Path("orders_template.csv")
        path.write_text(
            "order_id,title,cost,shipping,sold,shipped,delivered,currency,free_return,route\n"
            "AE-1001,TWS наушники,12.40,0,29.90,2026-08-01,2026-08-14,USD,yes,dropship\n"
            "AE-1002,Ремешок 22мм,4.10,0,0,2026-08-05,,USD,no,ua-direct\n",
            encoding="utf-8")
        print(f"✓ Образец создан: {path}")
        print("  Заполни своими данными и запусти:")
        print(f"  python3 tools/import_orders.py --file {path} --dry-run")
        return 0

    if not a.file:
        p.error("нужен --file (или --template для образца)")
    if not a.file.exists():
        print(f"Файл не найден: {a.file}", file=sys.stderr)
        return 1

    manual = {}
    for m in a.map:
        if "=" in m:
            src, dst = m.split("=", 1)
            manual[src.strip()] = dst.strip()

    raw = a.file.read_text(encoding="utf-8-sig")
    delim = a.delimiter
    if not delim:
        try:
            delim = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","

    rows = list(csv.DictReader(raw.splitlines(), delimiter=delim))
    if not rows:
        print("Файл пуст или не распознан", file=sys.stderr)
        return 1

    headers = list(rows[0].keys())
    mapping = build_mapping(headers, manual)

    print(f"Разделитель: {delim!r} · строк: {len(rows)}")
    print("Распознанные колонки:")
    for canon in ALIASES:
        src = mapping.get(canon)
        mark = "✓" if src else "·"
        print(f"  {mark} {canon:<12} ← {src or '(нет)'}")

    if "order_id" not in mapping or "title" not in mapping:
        print("\n✗ Обязательны колонки order_id и title.", file=sys.stderr)
        print('  Задай вручную: --map "Номер заказа=order_id" --map "Товар=title"',
              file=sys.stderr)
        return 1

    orders = load(a.db)
    existing = {o.order_id: o for o in orders}
    added = updated = skipped = 0
    problems: list[str] = []

    def get(row: dict, canon: str) -> str:
        col = mapping.get(canon)
        return (row.get(col) or "").strip() if col else ""

    for i, row in enumerate(rows, 2):
        oid = get(row, "order_id")
        title = get(row, "title")
        if not oid:
            problems.append(f"строка {i}: пустой order_id — пропущена")
            continue
        if oid in existing and not a.update:
            skipped += 1
            continue

        route = get(row, "route") or a.route
        if route not in ROUTES:
            route = a.route

        o = Order(
            order_id=oid,
            title=title or oid,
            cost=parse_money(get(row, "cost")),
            ship_cost=parse_money(get(row, "ship_cost")),
            sold_price=parse_money(get(row, "sold_price")),
            currency=get(row, "currency") or a.currency,
            route=route,
            customer=get(row, "customer"),
            shipped=parse_date(get(row, "shipped")),
            delivered=parse_date(get(row, "delivered")),
            free_return=norm(get(row, "free_return")) in TRUTHY,
        )
        if get(row, "shipped") and not o.shipped:
            problems.append(f"строка {i} ({oid}): не распознана дата "
                            f"{get(row, 'shipped')!r} — заполни вручную")

        if oid in existing:
            orders[orders.index(existing[oid])] = o
            updated += 1
        else:
            orders.append(o)
            existing[oid] = o
            added += 1

    print(f"\nДобавить: {added} · обновить: {updated} · пропустить (уже есть): {skipped}")
    if problems:
        print("\nПредупреждения:")
        for w in problems[:15]:
            print(f"  ⚠ {w}")
        if len(problems) > 15:
            print(f"  … ещё {len(problems) - 15}")

    if a.dry_run:
        print("\n[dry-run] Файл не изменён. Убери --dry-run для записи.")
        return 0

    save(a.db, orders)
    print(f"\n✓ Сохранено в {a.db}")
    print("  Проверь: python3 tools/order_ledger.py list")
    print("  Дедлайны: python3 tools/remind.py --days 7")
    return 0


if __name__ == "__main__":
    sys.exit(main())
