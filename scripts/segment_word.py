#!/usr/bin/env python3
"""把一张「单行单词」图切成每字母一张 PNG（不靠 OCR，字母顺序由 --word 决定）。

用法:
  python3 segment_word.py --image 01_words/POLYMER/v2_attempt1.png --word POLYMER \
      --out 02_letters/POLYMER

产物:
  <out>/<序号>_<字母>.png   白底黑字、紧贴字形外框
  <out>/letters.json        word / 切分策略 / 每字母 bbox、像素宽高、墨量
                            + cap_px（字高基准）、baseline_y（基线）
切分策略按顺序尝试：连通块 → 列投影间隙 → 动态规划（连笔字）。
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


# ---------------------------------------------------------------- 基础工具
def otsu(gray: np.ndarray) -> int:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    hist = hist.astype(np.float64)
    total = hist.sum()
    omega = np.cumsum(hist)
    mu = np.cumsum(hist * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (total - omega)
    denom[denom == 0] = 1e-12
    sigma_b = (mu_t * omega - mu * total) ** 2 / denom
    return int(np.argmax(sigma_b))


def load_ink(path: Path, min_area_ratio: float = 0.0004):
    img = Image.open(path).convert("L")
    gray = np.asarray(img)
    thr = otsu(gray)
    ink = gray < thr
    if ink.mean() > 0.5:  # 反色图（白字黑底）
        ink = ~ink
    # 去噪：面积过小的连通块当斑点
    lab, n = ndimage.label(ink, structure=np.ones((3, 3), dtype=int))
    if n:
        areas = ndimage.sum(ink, lab, range(1, n + 1))
        keep = np.zeros(n + 1, dtype=bool)
        keep[1:] = areas >= max(4, min_area_ratio * ink.sum())
        ink = keep[lab]
    ys, xs = np.where(ink)
    if len(xs) == 0:
        raise SystemExit(f"[segment] {path} 里没有可识别墨迹")
    return ink[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1], (int(xs.min()), int(ys.min()))


def bbox_of(mask: np.ndarray):
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ---------------------------------------------------------------- 切分策略
def cut_by_components(ink: np.ndarray, n: int):
    lab, cnt = ndimage.label(ink, structure=np.ones((3, 3), dtype=int))
    if cnt != n:
        return None, f"components={cnt}≠{n}"
    boxes = []
    for i in range(1, cnt + 1):
        m = lab == i
        boxes.append(bbox_of(m))
    boxes.sort(key=lambda b: b[0])
    return boxes, f"components={cnt}"


def cut_by_projection(ink: np.ndarray, n: int):
    col = ink.sum(axis=0)
    gaps = []
    run = None
    for x, v in enumerate(col):
        if v == 0:
            run = x if run is None else run
        else:
            if run is not None:
                gaps.append((run, x))
                run = None
    if run is not None:
        gaps.append((run, len(col)))
    # 丢掉贴着左右边缘的间隙
    inner = [g for g in gaps if g[0] > 0 and g[1] < len(col)]
    if len(inner) != n - 1:
        return None, f"gaps={len(inner)}≠{n - 1}"
    cuts = [0] + [int((a + b) / 2) for a, b in inner] + [ink.shape[1]]
    boxes = []
    for i in range(n):
        sub = ink[:, cuts[i]: cuts[i + 1]]
        if sub.sum() == 0:
            return None, "投影切分切出了空列"
        x0, y0, x1, y1 = bbox_of(sub)
        boxes.append((cuts[i] + x0, y0, cuts[i] + x1, y1))
    return boxes, f"projection gaps={len(inner)}"


def cut_by_clusters(ink: np.ndarray, n: int):
    """装饰花体/断笔字：连通块比字母多（卷草、断针、描点各自成块）时，
    把连通块按 x 排序，在最大的 n-1 个水平空隙处合并成 n 组，每组当一个字母。
    """
    lab, cnt = ndimage.label(ink, structure=np.ones((3, 3), dtype=int))
    if cnt < n:
        return None, f"components={cnt}<{n}"
    boxes = []
    for i in range(1, cnt + 1):
        ys, xs = np.where(lab == i)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    boxes.sort(key=lambda b: b[0])
    gaps = []
    for i in range(len(boxes) - 1):
        gaps.append((boxes[i + 1][0] - boxes[i][2], i))
    if len(gaps) < n - 1:
        return None, "连通块太少，无法分组"
    gaps.sort(key=lambda t: (-t[0], t[1]))
    cut_after = sorted(i for _g, i in gaps[: n - 1])
    groups, cur = [], [boxes[0]]
    for i, b in enumerate(boxes[1:]):
        if i in cut_after:
            groups.append(cur)
            cur = [b]
        else:
            cur.append(b)
    groups.append(cur)
    if len(groups) != n:
        return None, f"分组数={len(groups)}≠{n}"
    out = []
    for g in groups:
        x0 = min(b[0] for b in g); y0 = min(b[1] for b in g)
        x1 = max(b[2] for b in g); y1 = max(b[3] for b in g)
        sub = ink[y0:y1, x0:x1]
        bx0, by0, bx1, by1 = bbox_of(sub)
        out.append((x0 + bx0, y0 + by0, x0 + bx1, y0 + by1))
    return out, f"clusters={len(groups)}/comps={cnt}"


def cut_by_dp(ink: np.ndarray, n: int):
    """连笔/粘连字：DP 找 n-1 个切点。
    代价 = 切点所在列墨量（越小越好，最好落在粘连的细颈处）
          + λ·(切点偏离等分位置)²  （防止全部挤到一边）
          + μ·(切出的字母宽度偏离均值)²
    """
    H, W = ink.shape
    if W < n + 2:
        return None, "图太窄"
    col = ink.sum(axis=0).astype(np.float64) / max(1.0, float(ink.sum(axis=0).max()))
    min_sep = max(2, int(0.30 * W / n))
    lam, mu = 5.0, 3.0
    mean_w = W / n

    # 切点 i（i=1..n-1）落在 x 处的代价
    C = np.full((n, W), np.inf)
    xs = np.arange(W)
    for i in range(1, n):
        exp = i * mean_w
        C[i] = col + lam * ((xs - exp) / mean_w) ** 2

    dp = np.full((n, W), np.inf)
    back = np.zeros((n, W), dtype=int)

    def best_prev(row, upto):
        """返回 row[0:upto+1] 的最小值与位置（含切点间隔与宽度惩罚）。"""
        seg = row[: upto + 1]
        if seg.size == 0 or not np.isfinite(seg).any():
            return np.inf, -1
        j = int(np.nanargmin(np.where(np.isfinite(seg), seg, np.inf)))
        return float(seg[j]), j

    for x in range(min_sep, W - (n - 1) * min_sep + 1):
        dp[1, x] = C[1, x] + mu * ((x - mean_w) / mean_w) ** 2

    for i in range(2, n):
        for x in range(i * min_sep, W - (n - i) * min_sep + 1):
            prev, j = best_prev(dp[i - 1] + mu * ((np.arange(W) - (i - 1) * mean_w) / mean_w) ** 2,
                                x - min_sep)
            if j < 0:
                continue
            dp[i, x] = prev + C[i, x]
            back[i, x] = j

    # 收尾：最后一个切点之后还要放得下最后一个字母
    tail = dp[n - 1] + mu * ((np.arange(W) - (n - 1) * mean_w) / mean_w) ** 2
    tail[W - min_sep:] = np.inf
    tail[: min_sep] = np.inf
    if not np.isfinite(tail).any():
        return None, "DP 无可行解"
    x = int(np.nanargmin(np.where(np.isfinite(tail), tail, np.inf)))
    cuts = [x]
    for i in range(n - 1, 1, -1):
        x = int(back[i, x])
        cuts.append(x)
    cuts = [0] + sorted(cuts) + [W]

    boxes = []
    for i in range(n):
        sub = ink[:, cuts[i]: cuts[i + 1]]
        if sub.sum() == 0:
            return None, "DP 切分切出了空列"
        x0, y0, x1, y1 = bbox_of(sub)
        boxes.append((cuts[i] + x0, y0, cuts[i] + x1, y1))
    return boxes, f"dp cuts={cuts}"


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--word", required=True, help="图上的单词（大小写按实际写法）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-area-ratio", type=float, default=0.0004)
    ap.add_argument("--strategy", default="auto",
                    choices=["auto", "components", "projection", "clusters", "dp"])
    args = ap.parse_args()

    src = Path(args.image)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    word = args.word
    chars = list(word)
    n = len(chars)

    ink, origin = load_ink(src, args.min_area_ratio)
    order = {
        "auto": [cut_by_components, cut_by_projection, cut_by_clusters, cut_by_dp],
        "components": [cut_by_components],
        "projection": [cut_by_projection],
        "clusters": [cut_by_clusters],
        "dp": [cut_by_dp],
    }[args.strategy]

    boxes, strategy, notes = None, None, []
    for fn in order:
        boxes, msg = fn(ink, n)
        notes.append(f"{fn.__name__}: {msg}")
        if boxes:
            strategy = fn.__name__.replace("cut_by_", "")
            break
    if boxes is None:
        raise SystemExit("[segment] 所有切分策略都失败：\n  " + "\n  ".join(notes))

    heights = [b[3] - b[1] for b in boxes]
    bottoms = [b[3] for b in boxes]
    cap_px = float(np.median(heights))
    baseline_y = float(np.median(bottoms))

    letters = []
    for i, (ch, b) in enumerate(zip(chars, boxes)):
        x0, y0, x1, y1 = b
        sub = ink[y0:y1, x0:x1]
        png = out / f"{i:02d}_{ch}.png"
        Image.fromarray(np.where(sub, 0, 255).astype(np.uint8)).save(png)
        letters.append(
            {
                "index": i,
                "char": ch,
                "file": png.name,
                "bbox": [int(x0), int(y0), int(x1), int(y1)],
                "width": int(x1 - x0),
                "height": int(y1 - y0),
                "ink": int(sub.sum()),
                "cap_ref": float(cap_px),
                "descender_px": round(float(y1 - baseline_y), 2),
            }
        )

    meta = {
        "word": word,
        "source_image": str(src.resolve()),
        "origin_in_source": list(origin),
        "strategy": strategy,
        "strategy_notes": notes,
        "page_size": [int(ink.shape[1]), int(ink.shape[0])],
        "cap_px": round(cap_px, 2),
        "baseline_y": round(baseline_y, 2),
        "letters": letters,
    }
    (out / "letters.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"[segment] {word} → {len(letters)} 个字母 / 策略 {strategy} / cap {cap_px:.1f}px")
    for l in letters:
        flag = "" if abs(l["height"] - cap_px) < 0.06 * cap_px else "  ← 高度异常"
        print(f"  {l['char']} {l['width']:>4}×{l['height']:<4} ink={l['ink']:>6}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
