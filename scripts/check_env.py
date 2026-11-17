#!/usr/bin/env python3
"""check_env.py — 一条命令确认这套 skill 能不能在当前机器跑起来。

  python3 check_env.py

只看「跑脚本」需要的：Python 版本 + numpy / scipy / pillow / fonttools / potracer，
以及可选的 codex CLI（只有「生成单词图」那一步需要模型；没有它也能吃现成图片）。
不依赖 Pi、不需要任何 PI_* 环境变量。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import os
from pathlib import Path

OK, BAD, WARN = "✓", "✗", "!"


def main():
    print("=" * 62)
    print("fonter 环境自检")
    print("=" * 62)
    print(f"  {OK} python      {sys.version.split()[0]}  ({sys.executable})")

    ok = True
    mods = [("numpy", "numpy"), ("scipy", "scipy"), ("PIL", "pillow"),
            ("fontTools", "fonttools"), ("potrace", "potracer")]
    for mod, pkg in mods:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "")
            if mod == "PIL":
                ver = getattr(m, "version", "") or ver
            print(f"  {OK} {mod:<11} {ver}")
        except Exception as e:
            ok = False
            print(f"  {BAD} {mod:<11} 缺（{e}）→ pip install {pkg}")

    codex = shutil.which("codex")
    if codex:
        try:
            v = subprocess.run([codex, "--version"], capture_output=True, text=True).stdout.strip()
        except Exception:
            v = "?"
        print(f"  {OK} codex       {v}  ({codex})")
    else:
        print(f"  {WARN} codex       没装 —— 只有「用模型生成单词图」那一步需要它；"
              f"吃现成图片跑脚本没问题")

    home = Path.home()
    skill = home / ".codex" / "skills" / "fonter"
    here = Path(__file__).resolve().parent.parent
    print(f"  {OK} skill 目录   {skill if skill.exists() else here}"
          f"{'（符号链接）' if skill.is_symlink() else ''}")
    scripts = ["segment_word.py", "build_font.py", "build_family.py",
               "make_specimen.py", "render_material.py", "font_doctor.py", "check_env.py"]
    missing = [s for s in scripts if not (here / "scripts" / s).exists()]
    print(f"  {OK if not missing else BAD} 脚本齐全     "
          f"{len(scripts) - len(missing)}/{len(scripts)}" + (f"  缺 {missing}" if missing else ""))

    fonts = len(list(Path("/System/Library/Fonts").glob("*.ttf"))) + \
        len(list(Path("/Library/Fonts").glob("*.*")))
    print(f"  {OK} 系统字体     {fonts} 个文件（预览海报的小字说明用 Helvetica）")

    print("-" * 62)
    if ok and not missing:
        print("  结论: 可以直接跑（生成字体不需要 Pi，也不需要联网）")
        print("        需要模型出图（单词图 / 材质渲染图）时才用 codex image_gen")
        return 0
    print("  结论: 缺依赖，先 pip install -r 下面这些包再跑")
    print("        pip install numpy scipy pillow fonttools potracer")
    return 1


if __name__ == "__main__":
    sys.exit(main())
