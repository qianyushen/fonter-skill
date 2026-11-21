# 字体预览海报规范（Specimen poster）

对标用户的参考样张：深色底 + 撞色字，上半是词组（大字），中间一条细分隔线，
下半是 A–Z（及数字）的整齐网格。全部由 `scripts/make_specimen.py` 渲染，
**不要拿生图模型画海报**——生图模型会把字母画错，海报必须是真字体的渲染结果。

## 1. 版式（1688×2113，比例固定）

| 区块 | 位置 | 要求 |
| --- | --- | --- |
| 两个词 | 顶部 ~7%–40% 高度 | 两个词各一行；整体水平居中；超宽时整行缩到 ≤84% 画宽 |
| 一句标语 | 词下方 ~44% 高度 | 单行、居中、**用字体本身排**；自动从 35 句池按字体名抽；超宽自动缩字号 |
| 分割线 | ~54.5% 高度 | **通栏**，颜色 = 字体颜色，粗细 = 画面高的 0.6% |
| 字符网格 | 54.5% 以下 | 单大小写：固定 6–8 列 × 5 行；大小写都有：13 格/行；格子等宽；末行不足则居中；字按墨迹高度归一化 |

网格规则：

- **每个字母/数字墨迹高度完全一致**（`ink_h` 由「行高」和「最宽字不能溢出格」共同决定，
  所有字共用同一个 `ink_h`）。脚本输出 `ink_heights_unique`，唯一值 ≤2 种才算过。
- 行数由**实际字符集**决定，目标是**把下半块填满**（海报尺寸固定 1688×2113）：
  - 只有一种大小写（最常见：只有大写）→ **5 行**，字母（+数字）合成一条流：
    列数 = `ceil(字数 / 5)`（26 个 → 6 列、26+10 个 → 8 列），前几行**排满、宽度一致**，
    剩下的字放最后一行并**水平居中**（26 个 → A–F / G–L / M–R / S–X / Y Z；
    36 个 → A–H / I–P / Q–X / Y–Z0–5 / 6–9）。
    **不要**均分成 6/5/5/5/5：那样最后一行比上面宽半个格，右边缘会戳出一个字（已踩过）。
  - 大小写都有 → 大写 2 行（13+13）+ 小写 2 行（13+13）+ 数字 1 行（10 个居中）。
  - 字数太少（<10）自动降行数，不会硬凑 5 行把字摊开。
  - `--grid-rows 2` 可强制旧版两行效果（对照用）。
- 只有「小写字符映射到与大写同一个 glyph」的镜像小写**不重复排**（脚本自动判断）。
- 没有小写字形就不要出现小写格；没有数字就不要出现数字行。

## 2. 潘通撞色表（高饱和版，共 115 套，色值固定，别手调）

原则：底色深/浓、字色亮/纯，**明度差 ≥45%**（扩展库全部 ≥51%）；两色在色相上尽量拉开（撞色），
不要出现「深蓝 + 深灰」这种同明度组合。

分两层：

1. **15 套经典款**（下面这张表，手工命名，`--palette forest` 这种短名调用）。
2. **100 套扩展库**（`scripts/make_specimen.py` 里的 `PALETTES`，名字是「底色_字色」，
   如 `deep_teal_prism_pink` / `burgundy_icy_blue`）：Pantone TCX 双色配对，
   约束是「亮度差 ≥51%、色相拉开、同一底色最多配 4 种字色、同一字色最多用 6 次」，
   所以任意两套拿出来都不会看着像同一张。要加新的就顺着这个约束往表里加，
   别手工随手写两个 hex。

| 名字 | 底色 | 字色 | PANTONE |
| --- | --- | --- | --- |
| `forest` | `#05402A` | `#F7EE9C` | 19-5411 Forest Biome / 12-0736 Lemon |
| `lime` | `#0A3D1B` | `#C6FF33` | 18-0332 Grass Green / 13-0550 Lime Punch |
| `classic_blue` | `#0A4EA8` | `#FFD233` | 19-4052 Classic Blue / 13-0755 Primrose Yellow |
| `ultraviolet` | `#4A2B96` | `#FFE14D` | 18-3838 Ultra Violet / 13-0755 Primrose Yellow |
| `fiery` | `#D8142F` | `#FFF4DC` | 18-1664 Fiery Red / 11-0601 Bright White |
| `iris` | `#191B4D` | `#FFD400` | 19-3921 Black Iris / 13-0858 Vibrant Yellow |
| `emerald` | `#00795C` | `#FFB01F` | 17-5641 Emerald / 15-0960 Golden Apricot |
| `coral` | `#FF6F5E` | `#0B2D8F` | 16-1546 Living Coral / 19-4052 Classic Blue |
| `tangerine` | `#FF5A1F` | `#0B1B4A` | 17-1463 Tangerine / 19-4023 Total Eclipse |
| `ink` | `#0D1C4A` | `#FF3B30` | 19-4220 Dark Slate / 18-1664 Fiery Red |
| `greenery` | `#6FBF23` | `#0B1B4A` | 15-0343 Greenery / 19-4023 Total Eclipse |
| `marsala` | `#8E2B35` | `#FFE1A8` | 18-1438 Marsala / 12-0712 Vanilla Ice |
| `serenity` | `#7FB3FF` | `#0B1B4A` | 15-3919 Serenity / 19-4110 Midnight Navy |
| `magenta` | `#C2006B` | `#FFE94A` | 17-2031 Fuchsia Rose / 13-0755 Primrose Yellow |
| `electric` | `#00C2D1` | `#0A0A2A` | 16-4529 Cyan Blue / 19-4005 Stretch Limo |

## 3. 风格 → 配色（从字体气质出发选撞色）

| `--style` | 优先配色（依次） | 典型字体 |
| --- | --- | --- |
| `geometric` | forest → classic_blue → iris | 几何无衬线、字腔方整 |
| `minimal` | classic_blue → forest → serenity | 细笔、极简 |
| `bold` / `heavy` | fiery → tangerine → magenta | 超粗黑体、块面字 |
| `blob` | ultraviolet → magenta → greenery | 液态、黏液、融边 |
| `organic` | ultraviolet → emerald → marsala | 手绘不规则 |
| `blackletter` / `ornate` | fiery → iris → magenta | 哥特、卷草花体 |
| `brush` | tangerine → magenta → fiery | 马克笔、涂鸦 |
| `graffiti` | tangerine → electric → greenery | 街头喷漆 |
| `script` | ultraviolet → marsala → coral | 手写连笔 |
| `rounded` | coral → greenery → electric | 圆体 |
| `tech` | electric → iris → classic_blue | 科技感硬边 |

`--style auto` 时脚本按墨迹覆盖率判：>0.46 → bold，<0.24 → minimal，其余 → geometric。

**auto 选色怎么走**（重要，2026-11 修过一次真事故）：

- `--palette auto` → 先取「该风格的首选 + 所有底色色相落在该风格区间的扩展色」组成池子（几十套），
  再按 `字体名 + style + seed + 已用历史` 散列挑一套，并**避开最近用过的 12 套**
  （历史文件 `~/.fonter/palette_history.json`，环境变量 `FONTER_PALETTE_HISTORY` 可改）。
- 以前是 `STYLE_PALETTES[style][seed % 3]`，`--seed` 默认 0 → **同风格永远是第一顺位那套**，
  结果连着做两套哥特都是「红底白字」。现在同一风格连着做也不会撞色。
- `--palette all` 会把 115 套各出一张（文件名后缀 `_<palette>`），只在用户要挑色时才用。

## 4. 词组与标语（每套字体重新抽）

海报上半是**两个单词竖排两行 + 下方一句标语**，都用成品字体本身排。规则：

- 不给 `--word` → 脚本用 `pick_two_words(字体名, seed)` 从 100+ 单词池抽**两个不同的词**；
  同一字体同一 seed 结果固定，不同字体必然不同；运行时会打印抽到的两个词。
- 标语不给 `--sentence` 时用 `pick_sentence(字体名, seed)` 从 35 句池抽一句（如
  `GET RICH OR DIE TRYIN` / `RUN IT BACK AGAIN` / `BORN FROM THE ASPHALT`）；
  字体没有小写字形就自动转大写。
- 要换：`--seed 3` 同时换词和句；`--word "NOISE FIELD"` / `--sentence "KEEP IT LOUD"` 单独指定。
- **每套字体都要重新出一次**：不许复用上一套的 `specimen.png`，也不许四套共用同一对词/同一句。
- 抽到的词与句写进 `05_preview/specimen.json` 的 `words` / `sentence` 字段和 `build_log.md`。

## 5. 自检（每次出图都要过）

1. `specimen.json` 的 `verdict` = `PASS`（网格字高唯一值 ≤2）；
   `grid.rows` 在「只有一种大小写」时必须是 **5**，`grid.row_characters` 逐行拼起来等于实际字符集。
2. `top_spacing[].ink_gap_min == ink_gap_max`（词组字距一致）。
3. `text_check.png`（`PIL` 渲染「THESE GLYPHS 0123456789」两行）里字距均匀、无裁断。
4. 把海报给用户看；配色/词组/档位不满意就换 `--palette` / `--word` / `--seed` 重出，
   但**不要**手改海报里的字号去掩盖字体本身的大小不齐。
