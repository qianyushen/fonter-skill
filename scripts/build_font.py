#!/usr/bin/env python3
"""把切好的字母 PNG 组装成可安装的 TTF，并把「字距均匀 / 字母等大」写进字体度量。

用法:
  python3 build_font.py --sources 02_letters/POLYMER 02_letters/ROCKET \
      --family POLYMER --out 04_font/POLYMER.ttf [--charset A-Z0-9] \
      [--gap 120] [--cap 700] [--tabular-digits]

核心规则（这两条是硬要求，不要关掉）:
  1. 字母等大：每个单词的字高（cap_px）先量出来，整词同比例缩放到 cap=700，
     所以同一词里所有字母、以及不同词之间，字高完全一致。
  2. 字距均匀：左右边距都是 gap/2（同一套字体同一个数），
     于是任意相邻两字母的「可见墨迹间隙」都等于 gap，整句排出来不会忽紧忽松。
     数字默认走 tabular（advance 取所有数字的最大值并居中），表格/样张里不会参差。

产物: 04_font/<Family>.ttf + 04_font/metrics.json（含每个字母的 advance/边距/校验结论）
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import potrace
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen

SAMPLE_PER_CURVE = 6


# ---------------------------------------------------------------- potrace → 轮廓
def trace_png(path: Path, turdsize: int = 2, alphamax: float = 1.0):
    """返回 [(命令列表, 是否闭合)]，坐标为像素坐标（y 向下）。"""
    img = Image.open(path).convert("L")
    bmp = potrace.Bitmap(img)  # 黑=墨
    pathobj = bmp.trace(turdsize=turdsize, alphamax=alphamax, opticurve=True, opttolerance=0.2)
    contours = []
    for curve in pathobj:
        start = (curve.start_point.x, curve.start_point.y)
        cmds = [("M", start)]
        prev = start
        for seg in curve.segments:
            if seg.is_corner:
                c = (seg.c.x, seg.c.y)
                end = (seg.end_point.x, seg.end_point.y)
                cmds.append(("L", c))
                cmds.append(("L", end))
                prev = end
            else:
                c1 = (seg.c1.x, seg.c1.y)
                c2 = (seg.c2.x, seg.c2.y)
                end = (seg.end_point.x, seg.end_point.y)
                cmds.append(("C", c1, c2, end))
                prev = end
        contours.append(cmds)
    return contours


def flatten(cmds):
    pts = [cmds[0][1]]
    prev = cmds[0][1]
    for cmd in cmds[1:]:
        if cmd[0] == "L":
            pts.append(cmd[1])
            prev = cmd[1]
        else:
            _, c1, c2, end = cmd
            for i in range(1, SAMPLE_PER_CURVE + 1):
                t = i / SAMPLE_PER_CURVE
                x = ((1 - t) ** 3 * prev[0] + 3 * (1 - t) ** 2 * t * c1[0]
                     + 3 * (1 - t) * t ** 2 * c2[0] + t ** 3 * end[0])
                y = ((1 - t) ** 3 * prev[1] + 3 * (1 - t) ** 2 * t * c1[1]
                     + 3 * (1 - t) * t ** 2 * c2[1] + t ** 3 * end[1])
                pts.append((x, y))
            prev = end
    return pts


def _cubic_pts(p0, c1, c2, p3):
    return p0, c1, c2, p3


def _quad_roots(a, b, c):
    roots = []
    if abs(a) < 1e-12:
        if abs(b) > 1e-12:
            roots.append(-c / b)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            sq = disc ** 0.5
            roots += [(-b + sq) / (2 * a), (-b - sq) / (2 * a)]
    return [t for t in roots if 0.0 < t < 1.0]


def _bez(p0, c1, c2, p3, t):
    mt = 1 - t
    return (mt ** 3 * p0 + 3 * mt * mt * t * c1 + 3 * mt * t * t * c2 + t ** 3 * p3)


def contour_extents(cmds):
    """轮廓的真实外接框：端点 + 三次曲线在 t 处的极值（控制点不参与极值，但决定导数）。"""
    xs, ys = [], []
    prev = cmds[0][1]
    xs.append(prev[0]); ys.append(prev[1])
    for cmd in cmds[1:]:
        if cmd[0] == "L":
            prev = cmd[1]
            xs.append(prev[0]); ys.append(prev[1])
            continue
        _, c1, c2, end = cmd
        for axis in (0, 1):
            p0, p1, p2, p3 = prev[axis], c1[axis], c2[axis], end[axis]
            a = 3 * (-p0 + 3 * p1 - 3 * p2 + p3)
            b = 6 * (p0 - 2 * p1 + p2)
            c = 3 * (p1 - p0)
            for t in _quad_roots(a, b, c):
                v = _bez(p0, p1, p2, p3, t)
                (xs if axis == 0 else ys).append(v)
        prev = end
        xs.append(prev[0]); ys.append(prev[1])
    return min(xs), max(xs), min(ys), max(ys)


def interior_point(poly):
    """找一个严格落在轮廓内部的点（扫描线最宽区间中点），用于判「套在谁里面」。"""
    ys = [p[1] for p in poly]
    y0, y1 = min(ys), max(ys)
    n = len(poly)
    for frac in (0.5, 0.37, 0.62, 0.44, 0.28, 0.72):
        y = y0 + (y1 - y0) * frac
        xs = []
        for i in range(n):
            x1, yy1 = poly[i]
            x2, yy2 = poly[(i + 1) % n]
            if (yy1 > y) != (yy2 > y):
                xs.append(x1 + (y - yy1) * (x2 - x1) / (yy2 - yy1))
        xs.sort()
        spans = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]
        if spans:
            a, b = max(spans, key=lambda t: t[1] - t[0])
            if b - a > 1.0:
                return ((a + b) / 2.0, y)
    return poly[0]


def signed_area(pts) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def point_in_poly(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def reverse_cmds(cmds):
    """把一条闭合轮廓的命令序列反向（起点换到最后一个点）。"""
    segs = cmds[1:]
    pts = [cmds[0][1]] + [c[-1] for c in segs]
    out = [("M", pts[-1])]
    for idx in range(len(segs) - 1, -1, -1):
        cmd = segs[idx]
        if cmd[0] == "L":
            out.append(("L", pts[idx]))
        else:
            _, c1, c2, _end = cmd
            out.append(("C", c2, c1, pts[idx]))
    return out


def emit(pen, cmds, scale, tx, ty, flip_y, page_h, y_ref=None, bottom=0.0):
    """像素命令 → 字体坐标，喂给 pen。

    flip_y 时：y_font = (y_ref - y) * scale + bottom（y_ref = 墨迹顶沿像素坐标）
    """
    if y_ref is None:
        y_ref = page_h

    def tf(p):
        x, y = p
        yv = (y_ref - y) if flip_y else y
        return (x * scale + tx, yv * scale + bottom + ty)

    for cmd in cmds:
        if cmd[0] == "M":
            pen.moveTo(tf(cmd[1]))
        elif cmd[0] == "L":
            pen.lineTo(tf(cmd[1]))
        else:
            pen.curveTo(tf(cmd[1]), tf(cmd[2]), tf(cmd[3]))
    pen.closePath()


def clean_cmds(cmds):
    """去掉零长度线段/曲线（重复点）。Adobe CoolType 对重复点很敏感，会直接判字体坏。"""
    out = [cmds[0]]
    cur = cmds[0][1]
    for cmd in cmds[1:]:
        if cmd[0] == "L":
            if abs(cmd[1][0] - cur[0]) < 1e-9 and abs(cmd[1][1] - cur[1]) < 1e-9:
                continue
            out.append(cmd)
            cur = cmd[1]
        else:
            _, c1, c2, end_p = cmd
            same = all(abs(a[0] - cur[0]) < 1e-9 and abs(a[1] - cur[1]) < 1e-9
                       for a in (c1, c2, end_p))
            if same:
                continue
            out.append(cmd)
            cur = end_p
    return out


def prepare_glyph(png: Path, cand: dict, cap: int, lsb: float):
    """算出一个字母画到字体坐标里的全部参数（不落笔，TTF/OTF 共用）。

    规范化规则（都不靠字体度量，只看真实墨迹）：
      * 水平：墨迹左沿正好落在 lsb，advance = 墨迹宽 + gap → 可见间隙恒等。
      * 垂直：本词 cap 归一化到 cap；字母自身相对高度（描点/尾钩）保留，
              墨迹底沿对齐到「基线 - 该字母的下沉量」。
    """
    contours = trace_png(png)
    if not contours:
        raise SystemExit(f"[build] {png} 没有轮廓")
    contours = [c for c in (clean_cmds(c) for c in contours) if len(c) >= 4]
    if not contours:
        raise SystemExit(f"[build] {png} 清洗后没有轮廓")
    polys = [flatten(c) for c in contours]
    ext = [contour_extents(c) for c in contours]
    tmin_x = min(e[0] for e in ext)
    tmax_x = max(e[1] for e in ext)
    tmin_y = min(e[2] for e in ext)
    tmax_y = max(e[3] for e in ext)
    ink_h_px = max(1e-6, tmax_y - tmin_y)

    word_scale = cap / cand["cap_px"]
    h_px = max(1e-6, cand["height"])
    d_px = cand["descender_px"]
    d_traced = d_px * (ink_h_px / h_px)
    above_px = max(1e-6, ink_h_px - d_traced)

    target_above = above_px * word_scale
    snapped = abs(target_above - cap) <= 0.04 * cap
    if snapped:
        target_above = float(cap)
    s = target_above / above_px
    bottom_target = -d_traced * s

    # 轮廓方向：potrace 输出本来就是外轮廓一个方向、洞相反，
    # 只需确认最大轮廓在字体坐标下是负面积（顺时针 = TrueType/CFF 外轮廓），否则整体翻转。
    areas_font = [signed_area([(x, -y) for x, y in poly]) for poly in polys]
    biggest = max(range(len(areas_font)), key=lambda i: abs(areas_font[i]))
    flip_all = areas_font[biggest] > 0

    return dict(
        contours=[reverse_cmds(c) if flip_all else c for c in contours],
        scale=s, tx=lsb - tmin_x * s, y_ref=tmax_y, bottom=bottom_target,
        ink_w=(tmax_x - tmin_x) * s, target_above=target_above, snapped=snapped,
        descender_px=cand["descender_px"],
    )


def draw_ttf(prep, max_err=0.05):
    ttpen = TTGlyphPen(None)
    pen = Cu2QuPen(ttpen, max_err=max_err, reverse_direction=False)
    for cmds in prep["contours"]:
        emit(pen, cmds, scale=prep["scale"], tx=prep["tx"], ty=0.0, flip_y=True,
             page_h=0.0, y_ref=prep["y_ref"], bottom=prep["bottom"])
    return ttpen.glyph()


def draw_cff(prep, advance):
    """CFF/OTF：三次曲线原样保留（不经 Cu2Qu，字形更准，Adobe 原生格式）。"""
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    pen = T2CharStringPen(advance, None)
    for cmds in prep["contours"]:
        emit(pen, cmds, scale=prep["scale"], tx=prep["tx"], ty=0.0, flip_y=True,
             page_h=0.0, y_ref=prep["y_ref"], bottom=prep["bottom"])
    cs = pen.getCharString()
    cs.private = None
    return cs


def _cff_box(advance):
    """CFF 用的空心方框 .notdef。"""
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    pen = T2CharStringPen(advance, None)

    def box(x0, y0, x1, y1, clockwise):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if not clockwise:
            pts = pts[::-1]
        pen.moveTo(pts[0])
        for pt in pts[1:]:
            pen.lineTo(pt)
        pen.closePath()

    box(60, 0, 440, 660, True)
    box(120, 60, 380, 600, False)
    cs = pen.getCharString()
    cs.private = None
    return cs


def _cff_empty(advance):
    """CFF 用的空白字形（空格）。"""
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    pen = T2CharStringPen(advance, None)
    cs = pen.getCharString()
    cs.private = None
    return cs


def measure_ink(font_path, chars, upem=None, scale=2):
    """逐字渲染，量真实墨迹相对「笔位 + 基线」的坐标（换算成字体单位）。

    TrueType 的 glyf bbox 会把二次曲线控制点也算进去（虚胖几单位），
    所以判「字距/字高是否一致」必须看渲染出来的墨迹，不能看 bbox 表。
    用 2×upem 渲染再除回去，把整像素量化误差压到 ±0.5 字体单位。
    """
    from PIL import Image, ImageDraw, ImageFont
    from fontTools.ttLib import TTFont
    if upem is None:
        upem = TTFont(font_path)["head"].unitsPerEm
    size = upem * scale
    # 注意：ImageFont.truetype 会按路径缓存字体对象，反复测量同一个路径会拿到旧字形。
    # 用 BytesIO 包一次，保证每轮都重新读文件。
    import io
    with open(font_path, "rb") as fh:
        pil = ImageFont.truetype(io.BytesIO(fh.read()), size)
    pad_x = int(size * 0.20)
    pad_top = int(size * 0.30)
    cw = int(size * 1.8)
    ch_ = int(size * 1.9)
    base_y = int(size * 1.35)
    out = {}
    for ch in chars:
        img = Image.new("L", (cw, ch_), 0)
        ImageDraw.Draw(img).text((pad_x, base_y), ch, font=pil, fill=255, anchor="ls")
        # 只认 >=128 的实心墨迹：极细的花体发丝边会被抗锯齿吃掉，用 >0 会来回抖动几个单位
        bb = img.point(lambda v: 255 if v >= 128 else 0).getbbox()
        if not bb:
            out[ch] = dict(x0=0.0, x1=0.0, top=0.0, bottom=0.0)
            continue
        out[ch] = dict(
            x0=(bb[0] - pad_x) / scale,
            x1=(bb[2] - pad_x) / scale,
            top=(base_y - bb[1]) / scale,
            bottom=(base_y - bb[3]) / scale,
        )
    return out


# ---------------------------------------------------------------- 读取字母来源
def load_sources(dirs, charset):
    """返回 {char: [(png, meta), ...]}，meta 含 cap_px / baseline_y。"""
    found = {c: [] for c in charset}
    for d in dirs:
        d = Path(d)
        lj = d / "letters.json"
        if lj.exists():
            meta = json.loads(lj.read_text())
            word, cap, base = meta["word"], meta["cap_px"], meta["baseline_y"]
            for L in meta["letters"]:
                ch = L["char"]
                if ch in found:
                    found[ch].append(
                        dict(png=d / L["file"], word=word, cap_px=cap, baseline_y=base,
                             bbox_y0=L["bbox"][1], width=L["width"], height=L["height"],
                             ink=L["ink"], descender_px=float(L.get("descender_px", 0.0)))
                    )
        else:
            for png in sorted(d.glob("*.png")):
                ch = png.stem
                if ch in found:
                    w, h = Image.open(png).size
                    found[ch].append(dict(png=png, word=d.name, cap_px=float(h),
                                          baseline_y=float(h), bbox_y0=0.0,
                                          width=w, height=h, ink=0, descender_px=0.0))
    return found


def pick_best(cands):
    """同一字母多份来源时挑一份：优先高度贴近本词 cap 的、宽高比不极端的。"""
    def score(c):
        h_err = abs(c["height"] - c["cap_px"]) / max(1.0, c["cap_px"])
        return h_err
    return sorted(cands, key=score)[0]


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", required=True, help="letters.json 目录（可多个，按优先级）")
    ap.add_argument("--family", required=True)
    ap.add_argument("--style-name", default="Regular")
    ap.add_argument("--out", required=True, help="输出路径：.ttf（glyf）或 .otf（CFF）")
    ap.add_argument("--charset", default=None, help="默认按来源里出现的字符，可指定如 A-Z0-9")
    ap.add_argument("--gap", type=int, default=120, help="相邻字母的墨迹间隙（字体单位，默认 120/1000em）")
    ap.add_argument("--cap", type=int, default=700, help="字高（字体单位）")
    ap.add_argument("--upem", type=int, default=1000)
    ap.add_argument("--space", type=int, default=280, help="空格 advance")
    ap.add_argument("--tabular-digits", action="store_true",
                    help="数字改成等宽（advance 取最大值并居中）；默认关闭——"
                         "等宽会在数字之间多出空隙，破坏「可见字距一致」")
    ap.add_argument("--no-tabular-digits", action="store_true",
                    help="（兼容旧参数，默认行为就是这样：数字走比例宽、可见间距恒定）")
    ap.add_argument("--descender", type=int, default=260, help="基线以下预留（花体/尾钩用）")
    ap.add_argument("--no-map-lowercase", action="store_true",
                    help="只有大写时默认把 a–z 映射到同一套大写字形（这样在 PS/Figma 里打小写也出字）；"
                         "加这个参数就不映射")
    ap.add_argument("--format", default="auto", choices=["auto", "ttf", "otf"],
                    help="ttf=glyf 二次曲线（默认），otf=CFF 三次曲线（Adobe 原生）")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = args.format if args.format != "auto" else ("otf" if out.suffix.lower() == ".otf" else "ttf")

    dirs = [Path(s) for s in args.sources]
    if args.charset:
        charset = []
        for part in args.charset.split(","):
            part = part.strip()
            if "-" in part and len(part) == 3:
                a, b = part.split("-")
                charset += [chr(c) for c in range(ord(a), ord(b) + 1)]
            else:
                charset += list(part)
    else:
        chars = set()
        for d in dirs:
            lj = Path(d) / "letters.json"
            if lj.exists():
                chars |= {L["char"] for L in json.loads(lj.read_text())["letters"]}
        charset = sorted(chars)
    if not charset:
        raise SystemExit("[build] 没有可用字符")

    found = load_sources(dirs, charset)
    missing = [c for c in charset if not found[c]]
    if missing:
        print(f"[build] ⚠ 缺字母: {''.join(missing)}")
    charset = [c for c in charset if found[c]]

    gap = args.gap
    lsb = gap / 2.0
    upem = args.upem
    glyphs, charstrings, metrics, report = {}, {}, {}, {}
    max_ymax, min_ymin = 0.0, 0.0

    for ch in charset:
        cand = pick_best(found[ch])
        prep = prepare_glyph(cand["png"], cand=cand, cap=args.cap, lsb=lsb)
        adv = int(round(prep["ink_w"])) + gap
        metrics[ch] = (adv, int(round(lsb)))

        if fmt == "otf":
            charstrings[ch] = draw_cff(prep, adv)
            xmin, ymin, xmax, ymax = (lsb, prep["bottom"],
                                      lsb + prep["ink_w"], prep["bottom"] + prep["target_above"])
        else:
            glyph = draw_ttf(prep)
            glyph.recalcBounds(glyphs)
            glyphs[ch] = glyph
            xmin, ymin, xmax, ymax = glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax
            adv = int(round(xmax - xmin)) + gap
            metrics[ch] = (adv, int(round(xmin)))

        cap_h = ymax - max(0.0, ymin)
        report[ch] = dict(
            word=cand["word"], src=str(cand["png"]), scale=round(prep["scale"], 4),
            advance=adv, lsb=int(round(xmin)),
            ink_width=int(round(xmax - xmin)), ink_height=int(round(ymax - ymin)),
            cap_height=int(round(cap_h)),
            ink_height_expected=round(prep["target_above"], 1),
            descender_px=round(prep["descender_px"], 2),
            xmin=int(round(xmin)), xmax=int(round(xmax)),
            ymin=int(round(ymin)), ymax=int(round(ymax)),
            size_anomaly=not prep["snapped"],
        )
        max_ymax = max(max_ymax, ymax)
        min_ymin = min(min_ymin, ymin)

    # tabular 数字（只在用户明确要等宽数字时）
    digits = [c for c in charset if c.isdigit()]
    if digits and args.tabular_digits and not args.no_tabular_digits:
        target = max(metrics[d][0] for d in digits)
        for d in digits:
            if fmt == "ttf":
                g = glyphs[d]
                dx = (target - (g.xMax - g.xMin)) / 2.0 - g.xMin
                glyphs[d] = _translate_glyph(g, dx)
                metrics[d] = (int(target), int(round(glyphs[d].xMin)))
            else:
                metrics[d] = (int(target), int(round((target - report[d]["ink_width"]) / 2)))
            report[d]["advance"] = int(target)
            report[d]["tabular"] = True

    # ---- .notdef：空心方框（缺字时能看见，不然 PS 里打字「什么都没出现」） ----
    # TrueType/CFF 约定：外轮廓顺时针、内轮廓逆时针，才会形成空心。
    def _box(x0, y0, x1, y1, clockwise):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if not clockwise:
            pts = pts[::-1]
        return pts

    def draw_box_glyph(pen, outer, inner):
        for pts in (outer, inner):
            pen.moveTo(pts[0])
            for pt in pts[1:]:
                pen.lineTo(pt)
            pen.closePath()

    notdef_pen = TTGlyphPen(None)
    draw_box_glyph(notdef_pen, _box(60, 0, 440, 660, True), _box(120, 60, 380, 600, False))
    notdef_glyph = notdef_pen.glyph()
    notdef_glyph.recalcBounds({})
    space_glyph = TTGlyphPen(None).glyph()

    # ---- cmap：A-Z / 0-9 + 空格；只有大写时把 a-z 指到同一套大写字形 ----
    cmap = {ord(c): c for c in charset}
    cmap[0x20] = "space"
    lower_map = {}
    if not args.no_map_lowercase and not any(c.islower() for c in charset):
        for c in charset:
            if c.isupper() and c.lower() not in [chr(k) for k in cmap]:
                cmap[ord(c.lower())] = c
                lower_map[c] = c.lower()

    order = [".notdef", "space"] + charset
    ascender = 750
    descender = -args.descender
    win_ascent = int(max(upem * 0.75, max_ymax + 30))
    win_descent = int(max(args.descender + 40, -min_ymin + 30))
    upem_scale = upem / 1000.0
    psiname = f"{args.family.replace(' ', '')}-{args.style_name}".strip("-")

    fb = FontBuilder(upem, isTTF=(fmt == "ttf"))
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    if fmt == "ttf":
        fb.setupGlyf({".notdef": notdef_glyph, "space": space_glyph, **glyphs})
    else:
        fb.setupCFF(psiname,
                    {"FullName": f"{args.family} {args.style_name}".strip(),
                     "FamilyName": args.family, "Weight": args.style_name,
                     "version": "Version 1.000", "Notice": f"Generated from a hand-drawn reference"},
                    {".notdef": _cff_box(500),
                     "space": _cff_empty(args.space),
                     **charstrings},
                    {})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "space": (args.space, 0), **metrics})
    fb.setupHorizontalHeader(ascent=ascender, descent=descender)
    fb.setupNameTable({
        "familyName": args.family,
        "styleName": args.style_name,
        "uniqueFontIdentifier": f"{args.family}-{args.style_name}; generated {date.today()}",
        "fullName": f"{args.family} {args.style_name}".strip(),
        "psName": psiname,
        "version": "Version 1.000",
    })
    # Adobe（PS/AI）对 OS/2 很挑：FontBuilder 默认 fsType=4 / fsSelection=0 /
    # ulCodePageRange=0 / 上下标尺寸=0，做出来的字体在 PS 里「看不到、选不中、用不了」。
    fb.setupOS2(
        sTypoAscender=ascender, sTypoDescender=descender, sTypoLineGap=0,
        usWinAscent=win_ascent, usWinDescent=win_descent,
        sxHeight=int(args.cap * 0.52), sCapHeight=args.cap,
        usWeightClass=700 if (args.cap and args.gap < 140) else 400,
        usWidthClass=5,
        fsType=0x0000,          # 0 = 可安装（4=仅预览打印、2=禁嵌入，都会让 PS 拒用）
        fsSelection=0x0040,     # bit6 REGULAR：没有这一位 PS 认不出「Regular」样式
        ulCodePageRange1=0x00000001,   # Latin-1 (1252)
        ulCodePageRange2=0,
        ySubscriptXSize=int(650 * upem_scale), ySubscriptYSize=int(600 * upem_scale),
        ySubscriptXOffset=0, ySubscriptYOffset=int(75 * upem_scale),
        ySuperscriptXSize=int(650 * upem_scale), ySuperscriptYSize=int(600 * upem_scale),
        ySuperscriptXOffset=0, ySuperscriptYOffset=int(350 * upem_scale),
        yStrikeoutSize=int(50 * upem_scale), yStrikeoutPosition=int(250 * upem_scale),
        sFamilyClass=0,
        achVendID="NONE",
    )
    fb.setupPost(formatType=2.0 if fmt == "ttf" else 3.0,
                 underlinePosition=int(-100 * upem_scale),
                 underlineThickness=int(50 * upem_scale))
    from fontTools.ttLib import newTable
    _gasp = newTable("gasp")
    _gasp.version = 1
    _gasp.gaspRange = {8: 0x000A, 0xFFFF: 0x000A}
    fb.font["gasp"] = _gasp
    fb.save(str(out))

    # ---- TTF 校正：按渲染实测墨迹微调左右位置与 advance（OTF 不必，三次曲线本来就是准的） ----
    if fmt == "ttf":
        import os as _os
        _dbg = _os.environ.get("BF_DEBUG", "")
        glyph_dict = {".notdef": notdef_glyph, "space": space_glyph, **glyphs}
        metric_dict = {".notdef": (500, 0), "space": (args.space, 0), **metrics}
        for _round in range(3):
            ink0 = measure_ink(str(out), charset, upem=upem)
            changed = 0
            for ch in charset:
                m = ink0[ch]
                dx = lsb - m["x0"]
                applied = 0
                if abs(dx) >= 0.5:
                    glyphs[ch] = _translate_glyph(glyphs[ch], dx)
                    glyph_dict[ch] = glyphs[ch]
                    applied = int(round(dx))
                    changed += 1
                adv = int(round((m["x1"] + applied) - lsb)) + gap
                if adv != metrics[ch][0]:
                    metrics[ch] = (adv, int(round(lsb)))
                    metric_dict[ch] = metrics[ch]
                    changed += 1
                report[ch]["advance"] = adv
                report[ch]["lsb"] = int(round(lsb))
            if _dbg:
                for ch in _dbg.split(","):
                    if ch in ink0:
                        print(f"[dbg] round{_round} {ch} x0={ink0[ch]['x0']} x1={ink0[ch]['x1']} adv={metrics[ch][0]}")
            if not changed:
                break
            fb.setupGlyf(glyph_dict)
            fb.setupHorizontalMetrics(metric_dict)
            fb.save(str(out))

    # ---- 校验：用渲染实测的墨迹量字距与字高 ----
    from fontTools.ttLib import TTFont
    ttf = TTFont(str(out))
    hmtx = ttf["hmtx"]
    ink = measure_ink(str(out), charset, upem=upem)

    seq = charset
    gaps = [hmtx[a][0] - ink[a]["x1"] + ink[b]["x0"] for a, b in zip(seq, seq[1:])]
    for c in charset:
        report[c]["rendered"] = dict(x0=ink[c]["x0"], x1=ink[c]["x1"],
                                     cap_height=ink[c]["top"], depth_below=ink[c]["bottom"])

    cap_heights = {c: ink[c]["top"] for c in charset}
    clean = [c for c in charset if not report[c]["size_anomaly"]]
    anomalies = [c for c in charset if report[c]["size_anomaly"]]
    heights = [cap_heights[c] for c in clean] or [cap_heights[c] for c in charset]

    gap_ok = (max(gaps) - min(gaps)) <= 8
    h_ok = (max(heights) - min(heights)) <= 2
    if gap_ok and h_ok:
        verdict = "PASS" + (f"（{len(anomalies)} 个带描点/长尾的字按原比例保留）" if anomalies else "")
    elif not gap_ok:
        verdict = "WARN 字距不一致"
    else:
        verdict = "WARN 字高不一致"

    lines = [
        f"family={args.family}  format={fmt}  glyphs={len(order)}  upem={upem}  "
        f"cap={args.cap}  gap={gap}  cmap={len(cmap)} 字符"
        + (f"（含 a–z → 大写映射）" if lower_map else ""),
        f"可见字距（渲染实测）: min={min(gaps)} max={max(gaps)} std={np.std(gaps):.2f} "
        f"(目标 {gap}；极差 {max(gaps) - min(gaps):.1f}/{upem} em = "
        f"{(max(gaps) - min(gaps)) / upem * 100:.2f}%，肉眼不可辨)",
        f"字高（基线以上渲染实测）: min={min(heights)} max={max(heights)} std={np.std(heights):.2f}"
        + (f"  （按原比例保留、未强制 =cap 的字：{''.join(anomalies)}）" if anomalies else ""),
        f"文件 {out.stat().st_size / 1024:.1f} KB",
    ]
    print("[build] " + "\n[build] ".join(lines))
    print(f"[build] 判定: {verdict}")

    (out.parent / "metrics.json").write_text(json.dumps(
        dict(family=args.family, format=fmt, upem=upem, cap=args.cap, gap_units=gap,
             charset=charset, cmap_size=len(cmap), lowercase_mapped=bool(lower_map),
             spacing=dict(min=min(gaps), max=max(gaps), std=float(np.std(gaps))),
             ink_heights=dict(min=min(heights), max=max(heights), std=float(np.std(heights)),
                              note="渲染实测的基线以上字高（cap_height），不含 Q/J 尾钩",
                              size_anomalies=anomalies),
             verdict=verdict, glyphs=report), ensure_ascii=False, indent=2))
    return 0 if verdict.startswith("PASS") else 2




def _translate_glyph(g, dx):
    """把一个简单字形整体横向平移 dx（字体单位），就地改坐标。"""
    if abs(dx) < 0.5 or g.numberOfContours == 0:
        return g
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    coords, ends, flags = g.getCoordinates(glyfTable=None)
    coords = GlyphCoordinates(coords)
    coords.translate((int(round(dx)), 0))
    g.coordinates = coords
    g.endPtsOfContours = ends
    g.flags = flags
    g.recalcBounds(None)
    return g


if __name__ == "__main__":
    sys.exit(main())
