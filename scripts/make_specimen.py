#!/usr/bin/env python3
"""用刚做好的字体渲染一张「字体预览海报」（对标 05_preview 的参考样张）。

版式（参考 12112.png）：
  上半  随机词组 / 指定词组，用生字体本身排，字距统一
  中部  条码 + 说明小字 + 分隔线
  下半  A–Z（及数字）整齐排列，每格等大、等字高

用法:
  python3 make_specimen.py --font 04_font/POLYMER.ttf --out 05_preview/specimen.png \
      --style geometric --word "HYPER SECTOR"        # 不给 --word 就随机
  python3 make_specimen.py --font ... --digits off    # 不要数字
  python3 make_specimen.py --font ... --palette all   # 每套潘通撞色各出一张

铁律:
  * 网格里每个字母/数字的墨迹高度完全一致（先量墨迹再按高度归一化，不看字体度量）。
  * 每行字距 = 固定 value，靠「逐字量墨迹 + 固定间隙」排，不用 font 的 advance，
    所以不会出现排出来的句子里字距忽大忽小。
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 潘通撞色方案
# 每套都是「深底 + 撞色亮字」或「亮底 + 深字」的高对比组合，取自 Pantone TCX 常见色。
PALETTES = {
    # 高饱和撞色：底色走深/浓，字色走亮/纯，明度差 ≥ 45% 才不会糊
    "forest":       dict(bg="#05402A", fg="#F7EE9C", pantone="19-5411 Forest Biome / 12-0736 Lemon"),
    "lime":         dict(bg="#0A3D1B", fg="#C6FF33", pantone="18-0332 Grass Green / 13-0550 Lime Punch"),
    "classic_blue": dict(bg="#0A4EA8", fg="#FFD233", pantone="19-4052 Classic Blue / 13-0755 Primrose Yellow"),
    "ultraviolet":  dict(bg="#4A2B96", fg="#FFE14D", pantone="18-3838 Ultra Violet / 13-0755 Primrose Yellow"),
    "fiery":        dict(bg="#D8142F", fg="#FFF4DC", pantone="18-1664 Fiery Red / 11-0601 Bright White"),
    "iris":         dict(bg="#191B4D", fg="#FFD400", pantone="19-3921 Black Iris / 13-0858 Vibrant Yellow"),
    "emerald":      dict(bg="#00795C", fg="#FFB01F", pantone="17-5641 Emerald / 15-0960 Golden Apricot"),
    "coral":        dict(bg="#FF6F5E", fg="#0B2D8F", pantone="16-1546 Living Coral / 19-4052 Classic Blue"),
    "tangerine":    dict(bg="#FF5A1F", fg="#0B1B4A", pantone="17-1463 Tangerine / 19-4023 Total Eclipse"),
    "ink":          dict(bg="#0D1C4A", fg="#FF3B30", pantone="19-4220 Dark Slate / 18-1664 Fiery Red"),
    "greenery":     dict(bg="#6FBF23", fg="#0B1B4A", pantone="15-0343 Greenery / 19-4023 Total Eclipse"),
    "marsala":      dict(bg="#8E2B35", fg="#FFE1A8", pantone="18-1438 Marsala / 12-0712 Vanilla Ice"),
    "serenity":     dict(bg="#7FB3FF", fg="#0B1B4A", pantone="15-3919 Serenity / 19-4110 Midnight Navy"),
    "magenta":      dict(bg="#C2006B", fg="#FFE94A", pantone="17-2031 Fuchsia Rose / 13-0755 Primrose Yellow"),
    "electric":     dict(bg="#00C2D1", fg="#0A0A2A", pantone="16-4529 Cyan Blue / 19-4005 Stretch Limo"),
}

# 字体风格 → 优先配色（撞色要跟字的气质对上）
STYLE_PALETTES = {
    "geometric": ["forest", "classic_blue", "iris"],
    "minimal": ["classic_blue", "forest", "serenity"],
    "bold": ["fiery", "tangerine", "magenta"],
    "heavy": ["fiery", "tangerine", "ink"],
    "blob": ["ultraviolet", "magenta", "greenery"],
    "organic": ["ultraviolet", "emerald", "marsala"],
    "blackletter": ["fiery", "iris", "marsala"],
    "ornate": ["fiery", "iris", "magenta"],
    "brush": ["tangerine", "magenta", "fiery"],
    "graffiti": ["tangerine", "electric", "greenery"],
    "script": ["ultraviolet", "marsala", "coral"],
    "rounded": ["coral", "greenery", "electric"],
    "tech": ["electric", "iris", "classic_blue"],
}

WORDS = [
    "HYPER SECTOR", "NIGHT SHIFT", "PAPER TIGER", "MOTOR CITY", "SILK ROAD",
    "WILD CARD", "BLACK SAND", "GHOST TOWN", "LATE BLOOM", "TIN ROOF",
    "FAST LANE", "DEEP FIELD", "OPEN WATER", "HARD BOIL", "SOFT MACHINE",
    "PALE FIRE", "SLOW BURN", "LOUD QUIET", "GOLD LEAF", "COLD BREW",
    "IRON GARDEN", "NEON RIVER", "SALT FLAT", "BLUE HOUR", "DRY COUNTY",
    "HEAVY PETAL", "LUNAR TIDE", "SWEET RIOT", "BLUNT KNIFE", "MARBLE HALL",
    "STONE FRUIT", "PLASTIC SAINT", "VELVET WIRE", "CIVIC DUTY", "HOLLOW POINT",
    "QUIET STORM", "BRASS MONKEY", "DUTCH ANGLE", "FROZEN ASSET", "GLASS JAW",
    "PRIME MOVER", "ROUGH TRADE", "SHARP TURN", "QUEST CLUB", "VIVID DREAM",
    "BLACK OUT", "FRESH CUT", "JUICY LOOP",
]

# 词库按字母打散用：单字（非词组）池，用于「抽两个词拼一行」
WORD_POOL = sorted({w for pair in WORDS for w in pair.split()} | {
    "ZEBRA", "QUARTZ", "JOKER", "VORTEX", "GLYPH", "KILN", "MAZE", "ONYX",
    "PLUSH", "SWARM", "XENON", "YIELD", "FJORD", "BRISK", "CHUNK", "DWARF",
})


SENTENCES = [
    "GET RICH OR DIE TRYIN", "NO RULES JUST RIOT", "MADE FOR THE NIGHT",
    "LOUD IS A LANGUAGE", "PRINT IT ON THE WALL", "KEEP THE ENGINE RUNNING",
    "SALT IN THE WOUND", "RUN IT BACK AGAIN", "BORN FROM THE ASPHALT",
    "ALL KILLER NO FILLER", "TOO FAST TO FADE", "NEVER ASK PERMISSION",
    "SOMEONE LEFT THE LIGHT ON", "STAY HUNGRY STAY LOUD", "MAKE IT HURT SO GOOD",
    "SKETCH FIRST THINK LATER", "NOTHING SOFT ABOUT IT", "CUT THE NOISE OUT",
    "WE BUILD IT IN THE DARK", "TAKE THE LONG WAY HOME", "HIT HARD GO QUIET",
    "THE CITY EATS THE SLOW", "A LITTLE TOO MUCH", "SIGNED IN SPRAY PAINT",
    "WHO NEEDS A MAP", "DRIVE TIL THE ROAD ENDS", "BOLD BY DEFAULT",
    "WRITE IT IN CONCRETE", "NO SECOND TAKE", "SPLIT THE SILENCE",
    "FLAT OUT UNREASONABLE", "HEAVY ON THE BLUR", "BRIGHT SIDE OF WRONG",
    "CALL IT WHAT IT IS", "ALWAYS SIDEWAYS NEVER STRAIGHT",
]


def pick_sentence(family, seed=0):
    """按字体名 + seed 抽一句标语（每套字体各不相同）。"""
    import hashlib
    h = hashlib.md5(f"sentence|{family}|{seed}".encode("utf-8")).hexdigest()
    return SENTENCES[int(h[:8], 16) % len(SENTENCES)]


def pick_two_words(family, seed=0):
    """按字体名 + seed 抽**两个不同的单词**（同一字体每次都一样，不同字体必然不同）。

    这是给「每套字体都要重新生成两个词的预览」用的：不指定 --word 就走这里。
    """
    import hashlib
    h = hashlib.md5(f"{family}|{seed}".encode("utf-8")).hexdigest()
    n = len(WORD_POOL)
    a = int(h[:8], 16) % n
    b = int(h[8:16], 16) % n
    if b == a:
        b = (b + 1 + int(h[16:20], 16) % (n - 1)) % n
    return [WORD_POOL[a], WORD_POOL[b]]


# ---------------------------------------------------------------- 工具
def glyph_mask(font_path, ch, px):
    """渲染单个字符，返回紧贴墨迹的 L 模式 mask（白=墨）。"""
    f = ImageFont.truetype(font_path, px)
    canvas = Image.new("L", (int(px * 3), int(px * 3)), 0)
    ImageDraw.Draw(canvas).text((px * 0.8, px * 0.8), ch, font=f, fill=255)
    bb = canvas.getbbox()
    if not bb:
        return None
    return canvas.crop(bb)


def normalize_h(mask, target_h):
    w, h = mask.size
    new_w = max(1, round(w * target_h / h))
    return mask.resize((new_w, int(round(target_h))), Image.LANCZOS)


def paste_mask(canvas, mask, x, y, color):
    patch = Image.new("RGB", mask.size, color)
    canvas.paste(patch, (int(round(x)), int(round(y))), mask)


def measure_gap_stats(positions):
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    if not gaps:
        return 0.0, 0.0
    return min(gaps), max(gaps)


def layout_line(font_path, text, cap_h, tracking, probe_px=None):
    """返回 [(mask, x)] 与总宽度：逐字量墨迹、统一高度、固定间隙。"""
    size = int(max(cap_h, 8) * 2.2) if probe_px is None else probe_px
    masks = []
    for ch in text:
        if ch == " ":
            masks.append(("space", max(1, int(cap_h * 0.30))))
            continue
        m = glyph_mask(font_path, ch, size)
        if m is not None:
            masks.append(("glyph", normalize_h(m, cap_h)))
    x = 0.0
    placed = []
    for kind, obj in masks:
        if kind == "space":
            x += obj
            continue
        placed.append((obj, x))
        x += obj.width + tracking
    total = x - tracking if placed else 0
    return placed, total


def draw_layout(canvas, placed, x0, y, color):
    for mask, x in placed:
        paste_mask(canvas, mask, x0 + x, y, color)


def ink_gaps(placed):
    gaps = [(b[1]) - (a[1] + a[0].width) for a, b in zip(placed, placed[1:])]
    return (min(gaps), max(gaps)) if gaps else (0.0, 0.0)


def luminance(hexcolor):
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def infer_style(font_path, charset):
    """粗判字体气质：墨迹覆盖率高的当 bold，细的当 geometric。"""
    cov = []
    for ch in charset[:12]:
        m = glyph_mask(font_path, ch, 200)
        if not m:
            continue
        arr = m.point(lambda v: 255 if v > 127 else 0)
        cov.append(sum(1 for p in arr.getdata() if p) / (m.width * m.height))
    if not cov:
        return "geometric"
    c = sum(cov) / len(cov)
    if c > 0.46:
        return "bold"
    if c < 0.24:
        return "minimal"
    return "geometric"


# ---------------------------------------------------------------- 主渲染
def render(font_path, out_path, word, sentence, style, palette_name, digits, width, desc, seed):
    font_path = str(font_path)
    cmap = font_metrics_charset(font_path)
    up = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c in cmap]
    # 只有「真的有自己的小写字形」才排小写行；只是 a→A 镜像的不重复排
    low = [c for c in "abcdefghijklmnopqrstuvwxyz"
           if c in cmap and cmap.get(c.upper()) != cmap[c]]
    nums = [c for c in "0123456789" if c in cmap]
    ttf_charset = set(cmap)

    if style == "auto":
        style = infer_style(font_path, up or low or nums)
    if palette_name == "auto":
        palette_name = STYLE_PALETTES.get(style, ["forest"])[seed % len(STYLE_PALETTES.get(style, ["forest"]))]
    pal = PALETTES[palette_name]

    W = width
    H = int(round(W * 2113 / 1688))
    canvas = Image.new("RGB", (W, H), pal["bg"])
    fg = pal["fg"]

    # ---- 上半：词组（最多两行，字距统一、整体不越界）----
    lines = word.split()
    if len(lines) > 2:
        mid = (len(lines) + 1) // 2
        lines = [" ".join(lines[:mid]), " ".join(lines[mid:])]
    cap_h = H * 0.150
    tracked = cap_h * 0.09
    max_w = W * 0.84
    # 先按名义字高排版，再整体缩到安全宽度内
    for _ in range(6):
        layouts = [layout_line(font_path, ln, cap_h, tracked) for ln in lines]
        widest = max(w for _, w in layouts)
        if widest <= max_w:
            break
        k = max_w / widest
        cap_h *= k
        tracked *= k

    block_h = len(lines) * cap_h * 1.24
    y = max(H * 0.06, (H * 0.44 - block_h) / 2 + H * 0.03)
    spacing_report = []
    for ln, (placed, w) in zip(lines, layouts):
        draw_layout(canvas, placed, (W - w) / 2, y, fg)
        gmin, gmax = ink_gaps(placed)
        spacing_report.append(dict(line=ln, width=int(w), ink_gap_min=round(gmin, 2),
                                   ink_gap_max=round(gmax, 2)))
        y += cap_h * 1.24

    # ---- 大字下方：一句随机标语（也用字体本身排，字距统一）----
    sent = sentence
    if not any(c.islower() for c in ttf_charset):
        sent = sent.upper()
    elif not any(c.isupper() for c in ttf_charset):
        sent = sent.lower()
    cap_sent = min(H * 0.040, max(H * 0.022, (H * 0.050) * (len(sent) / 24) ** -0.35))
    tr_sent = cap_sent * 0.10
    max_w_sent = W * 0.80
    for _ in range(6):
        placed_s, w_s = layout_line(font_path, sent, cap_sent, tr_sent)
        if w_s <= max_w_sent:
            break
        k = max_w_sent / max(w_s, 1)
        cap_sent *= k
        tr_sent *= k
    sent_y = y + cap_h * 0.16
    draw_layout(canvas, placed_s, (W - w_s) / 2, sent_y, fg)
    gmin, gmax = ink_gaps(placed_s)
    spacing_report.append(dict(line=sent, width=int(w_s),
                               ink_gap_min=round(gmin, 2), ink_gap_max=round(gmax, 2)))

    # ---- 通栏分割线：颜色与字体一致 ----
    div_y = int(H * 0.545)
    div_h = max(3, int(round(H * 0.006)))
    ImageDraw.Draw(canvas).rectangle([0, div_y, W, div_y + div_h - 1], fill=fg)

    # ---- 下半：字母 / 数字网格（每格等大）----
    show_upper = up
    show_low = low if (up or not low) else low
    grid_rows_sets = []
    if show_upper:
        grid_rows_sets.append(show_upper)
    if show_low:
        grid_rows_sets.append(show_low)
    if digits and nums:
        grid_rows_sets.append(nums)

    grid_left = W * 0.075
    grid_w = W * 0.85
    n_chars = max(len(s) for s in grid_rows_sets)
    per_row = 13 if n_chars >= 13 else n_chars
    cell_w = grid_w / per_row
    top = div_y + div_h + int(H * 0.035)
    bottom = H - int(H * 0.050)

    rows = []
    for s_ in grid_rows_sets:
        if not s_:
            continue
        per = min(per_row, len(s_)) if len(s_) <= per_row else per_row
        if len(s_) <= per_row:
            rows.append(s_)
        else:
            for i in range(0, len(s_), per_row):
                rows.append(s_[i:i + per_row])
    row_h = (bottom - top) / max(1, len(rows))

    # 候选字高：受行高和「最宽的字不能溢出格子」双重限制，所有字共用同一个高度
    probe = {}
    probe_h = row_h * 0.9
    for ch in {c for s_ in grid_rows_sets for c in s_}:
        m = glyph_mask(font_path, ch, int(probe_h * 2.2))
        if m is not None:
            probe[ch] = (m.width / m.height)
    widest_ratio = max(probe.values()) if probe else 1.0
    ink_h = min(row_h * 0.70, (cell_w * 0.86) / max(widest_ratio, 0.01))
    ink_h = max(ink_h, 12)
    # 行数 >=3 时按等分行高铺满（和参考样张一样上下撑开）；行少时别把一行摊在大片空白里
    if len(rows) >= 3:
        row_h_used = row_h
        y_start = top
    else:
        row_h_used = min(row_h, ink_h * 1.45)
        block_h = row_h_used * max(1, len(rows))
        y_start = top + ((bottom - top) - block_h) / 2

    grid_report = {"per_row": per_row, "rows": len(rows), "cell_w": round(cell_w, 1),
                   "row_h": round(row_h_used, 1), "ink_h": round(ink_h, 1), "cells": {}}

    for ri, row in enumerate(rows):
        row_top = y_start + ri * row_h_used
        n = len(row)
        off = (per_row - n) * cell_w / 2  # 末行居中
        for ci, ch in enumerate(row):
            m = glyph_mask(font_path, ch, int(ink_h * 2.4))
            if m is None:
                continue
            m = normalize_h(m, ink_h)
            cx = grid_left + off + ci * cell_w + (cell_w - m.width) / 2
            cy = row_top + (row_h_used - m.height) / 2
            paste_mask(canvas, m, cx, cy, fg)
            grid_report["cells"][ch] = dict(w=int(m.width), h=int(m.height),
                                            x=round(cx, 1), y=round(cy, 1))
    grid_report["row_spacing"] = report_row_spacing(grid_report)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)

    # ---- 校验输出 ----
    hs = {ch: v["h"] for ch, v in grid_report["cells"].items()}
    uniq = sorted(set(hs.values()))
    meta = dict(
        font=font_path, out=str(out_path), family=Path(font_path).stem,
        word=word, sentence=sent, style=style, palette=palette_name, pantone=pal["pantone"],
        bg=pal["bg"], fg=pal["fg"], digits=digits, generated=str(date.today()),
        grid=grid_report, top_spacing=spacing_report,
        ink_heights_unique=uniq,
        verdict="PASS" if len(uniq) <= 2 else "WARN 网格字高不一致",
    )
    return meta


def font_metrics_charset(font_path):
    """返回 {字符: glyph 名}。用来判断「小写是不是只是大写的镜像」。"""
    from fontTools.ttLib import TTFont
    f = TTFont(font_path, fontNumber=0)
    return {chr(k): v for k, v in f.getBestCmap().items() if 32 <= k < 127}


def balance_lines(text, n=3):
    words = text.split()
    if not words:
        return [""]
    total = sum(len(w) + 1 for w in words)
    target = total / n
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if sum(len(x) + 1 for x in cur) >= target and len(lines) < n - 1:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    return lines


def report_row_spacing(grid_report):
    """同一行内相邻字母的水平间隙是否一致（等大一格一格的排法应当完全一致）。"""
    rows = {}
    for ch, v in grid_report["cells"].items():
        rows.setdefault(round(v["y"], 1), []).append((v["x"], v["w"]))
    out = []
    for y, items in rows.items():
        items.sort()
        gaps = [round(b[0] - (a[0] + a[1]), 1) for a, b in zip(items, items[1:])]
        if gaps:
            out.append(dict(y=y, gap_min=min(gaps), gap_max=max(gaps), n=len(items) + 1))
    return out


DEFAULT_DESC = ("A DISPLAY TYPEFACE DERIVED FROM A HAND-DRAWN REFERENCE, WITH A CLEAN URBAN "
                "STYLE AND BOLD CHARACTER. SUITABLE FOR LOGOS, POSTERS, ALBUM COVERS AND "
                "EYE-CATCHING HEADLINES.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--out", required=True, help="输出 PNG（--palette all 时当文件名前缀）")
    ap.add_argument("--sentence", default=None,
                    help="大字下方那句标语；不给就按字体名随机抽一句")
    ap.add_argument("--word", default="auto",
                    help="标题词组（两个词最好）；auto = 按字体名抽两个随机单词")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--style", default="auto",
                    help="geometric/bold/blob/blackletter/brush/…/auto（决定配色取向）")
    ap.add_argument("--palette", default="auto", help="配色名或 auto，或 all（每套各出一张）")
    ap.add_argument("--digits", default="on", choices=["on", "off"])
    ap.add_argument("--desc", default=DEFAULT_DESC)
    ap.add_argument("--width", type=int, default=1688)
    args = ap.parse_args()

    family = Path(args.font).stem
    if args.word in (None, "", "auto", "random"):
        picked = pick_two_words(family, args.seed)
        word = " ".join(picked)
        print(f"[specimen] {family} 随机词组: {picked[0]} / {picked[1]}")
    else:
        word = args.word
        picked = word.split()
    palettes = list(PALETTES) if args.palette == "all" else [args.palette]

    metas = []
    for p in palettes:
        outp = Path(args.out)
        if args.palette == "all":
            outp = outp.with_name(f"{outp.stem}_{p}{outp.suffix}")
        sentence = args.sentence or pick_sentence(family, args.seed)
        if args.sentence:
            sentence = args.sentence
        meta = render(args.font, outp, word, sentence, args.style, p,
                      args.digits == "on", args.width, args.desc, args.seed)
        meta["words"] = picked
        metas.append(meta)
        print(f"[specimen] {outp}  palette={meta['palette']} ({meta['pantone']})  "
              f"字高一致性 {meta['ink_heights_unique']}  {meta['verdict']}")
        for sp in meta["top_spacing"]:
            print(f"   行「{sp['line']}」墨迹间隙 {sp['ink_gap_min']}–{sp['ink_gap_max']} px（固定值，理想差 0）")

    Path(str(args.out)).with_suffix(".json").write_text(json.dumps(metas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
