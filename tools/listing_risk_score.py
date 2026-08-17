#!/usr/bin/env python3
"""
Скоринг листинга AliExpress по «возвратопригодности».

Оценивает, насколько вероятно вернуть деньги при реальной проблеме
и во сколько это обойдётся. Методика: research/04-low-risk-product-selection.md

Использование:
    python3 listing_risk_score.py --interactive
    python3 listing_risk_score.py --json listing.json
    python3 listing_risk_score.py --free-return --choice --store-age 24 \
        --rating 4.8 --sales 2400 --price 32 --photo-reviews --size-chart

Формат JSON: любые ключи из списка параметров, например
    {"free_return": true, "choice": true, "store_age_months": 24,
     "rating": 4.8, "sales": 2400, "price": 32.0, "photo_reviews": true,
     "size_chart": true, "generic_listing": false, "discount_pct": 20,
     "repeated_complaints": false, "local_warehouse": false,
     "restricted_category": false, "chargeback_payment": true}
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Listing:
    free_return: bool = False
    choice: bool = False
    local_warehouse: bool = False
    store_age_months: float = 12.0
    rating: float = 4.5
    sales: int = 0
    photo_reviews: bool = False
    size_chart: bool = False
    chargeback_payment: bool = True
    price: float = 0.0
    discount_pct: float = 0.0
    generic_listing: bool = False
    repeated_complaints: bool = False
    restricted_category: bool = False


def score(x: Listing) -> tuple[int, list[tuple[str, int, str]]]:
    """Возвращает (итоговый балл, список факторов)."""
    f: list[tuple[str, int, str]] = []

    # --- защитные факторы ---
    if x.free_return:
        f.append(("Бейдж Free Returns", +30, "предоплаченная этикетка, возврат без причины 15 дней"))
    if x.choice:
        f.append(("Бейдж Choice", +15, "логистика платформы, проверяемая доставка"))
    if x.local_warehouse:
        f.append(("Локальный склад", +15, "возврат внутри страны, а не в Китай"))
    if x.store_age_months >= 36:
        f.append(("Магазин старше 3 лет", +10, "не однодневка"))
    elif x.store_age_months >= 12:
        f.append(("Магазин старше года", +5, "приемлемая история"))
    if x.rating >= 4.7:
        f.append((f"Рейтинг {x.rating}", +10, "высокая надёжность"))
    elif x.rating >= 4.5:
        f.append((f"Рейтинг {x.rating}", +4, "средне-высокий"))
    if x.sales >= 1000:
        f.append((f"Продаж {x.sales}", +8, "товар массово проверен"))
    elif x.sales >= 100:
        f.append((f"Продаж {x.sales}", +4, "есть выборка отзывов"))
    if x.photo_reviews:
        f.append(("Отзывы с фото", +8, "видно реальный товар"))
    if x.size_chart:
        f.append(("Размерная таблица/спека", +5, "лишает продавца аргумента в споре"))
    if x.chargeback_payment:
        f.append(("Оплата с чарджбэком", +5, "внешний рычаг эскалации"))

    # --- факторы риска ---
    if x.store_age_months < 6:
        f.append(("Магазин младше 6 мес.", -20, "риск исчезновения продавца"))
    if x.rating < 4.3:
        f.append((f"Рейтинг {x.rating}", -15, "системные жалобы"))
    if x.generic_listing:
        f.append(("Обезличенный листинг", -30, "признак hidden link: нечем доказать несоответствие"))
    if x.discount_pct > 60:
        f.append((f"Скидка {x.discount_pct:.0f}%", -15, "аномально низкая цена — маркер обмана"))
    if x.repeated_complaints:
        f.append(("Повторяющиеся жалобы", -15, "системный дефект товара"))
    if not x.size_chart:
        f.append(("Нет размерной таблицы", -10, "спор по размеру не выиграть"))
    if x.restricted_category:
        f.append(("Категория с ограничением пересылки", -10, "батареи/жидкости нельзя вернуть авиа"))
    if x.price > 100 and not x.free_return:
        f.append(("Дорого без Free Return", -20, "при споре потребуют отправку в Китай"))
    if not x.chargeback_payment:
        f.append(("Нет метода с чарджбэком", -15, "нет внешнего рычага"))

    return sum(w for _, w, _ in f), f


def verdict(total: int) -> tuple[str, str]:
    if total >= 50:
        return "НИЗКИЙ РИСК", "Покупать можно, защита возврата сильная."
    if total >= 20:
        return "ПРИЕМЛЕМО", "Покупать с дисциплиной: скриншот листинга, видео распаковки."
    if total >= 0:
        return "ПОВЫШЕННЫЙ РИСК", "Только на сумму, которую не жалко потерять."
    return "ВЫСОКИЙ РИСК", "Лучше найти другой листинг. Возврат, скорее всего, не сработает."


def report(x: Listing) -> str:
    total, factors = score(x)
    label, advice = verdict(total)
    out = ["=" * 74, "СКОРИНГ ЛИСТИНГА ALIEXPRESS — возвратопригодность", "=" * 74, ""]
    plus = [i for i in factors if i[1] > 0]
    minus = [i for i in factors if i[1] < 0]

    if plus:
        out.append("ЗАЩИТА:")
        for name, w, why in sorted(plus, key=lambda i: -i[1]):
            out.append(f"  +{w:<3} {name:<36} {why}")
        out.append("")
    if minus:
        out.append("РИСКИ:")
        for name, w, why in sorted(minus, key=lambda i: i[1]):
            out.append(f"  {w:<4} {name:<36} {why}")
        out.append("")

    out.append("-" * 74)
    out.append(f"ИТОГО: {total:+d}   →   {label}")
    out.append(f"{advice}")
    out.append("-" * 74)

    tips = []
    if not x.free_return:
        tips.append("Поискать аналог с бейджем Free Returns — это +30 к защите бесплатно.")
    if x.price > 50 and not (x.free_return or x.local_warehouse):
        tips.append("Дорогая позиция без локального возврата: при споре пересылка съест сумму.")
    if x.generic_listing:
        tips.append("Обезличенный листинг: описание не отражает товар, спор по SNAD почти невозможен.")
    if not x.photo_reviews:
        tips.append("Нет отзывов с фото — реальный вид товара неизвестен.")
    if tips:
        out.append("\nЧТО СДЕЛАТЬ:")
        out.extend(f"  • {t}" for t in tips)

    out.append("\nПеред оплатой: скриншот карточки (описание, бейджи, сроки). Листинг могут изменить.")
    return "\n".join(out)


def interactive() -> Listing:
    def ask_bool(q: str, default: bool = False) -> bool:
        d = "Y/n" if default else "y/N"
        v = input(f"{q} [{d}]: ").strip().lower()
        return default if not v else v in ("y", "yes", "д", "да", "1")

    def ask_num(q: str, default: float) -> float:
        v = input(f"{q} [{default}]: ").strip().replace(",", ".")
        try:
            return float(v) if v else default
        except ValueError:
            return default

    print("Оценка листинга (Enter — значение по умолчанию)\n")
    return Listing(
        free_return=ask_bool("Есть бейдж 'Free Returns'?"),
        choice=ask_bool("Есть бейдж 'Choice'?"),
        local_warehouse=ask_bool("Отправка с локального склада в твоей стране?"),
        store_age_months=ask_num("Возраст магазина, месяцев", 12),
        rating=ask_num("Рейтинг магазина", 4.5),
        sales=int(ask_num("Продаж у листинга", 100)),
        photo_reviews=ask_bool("Есть отзывы с фото покупателей?", True),
        size_chart=ask_bool("Есть размерная таблица / полная спецификация?", True),
        chargeback_payment=ask_bool("Оплата картой или PayPal (есть чарджбэк)?", True),
        price=ask_num("Цена", 20),
        discount_pct=ask_num("Заявленная скидка, %", 0),
        generic_listing=ask_bool("Листинг обезличенный (generic-фото, коды в вариантах)?"),
        repeated_complaints=ask_bool("В отзывах повторяется одна и та же претензия?"),
        restricted_category=ask_bool("Батареи / жидкости / аэрозоли?"),
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Скоринг возвратопригодности листинга AliExpress")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--json", type=Path, help="файл с параметрами листинга")
    p.add_argument("--free-return", action="store_true")
    p.add_argument("--choice", action="store_true")
    p.add_argument("--local-warehouse", action="store_true")
    p.add_argument("--store-age", type=float, default=12.0, help="возраст магазина в месяцах")
    p.add_argument("--rating", type=float, default=4.5)
    p.add_argument("--sales", type=int, default=0)
    p.add_argument("--photo-reviews", action="store_true")
    p.add_argument("--size-chart", action="store_true")
    p.add_argument("--no-chargeback", action="store_true")
    p.add_argument("--price", type=float, default=0.0)
    p.add_argument("--discount", type=float, default=0.0)
    p.add_argument("--generic", action="store_true")
    p.add_argument("--repeated-complaints", action="store_true")
    p.add_argument("--restricted", action="store_true")
    p.add_argument("--dump", action="store_true", help="вывести параметры как JSON")

    args = p.parse_args()

    if args.interactive:
        listing = interactive()
    elif args.json:
        listing = Listing(**json.loads(args.json.read_text(encoding="utf-8")))
    else:
        listing = Listing(
            free_return=args.free_return, choice=args.choice,
            local_warehouse=args.local_warehouse, store_age_months=args.store_age,
            rating=args.rating, sales=args.sales, photo_reviews=args.photo_reviews,
            size_chart=args.size_chart, chargeback_payment=not args.no_chargeback,
            price=args.price, discount_pct=args.discount, generic_listing=args.generic,
            repeated_complaints=args.repeated_complaints, restricted_category=args.restricted,
        )

    if args.dump:
        print(json.dumps(asdict(listing), ensure_ascii=False, indent=2))
        return

    print(report(listing))


if __name__ == "__main__":
    sys.exit(main())
