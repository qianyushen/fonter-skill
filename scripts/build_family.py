#!/usr/bin/env python3
"""build_family.py — 一次出 TTF + OTF 两份，并各跑一遍 Adobe 体检。

用法:
  python3 build_family.py --sources 02_letters/VAMPIRE 02_letters/JOCKEYS ... \
      --family WokeLiquid --out-dir 04_font [--charset A-Z,0-9] [--gap 120] [--cap 700]

为什么两份都要：
  * TTF（glyf / 二次曲线）：系统、Office、网页、Android 通用，装哪都能用。
  * OTF（CFF / 三次曲线）：Adobe 原生格式，字形更准（不经 Cu2Qu 近似），
    TTF 在某些 PS 版本上出问题时就靠它兜底。
  * **同一家族只能同时装一种**，两个都装 PS 会判重名「不可用」——交付时把两种都给用户，
    让用户挑一种装（`fix-ps-font.command` 会自动删掉另一种）。

产物：<out-dir>/<Family>.ttf、<out-dir>/<Family>.otf、<out-dir>/build_final.txt、
      <out-dir>/metrics.json（以 OTF 那次为准，字距/字高数据两者一致）
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", required=True)
    ap.add_argument("--family", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--charset", default="A-Z,0-9")
    ap.add_argument("--gap", type=int, default=None)
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--style-name", default="Regular")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "build_final.txt"
    lines, ok = [], True

    for ext in ("ttf", "otf"):
        cmd = [sys.executable, str(HERE / "build_font.py"), "--sources", *args.sources,
               "--family", args.family, "--style-name", args.style_name,
               "--out", str(out_dir / f"{args.family}.{ext}"), "--charset", args.charset]
        if args.gap:
            cmd += ["--gap", str(args.gap)]
        if args.cap:
            cmd += ["--cap", str(args.cap)]
        rc, out = run(cmd)
        lines.append(f"$ build_font.py {ext}\n{out.strip()}\n")
        if rc != 0:
            ok = False
            lines.append(f"!! {ext} 构建失败（exit {rc}）\n")

        drc, dout = run([sys.executable, str(HERE / "font_doctor.py"),
                         str(out_dir / f"{args.family}.{ext}")])
        lines.append(f"$ font_doctor.py {ext}\n{dout.strip()}\n")
        if drc != 0:
            ok = False

    log.write_text("\n".join(lines))
    print("\n".join(lines))

    # 汇总
    files = []
    for ext in ("ttf", "otf"):
        f = out_dir / f"{args.family}.{ext}"
        files.append(f"{f.name} {f.stat().st_size / 1024:.1f} KB" if f.exists() else f"{f.name} 缺失")
    met = out_dir / "metrics.json"
    verdict = json.loads(met.read_text()).get("verdict") if met.exists() else "无"
    print("=" * 60)
    print(f"{args.family}: " + " | ".join(files))
    print(f"metrics 判定: {verdict}")
    print("结论: " + ("两种格式都做好，且都能在 Adobe 里用" if ok else "有问题，看上面的日志"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
