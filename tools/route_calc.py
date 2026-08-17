#!/usr/bin/env python3
"""
Калькулятор итоговой стоимости (landed cost) по маршрутам доставки.

Считает, во что реально обойдётся заказ с учётом пошлин, НДС и пересылки,
и сопоставляет это с качеством защиты возврата.

Актуально на 2026-08-17. Правила меняются — см. research/12-verification-log.md.

    python3 tools/route_calc.py --price 80 --weight 1.2
    python3 tools/route_calc.py --price 40 --weight 0.5 --items 3
    python3 tools/route_calc.py --price 200 --weight 3 --currency EUR --format json

`--items` — число РАЗНЫХ товарных подпозиций (tariff subheadings), а не штук.
Пять одинаковых футболок = 1 подпозиция. Футболка + кабель = 2 подпозиции.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

# --- курсы по умолчанию (обновлять вручную) --------------------------------
RATES = {"EUR": 1.0, "USD": 0.92, "PLN": 0.235, "UAH": 0.022}

# --- налоговые параметры, актуально на 2026-08-17 --------------------------
UA_DUTY_FREE = 150.0      # €, лимит для Украины (законопроект №15460 может отменить с 2027)
UA_DUTY = 0.10            # 10% пошлина на превышение
UA_VAT = 0.20             # 20% НДС на превышение
EU_FLAT_DUTY = 3.0        # €, Регламент (EU) 2026/382, с 01.07.2026 до 01.07.2028
EU_DUTY_THRESHOLD = 150.0 # € — сбор применяется к B2C-посылкам ниже этого порога
EU_VAT_PL = 0.23          # НДС Польши (типовая точка входа для форвардинга)
EU_C2C_FREE = 45.0        # €, порог для частных отправлений без коммерческой цели


def to_eur(amount: float, currency: str) -> float:
    return amount * RATES[currency]


@dataclass
class Result:
    route: str
    label: str
    base: float = 0.0            # исходная цена товара, для сравнения маршрутов
    goods: float = 0.0           # цена по этому маршруту (может отличаться)
    shipping: float = 0.0
    duty: float = 0.0
    vat: float = 0.0
    forwarding: float = 0.0
    protection: int = 0          # 0..100, качество защиты возврата
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.goods + self.shipping + self.duty + self.vat + self.forwarding

    @property
    def overhead(self) -> float:
        """Всё сверх базовой цены товара: наценка маршрута, налоги, пересылка."""
        return self.total - self.base

    @property
    def overhead_pct(self) -> float:
        return (self.overhead / self.base * 100) if self.base else 0.0


def ua_customs(value: float) -> tuple[float, float, list[str]]:
    """Украинская таможня: пошлина и НДС на превышение лимита."""
    if value <= UA_DUTY_FREE:
        return 0.0, 0.0, [f"до €{UA_DUTY_FREE:.0f} без пошлины и НДС"]
    excess = value - UA_DUTY_FREE
    duty = excess * UA_DUTY
    vat = (excess + duty) * UA_VAT
    return duty, vat, [f"превышение €{excess:.2f}: пошлина 10% + НДС 20%"]


def fwd_cost_eur(weight: float) -> float:
    """Пересылка Польша → Украина, ориентир по тарифам Nova Post / Meest (PLN)."""
    if weight <= 1:
        pln = 29.0
    elif weight <= 2:
        pln = 44.0
    elif weight <= 5:
        pln = 54.0
    elif weight <= 10:
        pln = 64.0
    elif weight <= 15:
        pln = 79.0
    else:
        pln = 89.0 + max(0.0, weight - 20) * 5
    return pln * RATES["PLN"]


def calc(price_eur: float, weight: float, items: int, ship_eur: float) -> list[Result]:
    out: list[Result] = []

    # --- 1. UA-direct -----------------------------------------------------
    r = Result("ua-direct", "Прямо в Украину (Nova Poshta Global / Укрпошта / Meest)")
    r.base = price_eur
    r.goods, r.shipping = price_eur, ship_eur
    r.duty, r.vat, notes = ua_customs(price_eur + ship_eur)
    r.notes += notes
    r.protection = 55
    r.notes.append("спор работает; физический возврат в Китай нерентабелен → Refund only")
    if price_eur > UA_DUTY_FREE:
        r.warnings.append("выше лимита — рассмотри дробление на отдельные заказы")
    r.warnings.append("законопроект №15460: с ~2027 НДС 20% может применяться к любой сумме")
    out.append(r)

    # --- 2. UA-local ------------------------------------------------------
    r = Result("ua-local", "Локальный склад в Украине")
    r.base = price_eur
    r.goods, r.shipping = price_eur * 1.12, ship_eur * 0.4
    r.notes.append(f"цена выше на ~12% (+€{r.goods - price_eur:.2f}), таможня уже пройдена")
    r.notes.append("возврат по локальному адресу реально исполним")
    r.protection = 90
    out.append(r)

    # --- 3. EU-forward ----------------------------------------------------
    r = Result("eu-forward", "Адрес в ЕС (Польша) + пересылка форвардером")
    r.base = price_eur
    r.goods, r.shipping = price_eur, ship_eur
    base = price_eur + ship_eur

    if base < EU_DUTY_THRESHOLD:
        r.duty = EU_FLAT_DUTY * max(1, items)
        r.notes.append(f"Регламент (EU) 2026/382: €{EU_FLAT_DUTY:.0f} × {max(1, items)} подпозиц.")
        if items > 1:
            r.warnings.append(f"{items} разных подпозиций → сбор умножается "
                              f"(€{r.duty:.0f} вместо €{EU_FLAT_DUTY:.0f})")
    else:
        r.duty = base * 0.04
        r.notes.append("выше €150 — обычные ставки пошлины (ориентир ~4%, зависит от кода)")

    r.vat = (base + r.duty) * EU_VAT_PL
    r.notes.append(f"НДС Польши {EU_VAT_PL * 100:.0f}%")

    fwd = fwd_cost_eur(weight)
    r.forwarding = fwd
    r.notes.append(f"пересылка PL→UA ≈ €{fwd:.2f} за {weight} кг")

    ua_d, ua_v, ua_notes = ua_customs(price_eur)
    r.duty += ua_d
    r.vat += ua_v
    if ua_d or ua_v:
        r.warnings.append("вторая таможня на въезде в Украину — платишь дважды")

    r.protection = 75
    r.notes.append("на плече Китай→ЕС доступны Free Return и право ЕС (отказ 14 дней)")
    r.warnings.append("окно Buyer Protection тикает, пока посылка ждёт консолидации")
    r.warnings.append("при повреждении не доказать, на каком плече это произошло")
    out.append(r)

    # --- 4. Dropship ------------------------------------------------------
    r = Result("dropship", "Прямая отправка конечному покупателю")
    r.base = price_eur
    r.goods, r.shipping = price_eur, ship_eur
    r.duty, r.vat, notes = ua_customs(price_eur + ship_eur)
    r.notes += notes
    r.notes.append("нет издержек на промежуточное хранение и пересылку")
    r.protection = 30
    r.warnings.append("товар в руках не держишь — нет видео распаковки")
    r.warnings.append("клиент может сообщить о проблеме после истечения окна спора")
    out.append(r)

    return out


def bar(v: int, width: int = 10) -> str:
    filled = round(v / 100 * width)
    return "█" * filled + "░" * (width - filled)


def render(results: list[Result], cur: str, price: float, weight: float, items: int) -> str:
    k = RATES[cur]
    o = [
        "=" * 72,
        f"LANDED COST ПО МАРШРУТАМ · товар {price:.2f} {cur} · {weight} кг · "
        f"{items} подпозиц.",
        "=" * 72, "",
    ]
    best = min(results, key=lambda r: r.total)
    safest = max(results, key=lambda r: r.protection)

    for r in sorted(results, key=lambda x: x.total):
        mark = []
        if r is best:
            mark.append("ДЕШЕВЛЕ ВСЕГО")
        if r is safest:
            mark.append("ЛУЧШАЯ ЗАЩИТА")
        tag = ("  ← " + " · ".join(mark)) if mark else ""
        o.append(f"▸ {r.label}{tag}")
        o.append(f"   товар {r.goods / k:>8.2f}   доставка {r.shipping / k:>7.2f}   "
                 f"пошлина {r.duty / k:>6.2f}   НДС {r.vat / k:>7.2f}   "
                 f"пересылка {r.forwarding / k:>6.2f}")
        o.append(f"   ИТОГО {r.total / k:>8.2f} {cur}   "
                 f"(наценка +{r.overhead / k:.2f}, {r.overhead_pct:.0f}%)   "
                 f"защита {bar(r.protection)} {r.protection}%")
        for n in r.notes:
            o.append(f"     · {n}")
        for w in r.warnings:
            o.append(f"     ⚠ {w}")
        o.append("")

    o.append("-" * 72)
    diff = (safest.total - best.total) / k
    o.append(f"Разница между самым дешёвым и самым защищённым: {diff:+.2f} {cur}")
    if diff > 0:
        o.append(f"Это цена спокойствия. При товаре дороже {price:.0f} {cur} "
                 f"обычно окупается.")
    o.append("")
    o.append("Правила: ЕС — Регламент (EU) 2026/382, €3/подпозиция, 01.07.2026–01.07.2028.")
    o.append("Украина — лимит €150 действует; законопроект №15460 может отменить с 2027.")
    o.append("Цифры ориентировочные. Проверяй тариф форвардера и курс перед покупкой.")
    return "\n".join(o)


def main() -> None:
    p = argparse.ArgumentParser(description="Калькулятор landed cost по маршрутам")
    p.add_argument("--price", type=float, required=True, help="цена товара")
    p.add_argument("--weight", type=float, default=0.5, help="вес, кг")
    p.add_argument("--items", type=int, default=1,
                   help="число РАЗНЫХ товарных подпозиций (не штук)")
    p.add_argument("--shipping", type=float, default=0.0, help="доставка от продавца")
    p.add_argument("--currency", choices=list(RATES), default="EUR")
    p.add_argument("--format", choices=["text", "json"], default="text")
    a = p.parse_args()

    price_eur = to_eur(a.price, a.currency)
    ship_eur = to_eur(a.shipping, a.currency)
    res = calc(price_eur, a.weight, a.items, ship_eur)

    if a.format == "json":
        k = RATES[a.currency]
        print(json.dumps({
            "input": {"price": a.price, "currency": a.currency,
                      "weight": a.weight, "items": a.items},
            "routes": [{
                "route": r.route, "label": r.label,
                "base": round(r.base / k, 2), "goods": round(r.goods / k, 2),
                "shipping": round(r.shipping / k, 2),
                "duty": round(r.duty / k, 2), "vat": round(r.vat / k, 2),
                "forwarding": round(r.forwarding / k, 2),
                "total": round(r.total / k, 2),
                "overhead_pct": round(r.overhead_pct, 1),
                "protection": r.protection,
                "notes": r.notes, "warnings": r.warnings,
            } for r in sorted(res, key=lambda x: x.total)],
        }, ensure_ascii=False, indent=2))
    else:
        print(render(res, a.currency, a.price, a.weight, a.items))


if __name__ == "__main__":
    main()
