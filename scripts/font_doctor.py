#!/usr/bin/env python3
"""font_doctor.py — 检查 TTF/OTF 为什么在 Adobe（Photoshop / Illustrator）里用不了。

用法:
  python3 font_doctor.py <字体文件...>          # 体检
  python3 font_doctor.py --fix-inplace <file>   # 只修 OS/2 + post + gasp + name（不改字形）

检查的都是 Adobe / Windows 真会卡的字段（fontTools FontBuilder 的默认值大多为 0，
不显式设置就会做出「PS 里看不到 / 用不了」的字体）：

  fsType           0 可安装 / 8 可编辑；2 禁止嵌入（PS 直接拒用）；4 仅预览打印（常被拒）
  fsSelection      Regular 必须置 bit6(0x40)；0 表示「无样式」，PS 认不出这套字体
  head.macStyle    要和 fsSelection 自洽
  ulCodePageRange  为 0 时部分 Adobe 版本认为字体不支持任何代码页 → 列表里灰掉
  ulUnicodeRange   至少 bit0(Basic Latin) + bit1(Latin-1)
  上下标/删除线尺寸  为 0 会被部分校验器判为坏字体
  name             必须有 1/2/4/6；6 只能 ASCII 无空格；2 要和 fsSelection 对应
  post              underlineThickness 为 0 时 PS 里下划线消失（视觉像坏字体）
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def check(path):
    f = TTFont(path, fontNumber=0, lazy=False)
    rows = []

    def add(level, item, detail, fix=""):
        rows.append((level, item, detail, fix))

    head, hhea, os2 = f["head"], f["hhea"], f["OS/2"]
    name, post = f["name"], f["post"]

    # --- fsType ---
    fs = os2.fsType
    if fs in (0, 8):
        add(OK, "OS/2.fsType", f"{fs}（0=可安装 / 8=可编辑）")
    elif fs == 2:
        add(FAIL, "OS/2.fsType", "2 = Restricted License（禁止嵌入）",
            "Adobe 会直接拒绝使用这个字体；改成 0")
    elif fs == 4:
        add(WARN, "OS/2.fsType", "4 = Preview & Print only",
            "很多 Adobe 版本把它当「只读预览」拒用；改成 0")
    else:
        add(WARN, "OS/2.fsType", f"{fs}（含嵌入限制位 {bin(fs)}）", "拉丁文字体一般应为 0")

    # --- fsSelection / macStyle ---
    sel = os2.fsSelection
    style_bits = {0x01: "ITALIC", 0x20: "BOLD", 0x40: "REGULAR"}
    have = [n for b, n in style_bits.items() if sel & b]
    mac = head.macStyle
    if not have:
        add(FAIL, "OS/2.fsSelection", "0x0000（没有任何样式位）",
            "Regular 必须置 bit6=0x40，否则 PS 认不出样式、字体列表里选不中")
    else:
        add(OK, "OS/2.fsSelection", f"{sel:#06x} " + "/".join(have))
    want_bold = bool(sel & 0x20)
    want_italic = bool(sel & 0x01)
    if bool(mac & 1) != want_bold or bool(mac & 2) != want_italic:
        add(WARN, "head.macStyle", f"{mac} 与 fsSelection 不一致", "让 bold/italic 位保持一致")
    else:
        add(OK, "head.macStyle", str(mac))

    # --- 代码页 / Unicode 范围 ---
    cp1 = getattr(os2, "ulCodePageRange1", 0)
    cp2 = getattr(os2, "ulCodePageRange2", 0)
    if cp1 == 0 and cp2 == 0:
        add(FAIL, "OS/2.ulCodePageRange", "全 0（无任何代码页）",
            "拉丁字体至少置 bit0(1252)：ulCodePageRange1 |= 1")
    elif not cp1 & 1:
        add(WARN, "OS/2.ulCodePageRange1", f"{cp1:#010x} 缺 Latin-1(bit0)", "ulCodePageRange1 |= 1")
    else:
        add(OK, "OS/2.ulCodePageRange", f"{cp1:#010x} / {cp2:#010x}")

    ur1 = os2.ulUnicodeRange1
    if not ur1 & 0x3:
        add(WARN, "OS/2.ulUnicodeRange1", f"{ur1:#010x}", "A–Z/0–9 至少置 bit0+bit1 = 0x3")
    else:
        add(OK, "OS/2.ulUnicodeRange1", f"{ur1:#010x}")

    # --- 上下标 / 删除线尺寸 ---
    zero_subs = [k for k in ("ySubscriptXSize", "ySubscriptYSize", "ySuperscriptXSize",
                             "ySuperscriptYSize", "yStrikeoutSize") if getattr(os2, k) == 0]
    if zero_subs:
        add(WARN, "OS/2 上下标/删除线尺寸", "为 0: " + ",".join(zero_subs),
            "按 upem 比例给值（1000/em 时：下标 650×600，上标 650×600，删除线 50）")
    else:
        add(OK, "OS/2 上下标/删除线尺寸", "非零")

    if os2.sTypoAscender == 0 or os2.sTypoDescender == 0 or os2.usWinAscent == 0:
        add(FAIL, "OS/2 垂直度量", f"typoAsc={os2.sTypoAscender} typoDesc={os2.sTypoDescender} winAsc={os2.usWinAscent}",
            "必须是实际值，否则 PS/AI 里行高错乱甚至不显示")
    else:
        add(OK, "OS/2 垂直度量", f"typo {os2.sTypoAscender}/{os2.sTypoDescender}, win {os2.usWinAscent}/{os2.usWinDescent}")

    # --- name ---
    def get(nid):
        for rec in name.names:
            if rec.nameID == nid and rec.platformID == 3:
                try:
                    return rec.toUnicode()
                except Exception:
                    return None
        return None

    missing = [nid for nid in (1, 2, 4, 6) if not get(nid)]
    if missing:
        add(FAIL, "name 表", f"缺 nameID {missing}", "至少要有 1/2/4/6 四个记录")
    else:
        add(OK, "name 表", f"family={get(1)!r} style={get(2)!r} ps={get(6)!r}")
    ps = get(6) or ""
    if len(ps) > 63 or not ps.isascii() or " " in ps:
        add(FAIL, "name ID6（PS 名）", repr(ps), "≤63 字节、纯 ASCII、不能有空格")
    style_name = (get(2) or "").lower()
    if style_name == "regular" and not sel & 0x40:
        add(FAIL, "style 与 fsSelection 冲突", 'styleName="Regular" 但没置 REGULAR 位',
            "fsSelection |= 0x40")

    # --- post ---
    if post.formatType not in (2.0, 3.0):
        add(WARN, "post.formatType", f"{post.formatType}", "用 2.0 或 3.0")
    thick = getattr(post, "underlineThickness", 0)
    if thick in (0, None):
        add(WARN, "post.underlineThickness", "0", "设为 upem/20（1000/em 时 50），否则下划线看不见")
    else:
        add(OK, "post", f"format={post.formatType} underline={getattr(post,'underlinePosition',None)}/{thick}")

    # --- hmtx / hhea ---
    n_glyphs = f["maxp"].numGlyphs
    if hhea.numberOfHMetrics not in (n_glyphs, 1):
        add(WARN, "hhea.numberOfHMetrics", str(hhea.numberOfHMetrics), f"应为 {n_glyphs}")
    else:
        add(OK, "hhea.numberOfHMetrics", str(hhea.numberOfHMetrics))

    # --- cmap ---
    has_win_unicode = any(t.platformID == 3 and t.platEncID in (1, 10) for t in f["cmap"].tables)
    add(OK if has_win_unicode else FAIL, "cmap", str([(t.platformID, t.platEncID, t.format) for t in f["cmap"].tables]),
        "" if has_win_unicode else "缺 (3,1) Windows Unicode 子表")

    # --- gasp（屏幕渲染提示，缺了不致命） ---
    if "gasp" not in f:
        add(WARN, "gasp", "缺失", "Adobe/Windows 小字号渲染会偏；建议补一个 gasp")

    # --- 轮廓表（TTF=glyf / OTF=CFF）---
    if "glyf" not in f:
        has_cff = "CFF " in f or "CFF2" in f
        add(OK if has_cff else FAIL, "轮廓表", "CFF（OTF/三次曲线）" if has_cff else "既没有 glyf 也没有 CFF",
            "" if has_cff else "字体没有可用轮廓表")
        add(OK if "CFF " in f else WARN, "格式", "OTF/CFF（Adobe 原生，兼容性最好）" if "CFF " in f else "TTF/glyf")
        return rows, f

    glyf = f["glyf"]
    xs = [(glyf[g].xMin, glyf[g].xMax) for g in f.getGlyphOrder() if glyf[g].numberOfContours > 0]
    ys = [(glyf[g].yMin, glyf[g].yMax) for g in f.getGlyphOrder() if glyf[g].numberOfContours > 0]
    if xs:
        real = (min(a for a, _ in xs), min(a for a, _ in ys), max(b for _, b in xs), max(b for _, b in ys))
        stored = (head.xMin, head.yMin, head.xMax, head.yMax)
        if real != stored:
            add(WARN, "head bbox", f"存的 {stored} ≠ 实际 {real}", "用 recalcBBoxes 或手动写一致")
        else:
            add(OK, "head bbox", str(stored))

    return rows, f


def print_report(path):
    rows, f = check(path)
    print("=" * 78)
    print(f"{path}")
    print(f"  family={f['name'].getDebugName(1)!r} style={f['name'].getDebugName(2)!r} "
          f"glyphs={f['maxp'].numGlyphs} upem={f['head'].unitsPerEm}")
    bad = 0
    for level, item, detail, fix in rows:
        mark = {"OK  ": "✓", "WARN": "!", "FAIL": "✗"}[level]
        print(f"  {mark} {item:<28} {detail}")
        if fix and level != OK:
            print(f"      → {fix}")
        if level == FAIL:
            bad += 1
    print(f"  结论: {'可以在 Adobe 里用' if bad == 0 else f'{bad} 项致命问题，PS/AI 里会用不了或认不出'}")
    return bad


def fix_inplace(path):
    """只补齐 Adobe 需要的元数据，不动字形。"""
    f = TTFont(path, fontNumber=0, lazy=False)
    os2, head, post = f["OS/2"], f["head"], f["post"]
    upem = head.unitsPerEm
    sel = os2.fsSelection or 0
    upem_scale = upem / 1000

    os2.fsType = 0
    if not sel & 0x71:            # 没有任何样式位 → Regular
        sel |= 0x40
    os2.fsSelection = sel
    head.macStyle = (1 if sel & 0x20 else 0) | (2 if sel & 0x01 else 0)
    os2.ulCodePageRange1 |= 0x1   # Latin-1 (1252)
    os2.ulUnicodeRange1 |= 0x3    # Basic Latin + Latin-1 Supplement
    os2.ySubscriptXSize = int(650 * upem_scale)
    os2.ySubscriptYSize = int(600 * upem_scale)
    os2.ySubscriptYOffset = int(75 * upem_scale)
    os2.ySuperscriptXSize = int(650 * upem_scale)
    os2.ySuperscriptYSize = int(600 * upem_scale)
    os2.ySuperscriptYOffset = int(350 * upem_scale)
    os2.yStrikeoutSize = int(50 * upem_scale)
    os2.yStrikeoutPosition = int(250 * upem_scale)
    os2.sFamilyClass = 0
    os2.achVendID = "NONE"
    if os2.sxHeight == 0:
        os2.sxHeight = int(520 * upem_scale)
    if os2.sCapHeight == 0:
        os2.sCapHeight = int(700 * upem_scale)
    post.underlinePosition = int(-100 * upem_scale)
    post.underlineThickness = int(50 * upem_scale)

    # gasp：小字号平滑
    if "gasp" not in f:
        from fontTools.ttLib import newTable
        g = newTable("gasp")
        g.version = 1
        g.gaspRange = {8: 0x000A, 0xFFFF: 0x000A}   # 全尺寸对称平滑 + 栅格化
        f["gasp"] = g

    f.save(path)
    print(f"已修（字形未动）: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fonts", nargs="+")
    ap.add_argument("--fix-inplace", action="store_true")
    args = ap.parse_args()
    bad_total = 0
    for p in args.fonts:
        path = Path(p)
        if not path.exists():
            print(f"跳过（不存在）: {p}")
            continue
        if args.fix_inplace:
            fix_inplace(str(path))
        bad_total += print_report(str(path))
    return 0 if bad_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
