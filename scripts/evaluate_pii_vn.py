"""Đánh giá deterministic 500 mẫu tổng hợp cho recognizer PII tiếng Việt."""

from __future__ import annotations

import json
import sys

from ben_pii_vn.evaluation import evaluate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["raw_pii_after_redact"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
