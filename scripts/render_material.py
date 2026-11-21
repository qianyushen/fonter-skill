#!/usr/bin/env python3
"""render_material.py — 把「普通配色预览海报」渲染成一张真实材质版（图生图 / codex image_gen）。

用途：`05_preview/specimen.png` 是脚本用成品 TTF 渲的**字形真值**；
本脚本拿它当唯一版式与字形依据，只换「表面 + 媒介」（草坪+喷漆、砖墙+喷漆、
黑亚克力+水银、红宝石+刻痕…），走 codex 内置的 `image_gen`。

**材质组合不由脚本内置**：用户指名了材质就照用户的来；没指名就由 agent（codex）随机
想出一组搭配，用 --material 传进来。脚本只负责拼提示词、调模型、校验、归档。

用法：
  python3 scripts/render_material.py --project projects/polymer \
      --material "老旧红砖墙 + 街头喷漆" --material "磨砂玻璃 + 喷砂"
  python3 scripts/render_material.py --project projects/polymer --material "草坪 + 喷漆" --dry-run
  python3 scripts/render_material.py --ref 05_preview/specimen.png --material "..." --out-dir 06_art

产物（默认项目下 06_art/）：
  06_art/<Family>_<slug>.png          材质渲染图
  06_art/<Family>_<slug>.prompt.txt   使用的提示词（抄进 build_log.md）
  06_art/<Family>_<slug>.cli.jsonl    codex 事件流（排查用）
  06_art/materials.json              本次的材质、尺寸、校验结论
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_PROXY = "http://127.0.0.1:7890"


def slugify(text: str) -> str:
    """材质描述 → 稳定文件名片段（中文按字面保留，去掉标点/空白）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text, flags=re.UNICODE).strip("_")
    return (s or "material")[:40]


def build_prompt(material: str, word: str, sentence: str, grid: str,
                 ref_path: Path, out_path: Path) -> str:
    return (
        "用你自己内置的 image_gen 工具做**图生图**（把参考图作为图像输入，input_fidelity 拉满），"
        "把参考图这张字体预览海报换成真实材质。\n\n"
        f"参考图：{ref_path}\n"
        "它是脚本用成品字体渲出来的海报，是**版式与字形的唯一依据**。\n"
        f"本次只换材质：{material}\n"
        "材质与光照细节你自己补足，必须具体到「漆的雾化颗粒/流挂滴落、金属镜面高光、"
        "刻痕翻边毛刺、布料纤维与针脚、沙粒塌陷与积水反光」这一层，不要简化成平涂或滤镜。"
        "要像真实拍摄的照片，不要 3D/CG 感。\n\n"
        "硬性要求（一条都不许破）：\n"
        "- 版式 1:1 照搬参考图：上方两个词两行（同一位置、同一相对大小）、下方一句标语、\n"
        "  中间通栏分割线、下半部分字符网格的行数与每行字数完全一致。\n"
        "- 字母形状与参考图**逐字一致**：不许换字体、不许改倾斜角、不许改笔画粗细节奏、"
        "不许美化或重画任何字母。\n"
        f"- 拼写不能错：两个词是 {word}，标语是 {sentence}，网格是 {grid}，一个字都不能多、不能少、不能换。\n"
        "- 保留原有明暗关系：字（连同它的材质）是主角，底色/背景是材质表面，"
        "字与底的对比强度与参考图一致。\n"
        "- 只改材质与光照。不要加 logo、水印、边框、投影框、签名字样、道具、人物、置景。\n\n"
        f"输出：把成图原样（不裁剪、不缩放、不压缩、不改格式）复制到 {out_path}，"
        "确认文件存在且 > 20KB，然后只回一行：DONE <成图路径>。不要别的解释。\n"
    )


def _env(proxy: str | None) -> dict:
    env = dict(os.environ)
    if proxy:
        env["HTTPS_PROXY"] = env.get("HTTPS_PROXY") or proxy
        env["HTTP_PROXY"] = env.get("HTTP_PROXY") or proxy
        env["ALL_PROXY"] = env.get("ALL_PROXY") or f"socks5://{proxy.split('://')[-1]}"
    return env


def _collect(tmp: Path, out: Path, t0: float) -> list[Path]:
    """codex 把成图放在 ~/.codex/generated_images/<id>/ 下，所以三个地方都要捞。"""
    cands: list[Path] = []
    roots = [tmp, Path.home() / ".codex" / "generated_images", out.parent]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                try:
                    if p.stat().st_mtime >= t0 - 5 and p.stat().st_size > 15_000:
                        cands.append(p)
                except OSError:
                    pass
    return cands


def validate(out: Path, ref: Path) -> tuple[bool, str]:
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return True, "跳过体检（缺 numpy/Pillow）"
    try:
        im = Image.open(out)
        w, h = im.size
        a = np.asarray(im.convert("L").resize((256, 256)), dtype=np.float32)
        b = np.asarray(Image.open(ref).convert("L").resize((256, 256)), dtype=np.float32)
    except Exception as e:
        return False, f"读不了图：{e}"
    if out.stat().st_size < 20_000:
        return False, f"文件太小（{out.stat().st_size} B）"
    if h / w < 1.05:
        return False, f"不是竖版（{w}x{h}），版式大概被改了"
    if float(a.std()) < 8:
        return False, "画面几乎是纯色（可能没画出内容）"
    diff = float(np.abs(a - b).mean())
    if diff < 6.0:
        return False, f"和参考图几乎一样（平均差 {diff:.1f}），明显是原样退回参考图"
    return True, f"ok（{w}x{h}，{out.stat().st_size // 1024} KB，与参考图差异 {diff:.1f}）"


def main() -> int:
    ap = argparse.ArgumentParser(description="把字体预览海报渲染成真实材质版（codex image_gen）")
    ap.add_argument("--project", help="字体项目目录（含 05_preview/specimen.png + specimen.json）")
    ap.add_argument("--ref", help="直接用某个 specimen.png（不给 --project 时用）")
    ap.add_argument("--out-dir", help="默认 <project>/06_art")
    ap.add_argument("--material", action="append", default=None,
                    help="材质搭配，自由文本（如 \"老旧红砖墙 + 街头喷漆\"）。"
                         "可给多次；用户指名就用用户的，否则由 agent 随机想一组再传进来")
    ap.add_argument("--timeout", type=int, default=900, help="单张超时（秒）")
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--proxy", default=DEFAULT_PROXY, help="codex 直连 chatgpt.com 会超时，默认走本地 7890")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词，不调模型")
    a = ap.parse_args()

    if a.project:
        proj = Path(a.project).expanduser().resolve()
        ref = Path(a.ref).expanduser().resolve() if a.ref else proj / "05_preview/specimen.png"
        out_dir = Path(a.out_dir).expanduser().resolve() if a.out_dir else proj / "06_art"
    elif a.ref:
        ref = Path(a.ref).expanduser().resolve()
        out_dir = Path(a.out_dir).expanduser().resolve() if a.out_dir else ref.parent.parent / "06_art"
    else:
        sys.exit("要么给 --project，要么给 --ref")
    if not ref.exists():
        sys.exit(f"参考图不存在: {ref}")
    if not a.material:
        sys.exit("没有材质搭配。材质不由脚本内置：用户指名就按用户的，"
                 "没指名就让 agent 随机想一组，再通过 --material \"…\" 传进来。")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 从 specimen.json 拿词组/标语/字符集，拼进「拼写不能错」这条硬规则 ──
    meta: dict = {}
    sj = ref.parent / "specimen.json"
    if sj.exists():
        try:
            d = json.loads(sj.read_text(encoding="utf-8"))
            if isinstance(d, list) and d:
                meta = next((x for x in d if str(x.get("out", "")).endswith(ref.name)), d[0])
            elif isinstance(d, dict):
                meta = d
        except Exception:
            meta = {}
    family = meta.get("family") or ref.stem
    word = meta.get("word") or "（与参考图上方的两个词完全相同）"
    sentence = meta.get("sentence") or "（与参考图那行标语完全相同）"
    digits = "0-9" in str(meta.get("charset", "")) or meta.get("digits") is True
    row_chars = meta.get("grid", {}).get("row_characters")
    grid = (f"共 {len(row_chars)} 行，逐行为：" + " / ".join(row_chars)) if row_chars else ("A–Z 两行 + 0–9 一行" if digits else "A–Z 两行")

    results = []
    for material in a.material:
        out = out_dir / f"{family}_{slugify(material)}.png"
        prompt = build_prompt(material, word, sentence, grid, ref, out)
        stem = out.with_suffix("")
        Path(f"{stem}.prompt.txt").write_text(prompt, encoding="utf-8")
        if a.dry_run:
            print(prompt)
            continue

        ok, why = False, ""
        for attempt in range(1, a.attempts + 1):
            tmp = Path(tempfile.mkdtemp(prefix="fonter-mat-"))
            if out.exists():
                out.unlink()
            t0 = time.time()
            print(f"  → {material}  尝试 {attempt}/{a.attempts} …", flush=True)
            cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-i", str(ref), "-"]
            try:
                p = subprocess.run(cmd, cwd=tmp, input=prompt, capture_output=True, text=True,
                                   timeout=a.timeout, env=_env(None if a.no_proxy else a.proxy))
                stdout = p.stdout
            except subprocess.TimeoutExpired:
                print("    超时", flush=True)
                shutil.rmtree(tmp, ignore_errors=True)
                continue
            Path(f"{stem}.cli.jsonl").write_text(
                stdout + ("\n---STDERR---\n" + p.stderr if p.stderr else ""), encoding="utf-8")

            if not out.exists():
                # Only accept generated paths attributed to this invocation's log.
                log = stdout + "\n" + p.stderr
                reported = re.findall(r"/[^\s\"'<>]*generated_images/[^\s\"'<>]+\.(?:png|jpg|jpeg|webp)", log)
                cands = [Path(x) for x in dict.fromkeys(reported) if Path(x).is_file()]
                if not cands:
                    cands = [x for x in tmp.rglob("*.png") if x.stat().st_mtime >= t0]
                best, best_area = None, 0
                for c in cands:
                    try:
                        from PIL import Image
                        with Image.open(c) as im:
                            ar = im.width * im.height
                    except Exception:
                        ar = 0
                    if ar > best_area:
                        best, best_area = c, ar
                if best is None:
                    print("    没产出图片", flush=True)
                    shutil.rmtree(tmp, ignore_errors=True)
                    continue
                shutil.copy2(best, out)
            shutil.rmtree(tmp, ignore_errors=True)
            ok, why = validate(out, ref)
            print(f"    {out.name}  {why}", flush=True)
            if ok:
                break
            out.unlink(missing_ok=True)
        results.append({"material": material, "out": str(out) if ok else None,
                        "ok": ok, "check": why})

    Path(out_dir / "materials.json").write_text(
        json.dumps({"ref": str(ref), "family": family, "word": word, "sentence": sentence,
                    "grid": grid, "engine": "codex image_gen", "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.dry_run:
        good = [r for r in results if r["ok"]]
        print(f"[render_material] 完成 {len(good)}/{len(results)} 张 → {out_dir}", flush=True)
    return 0 if (a.dry_run or all(r["ok"] for r in results)) else 1


if __name__ == "__main__":
    sys.exit(main())
