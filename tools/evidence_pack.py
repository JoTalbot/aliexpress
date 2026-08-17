#!/usr/bin/env python3
"""
Evidence Pack — подготовка пакета доказательств для спора по реальной проблеме.

Берёт заказ из ledger (или причину напрямую) и генерирует:
  1. Чек-лист доказательств под конкретную причину спора.
  2. Структуру папок для файлов (data/evidence/<ID>/ — в .gitignore).
  3. Ссылку на подходящий шаблон обращения из docs/TEMPLATES_EN.md.
  4. Проверку дедлайна из ledger — есть ли ещё время собирать.

Границы (docs/SCOPE_AND_ETHICS.md): инструмент для РЕАЛЬНЫХ проблем с заказом.
Он помогает не потерять честный спор из-за слабых доказательств,
а не «выиграть» спор по выдуманной причине.

    python3 evidence_pack.py --id AE-1001                  # причина из заявки в ledger
    python3 evidence_pack.py --id AE-1001 --reason damaged # причина явно
    python3 evidence_pack.py --reason wrong-item           # без ledger
    python3 evidence_pack.py --id AE-1001 --make-dirs      # создать папки под файлы
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from order_ledger import DB_DEFAULT, REASONS, load  # noqa: E402

EVIDENCE_ROOT = Path(__file__).resolve().parent.parent / "data" / "evidence"
TEMPLATES = Path(__file__).resolve().parent.parent / "docs" / "TEMPLATES_EN.md"

# Общие доказательства — нужны почти всегда (research/02, docs/UNBOXING_CHECKLIST.md)
COMMON = [
    "Фото транспортной этикетки (трек-номер читается)",
    "Скриншот страницы заказа: цена, продавец, дата, трек",
    "Скриншот листинга НА МОМЕНТ ПОКУПКИ (описание могут отредактировать)",
    "Скриншоты переписки с продавцом (если была)",
]

# Причина → (доп. доказательства, № шаблона в docs/TEMPLATES_EN.md, папки)
PACKS: dict[str, tuple[list[str], int, list[str]]] = {
    "not-received": (
        ["Скриншот трекинга: последний статус + сколько дней нет движения",
         "Скриншот 'доставлено', если трек врёт (домофон/камера/соседи — что есть)",
         "Справка почты о невручении, если реально получали (Nova Poshta/Укрпошта)"],
        1, ["01-label", "02-tracking", "04-chat"]),
    "wrong-item": (
        ["Видео распаковки ОДНИМ ДУБЛЕМ: с этикетки до содержимого",
         "Фото пришедшего товара рядом со скриншотом листинга",
         "Фото маркировки/модели на самом товаре (не на коробке)"],
        2, ["01-label", "02-unboxing", "03-item", "05-listing", "04-chat"]),
    "damaged": (
        ["Видео распаковки ОДНИМ ДУБЛЕМ: с этикетки до обнаружения повреждения",
         "Фото повреждений упаковки СНАРУЖИ до вскрытия (вмятины, следы удара)",
         "Фото повреждений товара крупно, при дневном свете, с разных ракурсов"],
        3, ["01-label", "02-unboxing", "03-damage", "04-chat"]),
    "not-working": (
        ["Видео дефекта: включение → симптом, без склеек",
         "Видео/фото подключения по инструкции (исключить 'неправильно использовал')",
         "Серийный номер / маркировка устройства в кадре"],
        5, ["01-label", "02-unboxing", "03-defect", "04-chat"]),
    "shortage": (
        ["Видео распаковки ОДНИМ ДУБЛЕМ — единственное сильное доказательство недостачи",
         "Фото веса на этикетке (заявленный вес vs фактическое содержимое)",
         "Фото всего содержимого, разложенного в один кадр, рядом с упаковкой"],
        4, ["01-label", "02-unboxing", "03-contents", "04-chat"]),
    "not-as-desc": (
        ["Фото товара рядом со скриншотом конкретного пункта описания, которому он не соответствует",
         "Замеры линейкой/весами в кадре, если расхождение в размере/весе/материале",
         "Видео, если расхождение функциональное"],
        2, ["01-label", "02-unboxing", "03-item", "05-listing", "04-chat"]),
    "free-return": (
        ["Скриншот бейджа Free Return на листинге (доказательство права на возврат)",
         "Фото товара в исходном состоянии: не использован, упаковка цела",
         "Скриншот проблемы с этикеткой, если её не выдают (для шаблона 8)"],
        8, ["01-label", "03-item", "05-listing", "04-chat"]),
}

SCOPE_NOTE = ("Пакет — для реальной проблемы с заказом. Ложные заявления = потеря "
              "аккаунта и хуже (research/06, docs/SCOPE_AND_ETHICS.md).")


def build_report(reason: str, order=None, today: date | None = None) -> str:
    """Текстовый план сбора доказательств. Чистая функция — тестируется без I/O."""
    extra, template_no, dirs = PACKS[reason]
    lines = ["=" * 62,
             f"ПАКЕТ ДОКАЗАТЕЛЬСТВ: {REASONS[reason]}",
             "=" * 62]

    if order is not None:
        left = order.days_left(today)
        dl, why = order.deadline()
        lines += [f"Заказ: {order.order_id} — {order.title}",
                  f"Дедлайн спора: {dl} ({why})"]
        if left is not None:
            if left < 0:
                lines.append(f"⛔ ОКНО ЗАКРЫТО {-left} дн. назад — спор, скорее всего, невозможен.")
            elif left <= 3:
                lines.append(f"⚠ ОСТАЛОСЬ {left} дн. — собирай минимум и открывай спор СЕГОДНЯ.")
            else:
                lines.append(f"Осталось дней: {left}")
        lines.append("")

    lines.append("— Базовый набор (нужен всегда):")
    lines += [f"  [ ] {item}" for item in COMMON]
    lines.append(f"\n— Специфично для «{REASONS[reason]}»:")
    lines += [f"  [ ] {item}" for item in extra]
    lines += ["",
              f"Текст обращения: docs/TEMPLATES_EN.md, шаблон №{template_no}",
              "Печатный чек-лист распаковки: docs/UNBOXING_CHECKLIST.md",
              "",
              f"Папки под файлы: {', '.join(dirs)}",
              "",
              f"ℹ {SCOPE_NOTE}"]
    return "\n".join(lines)


def make_dirs(order_id: str, reason: str, root: Path = EVIDENCE_ROOT) -> Path:
    """Создаёт структуру папок и кладёт план в README.txt."""
    _, _, dirs = PACKS[reason]
    base = root / order_id
    for name in dirs:
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def main() -> None:
    p = argparse.ArgumentParser(description="Пакет доказательств для спора (реальные проблемы)")
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--id", help="ID заказа из ledger")
    p.add_argument("--reason", choices=list(PACKS),
                   help="причина; если не задана — берётся из заявки в ledger")
    p.add_argument("--make-dirs", action="store_true", help="создать папки в data/evidence/<ID>/")
    args = p.parse_args()

    order = None
    reason = args.reason
    if args.id:
        orders = load(args.db)
        matches = [o for o in orders if o.order_id == args.id]
        if not matches:
            raise SystemExit(f"Заказ {args.id} не найден в {args.db}")
        order = matches[0]
        if reason is None:
            reason = order.claim_reason or None
    if reason is None:
        raise SystemExit("Укажи --reason (или открой заявку в ledger: claim --reason ...)")

    report = build_report(reason, order)
    print(report)

    if args.make_dirs:
        oid = args.id or f"manual-{date.today().isoformat()}"
        base = make_dirs(oid, reason)
        (base / "README.txt").write_text(report, encoding="utf-8")
        print(f"\n✓ Папки созданы: {base}")
        print("  Файлы клади по папкам, README.txt — план. Каталог в .gitignore.")


if __name__ == "__main__":
    main()
