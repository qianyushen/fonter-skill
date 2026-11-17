"""缺依赖时给一条能照抄的安装命令，而不是甩一段 traceback。

用法：把 `import _bootstrap  # noqa: F401` 放在脚本的第三方 import 之前。
"""
from __future__ import annotations

import importlib.util
import sys

REQUIRED = [("numpy", "numpy"), ("scipy", "scipy"), ("PIL", "pillow"),
            ("fontTools", "fonttools"), ("potrace", "potracer")]

missing = [(mod, pkg) for mod, pkg in REQUIRED if importlib.util.find_spec(mod) is None]

if missing:
    pkgs = " ".join(pkg for _mod, pkg in missing)
    sys.stderr.write(
        "\n[fonter] 缺依赖: " + ", ".join(f"{mod}（pip 名 {pkg}）" for mod, pkg in missing) + "\n"
        "\n一条命令装好（用你现在这个 python3）：\n"
        f"    python3 -m pip install {pkgs}\n"
        "\n或者跑 skill 自带的安装脚本：\n"
        "    bash <skill目录>/scripts/setup.sh\n"
        "    python3 <skill目录>/scripts/check_env.py   # 装完自查\n\n"
    )
    sys.exit(2)
