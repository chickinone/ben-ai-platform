"""Tạo file .env từ .env.example, thay placeholder bằng giá trị ngẫu nhiên.

Dùng:  python scripts/init_env.py [--force]
"""

from __future__ import annotations

import re
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALNUM = string.ascii_letters + string.digits


def render(template: str) -> str:
    text = re.sub(r"__HEX(\d+)__", lambda m: secrets.token_hex(int(m.group(1)) // 2), template)
    return re.sub(
        r"__ALNUM(\d+)__",
        lambda m: "".join(secrets.choice(ALNUM) for _ in range(int(m.group(1)))),
        text,
    )


def main(argv: list[str]) -> int:
    source = ROOT / ".env.example"
    target = ROOT / ".env"
    if target.exists() and "--force" not in argv:
        print(f"{target} đã tồn tại — giữ nguyên. Dùng --force để tạo lại (mất mật khẩu cũ).")
        return 0
    target.write_text(render(source.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    print(f"Đã tạo {target}. Không commit file này.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
