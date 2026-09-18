"""Đánh giá deterministic 500 mẫu tổng hợp cho recognizer PII tiếng Việt."""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass

from ben_pii_vn import Redactor, detect_pii

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class Case:
    text: str
    kind: str | None
    value: str | None


def cases() -> list[Case]:
    items: list[Case] = []
    for index in range(80):
        phone = f"09{index:08d}"
        cccd = f"001{index:09d}"
        bank = str(10_000_000 + index)
        email = f"khach{index}@example.com"
        items.extend(
            [
                Case(f"Liên hệ {phone}", "PHONE", phone),
                Case(f"CCCD {cccd}", "CCCD", cccd),
                Case(f"STK: {bank}", "BANK", bank),
                Case(f"Email {email}", "EMAIL", email),
            ]
        )
    surnames = ["Nguyễn Văn An", "Trần Thị Bình", "Lê Minh Châu", "Phạm Gia Hân"]
    for index in range(40):
        order = f"#A{1000 + index}"
        name = surnames[index % len(surnames)]
        items.extend(
            [
                Case(f"Đơn {order} cần kiểm tra", "ORDER", order),
                Case(f"Khách hàng: {name}", "NAME", name),
            ]
        )
    for index in range(100):
        items.append(Case(f"Mã sản phẩm SP-{1000 + index}, giá {index + 1}000 đồng", None, None))
    assert len(items) == 500
    return items


def evaluate() -> dict:
    totals: Counter[str] = Counter()
    true_positive: Counter[str] = Counter()
    false_positive: Counter[str] = Counter()
    false_negative: Counter[str] = Counter()
    leakage: list[dict[str, str]] = []

    for case in cases():
        detected = {(entity.kind, entity.value) for entity in detect_pii(case.text)}
        if case.kind is None:
            for kind, _ in detected:
                false_positive[kind] += 1
            continue
        totals[case.kind] += 1
        expected = (case.kind, case.value)
        if expected in detected:
            true_positive[case.kind] += 1
        else:
            false_negative[case.kind] += 1
        false_positive.update(kind for kind, value in detected if (kind, value) != expected)
        redacted = Redactor().redact_text(case.text)
        if case.value and case.value in redacted:
            leakage.append({"kind": case.kind, "value": case.value})

    kinds = sorted(set(totals) | set(false_positive))
    metrics = {}
    for kind in kinds:
        tp, fp, fn = true_positive[kind], false_positive[kind], false_negative[kind]
        metrics[kind] = {
            "samples": totals[kind],
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        }
    return {"samples": 500, "metrics": metrics, "raw_pii_after_redact": leakage}


def main() -> int:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["raw_pii_after_redact"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
