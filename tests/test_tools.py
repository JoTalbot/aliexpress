#!/usr/bin/env python3
"""
Регрессионные тесты инструментов проекта.

Зачем: над проектом работают разные агенты с разных машин. Тесты фиксируют
поведение, которое легко сломать неосторожной правкой — прежде всего расчёт
дедлайнов Buyer Protection (цена ошибки = потерянный возврат).

    python3 tests/test_tools.py          # прогон
    python3 tests/test_tools.py -v       # подробно

Только стандартная библиотека. Работают на временных файлах, боевые данные не трогают.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from order_ledger import Order, load, save  # noqa: E402
import order_ledger as ol  # noqa: E402
import listing_risk_score as lrs  # noqa: E402
import route_calc as rc  # noqa: E402
import remind  # noqa: E402
import import_orders as imp  # noqa: E402


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


class TestDeadlines(unittest.TestCase):
    """Самое критичное: пропущенный дедлайн = потерянный возврат.

    Значения окон захардкожены НАМЕРЕННО. Это внешние бизнес-правила
    AliExpress, а не наша конфигурация. Если тест сверяется с константой
    модуля, он тавтологичен и не поймает случайное изменение правила.
    Меняешь константу — сначала проверь первоисточник и обнови research/12.
    """

    def test_business_constants_unchanged(self):
        """Страховка от молчаливой правки окон защиты."""
        self.assertEqual(ol.AFTER_DELIVERY_DAYS, 15, "окно после подтверждения = 15 дней")
        self.assertEqual(ol.FREE_RETURN_DAYS, 15, "окно Free Return = 15 дней")
        self.assertEqual(ol.EARLY_DISPUTE_DAYS, 10, "спор открывается с ~10 дня")
        self.assertEqual(ol.BP_DAYS_DEFAULT, 60, "BP по умолчанию = 60 дней")

    def test_confirmed_receipt_starts_15_day_clock(self):
        o = Order(order_id="X", title="t", shipped=days_ago(40), delivered=days_ago(20),
                  confirmed=days_ago(10))
        self.assertEqual(o.days_left(), 5, "15 дней окна минус 10 прошедших")
        self.assertIn("подтверждения", o.deadline()[1])

    def test_confirming_receipt_shortens_window(self):
        """Подтверждение получения ОБМЕНИВАЕТ длинное окно на короткое."""
        base = dict(order_id="X", title="t", shipped=days_ago(30))
        before = Order(**base).days_left()
        after = Order(**base, delivered=days_ago(2), confirmed=days_ago(2)).days_left()
        self.assertGreater(before, after, "подтверждение должно сокращать окно")

    def test_free_return_window(self):
        o = Order(order_id="X", title="t", shipped=days_ago(30),
                  delivered=days_ago(5), free_return=True)
        self.assertEqual(o.days_left(), 10, "15 дней Free Return минус 5 прошедших")
        self.assertIn("Free Return", o.deadline()[1])

    def test_not_delivered_uses_bp_window(self):
        o = Order(order_id="X", title="t", shipped=days_ago(10), bp_days=60)
        self.assertEqual(o.days_left(), 65, "60 дней BP + 15 на спор − 10 прошедших")

    def test_no_ship_date_has_no_deadline(self):
        o = Order(order_id="X", title="t")
        self.assertIsNone(o.deadline()[0])
        self.assertIsNone(o.days_left())

    def test_dispute_opens_after_early_window(self):
        o = Order(order_id="X", title="t", shipped=days_ago(0))
        self.assertEqual(o.dispute_opens_at(), date.today() + timedelta(days=10))

    def test_urgency_levels(self):
        cases = [(-5, "ПРОСРОЧЕНО"), (2, "КРИТИЧНО"), (6, "СРОЧНО"), (30, "ок")]
        for left, expected in cases:
            with self.subTest(left=left):
                # confirmed = сегодня - (15 - left)
                o = Order(order_id="X", title="t", shipped=days_ago(60),
                          confirmed=days_ago(15 - left))
                self.assertEqual(o.urgency(), expected)

    def test_closed_order_has_no_urgency(self):
        o = Order(order_id="X", title="t", shipped=days_ago(60), status="closed")
        self.assertEqual(o.urgency(), "—")


class TestMoney(unittest.TestCase):

    def test_net_profit(self):
        o = Order(order_id="X", title="t", cost=10.0, ship_cost=2.0, sold_price=30.0)
        self.assertAlmostEqual(o.invested(), 12.0)
        self.assertAlmostEqual(o.net(), 18.0)

    def test_supplier_refund_improves_net(self):
        o = Order(order_id="X", title="t", cost=20.0, refund_amount=20.0)
        self.assertAlmostEqual(o.net(), 0.0)

    def test_capital_gap(self):
        """Разрыв оборотки: клиенту вернул, от поставщика ещё нет."""
        o = Order(order_id="X", title="t", cost=20.0, sold_price=50.0,
                  customer_refunded=50.0)
        self.assertAlmostEqual(o.capital_gap(), 50.0)
        o.refund_amount = 20.0
        self.assertAlmostEqual(o.capital_gap(), 30.0)

    def test_gap_never_negative(self):
        o = Order(order_id="X", title="t", refund_amount=100.0, customer_refunded=10.0)
        self.assertEqual(o.capital_gap(), 0.0)

    def test_pending_recovery_only_when_claimed(self):
        o = Order(order_id="X", title="t", cost=15.0, status="claimed", claim_asked=15.0)
        self.assertAlmostEqual(o.pending_recovery(), 15.0)
        o.status = "refunded"
        self.assertEqual(o.pending_recovery(), 0.0)


class TestFX(unittest.TestCase):
    """FX-учёт (T-049, research/17): потери на конвертации при возврате.

    Сценарий: заказ $10 (cost 10, ship 0), с гривневой карты списано 420 UAH
    (курс покупки 42.0). Возврат $10, но на карту пришло 405 UAH → потеря 15 UAH.
    """

    def _order(self, **kw):
        base = dict(order_id="FX-1", title="t", cost=10.0, ship_cost=0.0)
        base.update(kw)
        return Order(**base)

    def test_purchase_rate_from_statement_facts(self):
        o = self._order(card_charged=420.0)
        self.assertAlmostEqual(o.purchase_rate(), 42.0)

    def test_fx_loss_positive_when_refund_shrinks(self):
        o = self._order(card_charged=420.0, refund_amount=10.0, card_refunded=405.0)
        self.assertAlmostEqual(o.fx_loss(), 15.0)

    def test_fx_gain_is_negative_loss(self):
        o = self._order(card_charged=420.0, refund_amount=10.0, card_refunded=430.0)
        self.assertAlmostEqual(o.fx_loss(), -10.0)

    def test_usd_card_one_to_one_no_loss(self):
        # Эталон из research/17 §3.3: USD-карта + USD на сайте → возврат 1:1.
        o = self._order(card_currency="USD", card_charged=10.0,
                        refund_amount=10.0, card_refunded=10.0)
        self.assertAlmostEqual(o.fx_loss(), 0.0)

    def test_no_facts_no_fx(self):
        # Без пары фактов по выписке FX не считается (None, а не 0 или мусор).
        self.assertIsNone(self._order().fx_loss())
        self.assertIsNone(self._order(card_charged=420.0).fx_loss())
        self.assertIsNone(self._order(refund_amount=10.0, card_refunded=405.0).fx_loss())

    def test_zero_invested_no_rate(self):
        # Деление на ноль исключено по построению.
        o = Order(order_id="FX-0", title="t", cost=0.0, card_charged=420.0)
        self.assertIsNone(o.purchase_rate())

    def test_old_records_without_fx_fields_still_load(self):
        # Обратная совместимость: старый ledger.json без FX-полей читается.
        old = {"order_id": "OLD-1", "title": "t", "cost": 5.0}
        o = Order(**old)
        self.assertEqual(o.card_charged, 0.0)
        self.assertIsNone(o.fx_loss())


class TestPersistence(unittest.TestCase):

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "l.json"
            orders = [Order(order_id="A", title="Товар №1", cost=5.5, notes=["тест"]),
                      Order(order_id="B", title="Item 2", free_return=True)]
            save(db, orders)
            loaded = load(db)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].title, "Товар №1")
            self.assertTrue(loaded[1].free_return)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load(Path("/tmp/definitely_absent_xyz.json")), [])


class TestRiskScore(unittest.TestCase):

    def test_free_return_is_strongest_positive(self):
        base = lrs.Listing(price=30)
        with_fr = lrs.Listing(price=30, free_return=True)
        self.assertGreater(lrs.score(with_fr)[0], lrs.score(base)[0] + 25)

    def test_generic_listing_penalised(self):
        clean = lrs.Listing(price=30, size_chart=True)
        generic = lrs.Listing(price=30, size_chart=True, generic_listing=True)
        self.assertLess(lrs.score(generic)[0], lrs.score(clean)[0] - 25)

    def test_dirty_account_penalised(self):
        """Вывод T-011: репутация аккаунта реально влияет."""
        clean = lrs.Listing(price=30, account_clean=True)
        dirty = lrs.Listing(price=30, account_clean=False)
        self.assertLess(lrs.score(dirty)[0], lrs.score(clean)[0] - 30)

    def test_eu_multiple_lines_penalised(self):
        one = lrs.Listing(price=50, ships_from_eu=True, declaration_lines=1)
        many = lrs.Listing(price=50, ships_from_eu=True, declaration_lines=4)
        self.assertLess(lrs.score(many)[0], lrs.score(one)[0])

    def test_verdict_thresholds_ordered(self):
        labels = [lrs.verdict(v)[0] for v in (60, 30, 10, -50)]
        self.assertEqual(labels, ["НИЗКИЙ РИСК", "ПРИЕМЛЕМО",
                                  "ПОВЫШЕННЫЙ РИСК", "ВЫСОКИЙ РИСК"])


class TestRouteCalc(unittest.TestCase):

    def test_all_routes_present(self):
        res = rc.calc(50.0, 1.0, 1, 0.0)
        self.assertEqual({r.route for r in res},
                         {"ua-direct", "ua-local", "eu-forward", "dropship"})

    def test_ua_under_limit_no_duty(self):
        r = next(x for x in rc.calc(100.0, 1.0, 1, 0.0) if x.route == "ua-direct")
        self.assertEqual(r.duty, 0.0)
        self.assertEqual(r.vat, 0.0)

    def test_ua_over_limit_has_duty(self):
        r = next(x for x in rc.calc(300.0, 1.0, 1, 0.0) if x.route == "ua-direct")
        self.assertGreater(r.duty, 0.0)
        self.assertGreater(r.vat, 0.0)

    def test_eu_fee_scales_with_declaration_lines(self):
        """Регламент (EU) 2026/382: сбор на строку декларации, не на посылку."""
        one = next(x for x in rc.calc(40.0, 0.5, 1, 0.0) if x.route == "eu-forward")
        three = next(x for x in rc.calc(40.0, 0.5, 3, 0.0) if x.route == "eu-forward")
        self.assertAlmostEqual(three.duty - one.duty, rc.EU_FLAT_DUTY * 2, places=2)

    def test_handling_fee_increases_cost(self):
        without = next(x for x in rc.calc(40.0, 0.5, 2, 0.0, False) if x.route == "eu-forward")
        with_fee = next(x for x in rc.calc(40.0, 0.5, 2, 0.0, True) if x.route == "eu-forward")
        self.assertAlmostEqual(with_fee.duty - without.duty, rc.EU_HANDLING_FEE * 2, places=2)

    def test_overhead_measured_from_base_price(self):
        """Регрессия найденного бага: наценка считалась от цены маршрута."""
        r = next(x for x in rc.calc(100.0, 1.0, 1, 0.0) if x.route == "ua-local")
        self.assertGreater(r.overhead_pct, 5, "наценка локального склада должна быть видна")

    def test_ua_local_has_best_protection(self):
        res = rc.calc(50.0, 1.0, 1, 0.0)
        best = max(res, key=lambda r: r.protection)
        self.assertEqual(best.route, "ua-local")


class TestRemind(unittest.TestCase):

    def _db(self, orders):
        d = tempfile.mkdtemp()
        db = Path(d) / "l.json"
        save(db, orders)
        return db

    def test_detects_overdue(self):
        db = self._db([Order(order_id="OLD", title="t", shipped=days_ago(200),
                             confirmed=days_ago(100))])
        r = remind.collect(db, 7)
        self.assertEqual(len(r["overdue"]), 1)
        self.assertTrue(remind.has_alerts(r))

    def test_detects_stale_claim(self):
        db = self._db([Order(order_id="C", title="t", shipped=days_ago(50),
                             status="claimed", claim_opened=days_ago(45), claim_asked=10)])
        self.assertEqual(len(remind.collect(db, 7)["stale"]), 1)

    def test_quiet_when_nothing_urgent(self):
        db = self._db([Order(order_id="N", title="t", shipped=days_ago(1))])
        self.assertFalse(remind.has_alerts(remind.collect(db, 7)))

    def test_unconfirmed_delivery_listed(self):
        db = self._db([Order(order_id="U", title="t", shipped=days_ago(20),
                             delivered=days_ago(1))])
        self.assertEqual(len(remind.collect(db, 7)["unconfirmed"]), 1)

    def test_json_output_valid(self):
        db = self._db([Order(order_id="J", title="t", shipped=days_ago(70),
                             confirmed=days_ago(14))])
        json.loads(remind.as_json(remind.collect(db, 7)))


class TestImport(unittest.TestCase):

    def test_parse_money_formats(self):
        for raw, expected in [("12,40", 12.40), ("$18.90", 18.90), ("1 234,56", 1234.56),
                              ("", 0.0), ("—", 0.0), ("1.234.56", 1234.56)]:
            with self.subTest(raw=raw):
                self.assertAlmostEqual(imp.parse_money(raw), expected, places=2)

    def test_parse_date_formats(self):
        for raw in ["2026-08-05", "05.08.2026", "05/08/2026"]:
            with self.subTest(raw=raw):
                self.assertEqual(imp.parse_date(raw), "2026-08-05")

    def test_parse_date_rejects_garbage(self):
        self.assertIsNone(imp.parse_date("битая дата"))
        self.assertIsNone(imp.parse_date(""))

    def test_column_mapping_multilingual(self):
        m = imp.build_mapping(["Номер заказа", "Товар", "Цена", "Дата отправки"], {})
        self.assertEqual(m.get("order_id"), "Номер заказа")
        self.assertEqual(m.get("title"), "Товар")
        self.assertEqual(m.get("cost"), "Цена")
        self.assertEqual(m.get("shipped"), "Дата отправки")

    def test_column_mapping_english(self):
        m = imp.build_mapping(["Order ID", "Product Name", "Price"], {})
        self.assertEqual(m.get("order_id"), "Order ID")
        self.assertEqual(m.get("title"), "Product Name")


class TestScopeGuard(unittest.TestCase):
    """Границы проекта — часть спецификации, а не пожелание (ADR-002)."""

    def test_scope_document_exists(self):
        self.assertTrue((ROOT / "docs" / "SCOPE_AND_ETHICS.md").exists())

    def test_agents_md_references_scope(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("SCOPE_AND_ETHICS", text)

    def test_no_plaintext_secrets_committed(self):
        for pattern in ("ghp_", "github_pat_"):
            for f in ROOT.rglob("*.md"):
                if ".git" in f.parts:
                    continue
                content = f.read_text(encoding="utf-8", errors="ignore")
                # допускаем упоминание в маскированном виде
                for line in content.splitlines():
                    if pattern in line and "***" not in line and "REDACTED" not in line:
                        self.assertNotRegex(line, rf"{pattern}[A-Za-z0-9]{{20,}}",
                                            f"возможный секрет в {f}")


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
