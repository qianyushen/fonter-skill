---
name: fonter
description: >-
  Turn one hand-lettered reference — a whole word ("happy", "atom flow") or a single letter ("N") — into an installable TTF/OTF font covering A–Z / a–z (optional 0–9), then render a Pantone-contrast preview poster and an optional real-material render. Use when the user wants a typeface built from a wordmark, lettering, logo or a hand-drawn glyph: plan the words that cover the alphabet, generate them with the image model, segment each letter, vectorize, equalise cap height and side bearings, assemble and validate the font, then package font + poster.
metadata:
  short-description: 从单词/单字母参考图做整套 TTF/OTF 字体（含潘通撞色预览海报与可选材质渲染图） · Build an installable TTF/OTF font from a wordmark or letterform, with specimen poster and optional material render
---

# 从单词参考图做字体（Font from Wordmark）

把一张「一个单词」的手写字型图，扩展成一套覆盖 A–Z / a–z 的字体文件。
字形的唯一真值是用户给的参考图；全程不许重新设计风格，只做「同一套骨架的延展」。

## 0. 项目目录与内置脚本

所有产物放在用户指定的项目目录，默认 `~/Desktop/fontskill/projects/<参考词slug>/`：

```
00_reference/   reference.png（平面化参考）, reference_flat.png, 处理说明
01_words/       每个覆盖词的生成图 + 采用记录
02_letters/     切割出的字母 PNG + letters.json（含 cap_px / baseline_y）
03_vector/      可选：单个字母的 SVG 调试输出
04_font/        *.ttf / *.otf + metrics.json（字距/字高校验结论）
05_preview/     specimen.png（预览海报）+ specimen.json + text_check.png
06_art/         材质渲染图 <Family>_<material>.png + materials.json（可选，用户点头才做）
build_log.md    全程日志：每轮提示词、采用/弃用原因、用户确认点、重试次数
```

**内置脚本（本 skill 自带，不要临时改写成一次性代码）**：

| 脚本 | 作用 |
| --- | --- |
| `scripts/segment_word.py` | 单行单词图 → 每字母 PNG + `letters.json`（连通块 / 列投影 / DP 三种切分） |
| `scripts/build_family.py` | **交付入口**：一次出 TTF + OTF，并各跑一遍 Adobe 体检 |
| `scripts/build_font.py` | 字母 PNG → potrace 轮廓 → 规范化字高与边距 → 单个 `.ttf` / `.otf` + `metrics.json` |
| `scripts/make_specimen.py` | 成品字体 → 高饱和潘通撞色预览海报（上两个词 / 下等大网格，单大小写排 5 行；115 套配色） |
| `scripts/render_material.py` | 预览海报 → 真实**材质渲染图**（图生图，走 codex `image_gen`；材质搭配不内置，由 agent 随机或用户指定后传入） |
| `scripts/check_env.py` | 一条命令确认这台机器能不能直接跑（Python + 5 个依赖 + codex） |
| `scripts/font_doctor.py` | 体检「为什么在 PS/AI 里用不了」；`--fix-inplace` 可原地补齐 Adobe 必需字段（不改字形） |

依赖：`pillow numpy scipy fonttools potracer`（`pip install potracer`）。

### 0b. 出图工具

| 用途 | 工具 / 模型 | 怎么调 |
| --- | --- | --- |
| 生成单词图（`01_words/`） | codex 内置 `image_gen`（gptimage 2.5） | `codex exec -i 参考图.png …`（见 §9b） |
| 材质渲染图（`06_art/`） | 同上，图生图 | `python3 scripts/render_material.py --project … --material "…"`（见 §10b） |

铁律：**一个单词一次调用、参考图当唯一字形依据、不许重新设计**。
切分/组字/海报/体检脚本全部离线，跟模型无关。

`build_log.md` 是硬要求：用户要能据此回溯「哪个字母来自哪个词、用第几版提示词」。

## 1. 参考图闸门（Flatten gate）

先判断用户给的是**平面图**还是**手写草稿**；参考图可以是**一个单词**，也可以是**单个字母**
（单个字母走 §2b 单字母模式）。

- 已经是平面图（白底、纯黑字形、单一单词、无阴影/渐变/照片质感）→ 直接复制为
  `00_reference/reference.png`，只做体检并报告：背景/字形对比、大致字数、字形是否粘连，
  **不要改图**。
- 是草稿/照片/截图（纸纹、阴影、透视、彩色、灰度不均）→ 先平面化：
  灰度 → Otsu 或自适应阈值 → 去掉背景噪点 → 只保留纯黑字形 + 纯白背景 →
  轻微纠偏/裁切到字形外框 → 存 `reference_flat.png`。
  - 保留原文件不动，所有处理输出新文件。
  - 把平面化结果**给用户看，等确认**；不满意就调参数重做，直到用户点头。
  - 只有平面化结果被确认后才进入下一步。

参考图的字母集合要记录（大小写按图上的实际写法），后面所有提示词都要用它做锚点。

## 2. 拟覆盖词（Word plan）

目标：用 5–7 个单词覆盖目标字母集；**每个单词里尽量含 1–3 个参考图里已有的字母**，
让模型有可直接复用的锚定字形，风格一致性明显更好。

规则：

- 目标字母集：用户选「只要大写」→ A–Z；「只要小写」→ a–z；「都要」→ 大小写各一套。
- **数字单独问、单独排**：默认不让生图模型画数字（它画数字比画字母更容易错、也更容易把「0」画成「O」）。
  需要数字时另起一张图，整行 `0123456789` 一次生成，切完跟字母用同一套边距规则（可见间距恒定）。
- 一套「A–Z + 0–9」的通用覆盖词表（26 字母全覆盖、单词内不重复字母，做批量对比时可直接复用）：
  `VAMPIRE / JOCKEYS / QUARTZ / HOWLING / BOXED / FJORD` + 数字行 `0123456789`。
- 单词长度 4–8 个字母；尽量不重复字母（同一字母在一张图里出现两次容易只抄对一个）。
- 单词要真实、常见、易辨认；避免专用名词和易混字母堆叠（如 rn / cl / vv）。
- 难字母（Q、X、Z、J、K、V、G）优先放在**含锚定字母**的词里，别单独成词。
- 输出一张表交给用户确认：

  | 顺序 | 单词 | 字母 | 复用的参考字母 | 新造字母 |
  |---|---|---|---|---|
  | 1 | TAKE | T A K E | t a | k e |

用户确认后再生成；如果用户说「直接开始」，就用最优方案继续。

## 2b. 单字母参考模式（Single-letter mode）

参考图里只有一个字母（用户常拿来先试探风格是否做得出来）时，**锚点只有 1 个字母，风格信息
不足以直接排满 A–Z**。此时不要直接铺开全部单词，先做一批「风格试探」，交给用户审。

做法：

1. 挑 3–5 个真实、常见、4–7 字母、**都含这个字母**的单词；让它在批次里出现于词首 / 词中 /
   词尾（位置不同会暴露模型对这个字母的误解）。顺带把难字母（Q X Z J K V W G）塞进这批词里，
   避免后面重复生成。
2. 每个词用 v2 提示词生成一张，提示词里必须写清楚：
   - 参考图**只有这一个字母**，其余字母必须由它的骨架派生；
   - 把这个字母的形状特征描述到可执行（例：棘刺状尖角、笔画末端拖出细尖、重心偏高、字宽比…），
     因为单字母提供不了整体风格统计量。
3. 出 `05_preview/probe_review.png` 对比大图（每词标注目标单词 + 提示词版本 + 采用/弃用），
   并逐词逐字母写审计意见，然后**停下来等用户确认**。
4. 用户认可 → 这批词**直接作为正式覆盖词表的一部分**（不浪费），再补齐剩余字母，进入 §4 之后
   的常规流程。
5. 用户不认可 → 换一个提示词版本重做试探批次（同一批词最多 3 轮）；如果 3 轮都不行，说明这个
   单字母不足以定义风格，把结论摆给用户：要么补一张整词参考图，要么先确定这个字母的标准写法。
6. 每轮的提示词版本、取舍、用户意见都写进 `build_log.md`。

单字母模式下的覆盖词表要额外保证：该参考字母的每一种位置（词首/词中/词尾）至少出现一次，
方便后续从多个来源里挑最像参考图的那一份。

## 3. 生成（Generation）

用内置 `image_gen` 工具，**每个单词一次调用**，把参考图作为 edit/参考输入，只输出一张单行单词图（`codex exec -i 参考图.png` → 见 §9b）。

- **首轮统一使用 v2 提示词（逐字母对照表）**，模板见 `references/prompts.md`。
  v2 的要点：把每个字母单独列一行 —— 参考图里有的写「直接取用、逐笔照抄、不重绘」，
  没有的写「按同一套骨架新造」。
- 每次调用都要带上硬约束块：保留原字型（笔触/粗细/倾斜/终端/字距）、纯黑字+纯白底、
  单行横排、不要任何其他文字与水印。
- 存 `01_words/<word>/v2_attempt1.png`，在 `build_log.md` 记下：词、提示词版本、字符数、
  文件名、时间。
- 一旦有一批被用户认可的图，后续生成可以把**参考图 + 1~3 张已采用的词图**一起作为风格参照
  （不只给原参考），跨字母的风格一致性会明显变好；日志里记明这一次引用哪几张。

## 4. 分割前确认闸门（Review gate）

**必须**在切割前让用户看图：

- 生成一张带标注的对比大图 `05_preview/words_review.png`：每个词一行，标注「目标单词 / 提示词版本 / 采用或弃用」。
- 用文字逐词报告：这个词的字形是否延续了参考图风格、字母是否可辨认、有无被改成别的字母/多字少字。
  「看起来没问题」不算审计——要按字母点名（例：FROCK 的 F 端部切角一致，C 偏圆）。
- 等用户确认。

某个字母效果不好时：**只重生该单词**，并且**换一个提示词版本**（v1/v3/v4/v5 轮换，禁止原样重发
v2 提示词）；同一个词最多重生 3 次，仍不行就把备选方案和取舍摆给用户选。
每轮记进 `build_log.md`（第几轮、用了哪版提示词、为什么弃用）。

## 5. 分割（Segmentation）

已知单词内容，所以**不需要 OCR**：只需把图按顺序切成 `len(word)` 段。

1. 二值化：灰度 + Otsu；字形=暗色。若暗色像素超过一半，说明是反色图，取反。
2. 去噪：去掉面积小于墨迹总量 0.015% 的连通块（斑点、飞白碎屑）。
3. 裁到字形外框，记录 `top / bottom / baseline / cap_height`。
4. 切分策略按顺序尝试，命中即停：
   - **连通块**：连通块数量恰好等于字母数 → 用连通块外框（大多数字母独立时走这条）。
   - **列投影间隙**：内部「零墨」间隙恰好 n−1 个 → 在间隙中心切。
   - **动态规划切分**：字形连笔（手写/连笔字常见）时用 —— 目标边界按各字母相对字宽的
     累积比例估计，代价 = 切点所在列的墨量（越小越好）+ 偏离期望位置的惩罚；
     切完在 ±8px 内微调到局部最小墨量列。
   - 兜底：等分，并在报告里标注「切分不可靠」。
5. 陷阱：`i / j` 的点、断笔、装饰会产生多余连通块（按 x 范围合并）；**尖刺/飞白风格里被切开的细尾、
   断针要按「最近的所属字母」归回**，不要当噪点丢掉，也不要单独成字；连笔字没有零间隙，
   必须走 DP；字母 `I / L` 很窄，切偏会切到邻居，切完要检查每个字母的墨量是否合理。

输出：

```
02_letters/<word>/<序号>_<字母>.png   白底黑字单字母
02_letters/<word>/letters.json        word / 每个字母的 bbox、像素宽高、墨量、切分策略
```

`letters.json` 里要保留 `source_word` 和 `prompt_version`，方便后面追溯字形来源。

## 6. 大小写 / 数字闸门（Case & digits gate）

切割前后都问一次（默认在生成前问，避免白花生成额度）：

- 只做大写 / 只做小写 / 大小写都要。
- **要不要数字 0–9？（必须在生成前问用户）** 数字多一次生成 + 一次切分，并决定预览海报下半部分
  是「A–Z」还是「A–Z + 0123456789」。问清楚四种组合：只大写 / 大写+数字 / 小写+数字 / 大小写+数字。
  用户说要数字 → 海报网格就必须排上数字那一行；说不要 → 一行都不许出现。
  用户没明确要求就默认**不做数字**（省一次生成，样式也不容易跑偏）。
- 预览海报的网格必须**如实反映已覆盖的字符集**：只要大写就排 A–Z；大写+数字就把 0–9 接在字母流后面；
  大小写都要就两套都排 + 数字一行。不要在没有小写字形时把大写塞进小写格。
- **只有一种大小写时（最常见：只有大写）下半必须排成 5 行**（26 个字 → 6 列 × 5 行，
  大字+数字 36 个 → 8 列 × 5 行）：海报尺寸固定，两行 A–Z 会在下半留出大片空白、字母也被挤小。
- 生成成本大约是「只要一种」的 1 倍、「都要」的 2 倍，把这点告诉用户。
- 只有一种时，另一种的 cmap 怎么处理要问：**不映射**（系统回退到别的字体）还是
  **映射到同形**（小写输入也显示大写字形）。默认不映射，除非用户要。

## 7. 组装字母表

把切出的字母按字符归档，同名多份时挑最优（看边缘干净/笔形完整/与其他字母的粗细一致），
其余留作备选。输出 `05_preview/letters_grid.png`：26 格（或所选子集）网格，
每格标注「字母 + 来自哪个词」，缺字母的格子标红。

报告「只有一个来源」的字母（无法交叉校验）和「风格可疑」的字母，让用户决定是否补生成。

## 8. 矢量化（Vectorize）

`scripts/build_font.py` 里已包含这一步（potrace 纯 Python 版 `potracer`）。要点：

- 二值图 → 轮廓：potrace（`pip install potracer`，纯 Python 版 potrace；
  或系统里有 `potrace` 就用 CLI）。参数：`turdsize≈2` 去小噪点，`alphamax≈1.0`，
  开启曲线优化；字形轮廓要保留内外环（对应洞，如 O、A、B 的封闭空间）。
- **极性必须验证**：potrace 把布尔数组里的 `True`（或暗值）当墨，传反了会得到反白块。
  矢量化后先渲染一张字形轮廓图看是实心字还是反白，再继续；不要等字体生成完才发现。
- 归一化到字体坐标：`unitsPerEm = 1000`，基线 y=0，大写高度约 700（小写 x-height 按参考图
  实测比例缩放），按每个字母在图里的原始宽高比缩放，横向不要拉伸变形。
- 左右边距（side bearing）由参考图里字与字的实际间距推算；连笔风格取小值（约 40–60），
  宽字取略大值。同一套字体用同一套规则，保证字距均匀。
- TrueType 用二次贝塞尔：用 `fontTools.pens.cu2quPen` 把 potrace 的三次曲线转二次。
  自建 CFF/OTF 时保留三次曲线。

## 9. 打包字体（Build）

**首选一次出两种格式**（矢量化 + 度量规范化 + 打包 + Adobe 体检一条龙）：

```bash
python3 scripts/build_family.py \
  --sources 02_letters/VAMPIRE 02_letters/JOCKEYS 02_letters/QUARTZ \
            02_letters/HOWLING 02_letters/BOXED 02_letters/FJORD \
            02_letters/digits_0123456789 \
  --family POLYMER --out-dir 04_font --charset A-Z,0-9
#   → 04_font/POLYMER.ttf（glyf 二次曲线）+ 04_font/POLYMER.otf（CFF 三次曲线）
#   → 两个文件各跑 font_doctor.py，结论都必须是「可以在 Adobe 里用」
#   --gap 120   相邻字母的墨迹间隙（字体单位，1000/em），太松改小
#   --cap 700   字高；所有字母/数字强制归一到这个高度
```

**两种格式都要交，各有各的场合**：

| 格式 | 内部 | 适合 | 备注 |
| --- | --- | --- | --- |
| `.ttf` | `glyf` + 二次曲线（Cu2Qu 近似） | 系统、Office、网页、Android、Windows | 通用性最好 |
| `.otf` | CFF + **三次曲线（不近似）** | Adobe（PS/AI）、印刷、macOS | 字形更准、体积更小；TTF 在某版 PS 出问题时的兜底 |

单独控制某一种格式时才用 `build_font.py`（`--out x.ttf` / `--out x.otf`）。
**同一家族不要同时装进系统**——两个文件 family/PS 名相同，PS 会判重名「不可用」；给用户两份，让他挑一种装。

脚本会把两件事锁进 ttf：

1. **字母等大**：每个词的 `cap_px` 先量出来，整词同比例缩放到 `cap`；跨词因此也一致。
   基线取该词所有字母底边的中位数，所以 `Q/J` 的尾、花体的卷草会自然落到基线以下，不会被压小。
2. **字距等距**：左右边距都等于 `gap/2`，`advance = 墨迹宽 + gap`，所以任意相邻两字母的
   **可见间隙恒等于 `gap`，字母和数字一视同仁**。数字默认走比例宽（跟字母同一套规则）；
   只有在用户明确要「表格里数字对齐」时才加 `--tabular-digits`（代价是数字之间会多出空隙）。

跑完必须看结尾三行：`可见字距 min/max/std`、`字高 min/max/std`、`判定: PASS`。

**打完包必须再跑一次字体体检**（Adobe 用不了 99% 是 OS/2 字段没写）：

```bash
python3 scripts/font_doctor.py 04_font/<Family>.ttf        # 结论必须是「可以在 Adobe 里用」（也支持 .otf）
python3 scripts/font_doctor.py --fix-inplace 某个老字体.ttf  # 老字体不想重做时原地补字段
```

`build_font.py` 已经写死了这几个 Adobe 必看字段，不要回退成 FontBuilder 的默认值：

| 字段 | 正确值 | 默认值 → 后果 |
| --- | --- | --- |
| `OS/2.fsType` | `0`（可安装） | `4` 仅预览打印 → PS 拒用；`2` 禁嵌入 → 直接看不见 |
| `OS/2.fsSelection` | `0x0040`（REGULAR） | `0` 没有任何样式位 → PS 认不出 Regular，列表里选不中 |
| `OS/2.ulCodePageRange1` | `0x1`（Latin-1） | `0` → Adobe 认为字体不支持任何代码页，灰掉 |
| `OS/2.ulUnicodeRange1` | 至少 `0x3` | `0` → 字符范围不明 |
| 上下标/删除线尺寸 | 按 upem 比例给非 0 | `0` 会被校验器判坏字体 |
| `post.underlineThickness` | upem/20 | `0` → 下划线消失，像坏字体 |
| `gasp` 表 | 存在（0x000A） | 缺失 → 小字号渲染发糊 |

另外三条「装了但看起来用不了」的必备项（`build_font.py` 已做）：

| 项 | 做法 | 不做会怎样 |
| --- | --- | --- |
| `.notdef` 字形 | 画一个**空心方框** | 缺字时什么都不显示 → 用户以为「字体用不了 / 打字没反应」 |
| 空格 | 必须进 cmap（0x20） | 词间距错乱，空格按 .notdef 走 |
| 只有大写时的小写输入 | 默认把 `a–z` **映射到同一套大写字形**（`--no-map-lowercase` 可关） | 用户在 PS/Figma 里打小写 → 满屏 .notdef 方框，直接判定「这字体不能用」 |

**Adobe 里排查不动时，先给 OTF**：`--out x.otf` 会走 CFF（三次曲线，Adobe 原生格式，不经 Cu2Qu，
字形更准），兼容性通常比 TTF 更好；TTF 装不上就换 OTF 装，别死磕一种格式。
不是 PASS 就查是哪张切歪了（通常是某词切到邻字或漏了笔画），**不要手改 metrics.json 凑数**。

手工构建时的要求（脚本已实现，手写时照抄）：

- 必须包含：`.notdef`、`space`、每个字符一个 glyph。
- 表：`head`（unitsPerEm 1000）、`hhea`/`hmtx`（advance 来自规范化后的墨迹宽 + gap）、
  `maxp`、`cmap`（Unicode → glyph）、`name`（家族名/样式名/全名一致）、
  `OS/2`（sTypoAscender/Descender、usWinAscent/Descent 与基线一致）、`post`。
- 家族名默认取自项目名（例：`AtomFlow`），与用户确认；不要覆盖系统已有字体名。
- 校验：能被 `fontTools.ttLib.TTFont` 重新打开，cmap 覆盖目标字符，每个 glyph 的 advance > 0。

## 9b. 独立运行（不依赖 Pi / 任何 agent 框架）

这套 skill 只有两样东西：**Markdown 说明 + 5 个纯 Python 脚本**。脚本里没有任何
`~/.pi`、`PI_*` 环境变量、私有 SDK 的引用，`env -i HOME=$HOME PATH=/usr/bin:/bin python3 …`
这种空环境下也能跑（已实测：建字体 + 出海报 + 体检全通过）。

**依赖（一次性）**

```bash
# 用哪个 python3 装就对哪个解释器生效：先确认 `which python3`
pip3 install numpy scipy pillow fonttools potracer
python3 scripts/check_env.py        # 全部 ✓ 就能跑了
```

**能干什么 / 需要什么**

| 步骤 | 依赖 | 说明 |
| --- | --- | --- |
| 切分字母 `segment_word.py` | 纯 Python | 离线 |
| 组字 `build_family.py` / `build_font.py` | 纯 Python（potracer 描轮廓） | 离线，不需要网络 |
| 预览海报 `make_specimen.py` | 纯 Python（PIL 渲字） | 离线；**海报是脚本渲的，不用生图模型** |
| 体检 `font_doctor.py` | 纯 Python | 离线 |
| 生成单词图（`01_words/`） | 需要模型：codex CLI/App 内置的 `image_gen`（或 ChatGPT 网页版） | 唯一需要 AI 的一步；也可以人工拿现成图放进去 |
| 材质渲染图（`06_art/`） | 需要模型：同上，图生图 | 可选，用户点头才做 |

**在 codex 里用（不需要 Pi）**

```bash
cd ~/Desktop/某个项目
codex exec --skip-git-repo-check -s workspace-write -i 参考图.png - < 任务.md
# 任务.md 里写：读 ~/.codex/skills/fonter/SKILL.md，按它做完整套字体 + 预览
```
Codex 从 `$CODEX_HOME/skills`（默认 `~/.codex/skills`）加载 skill，`fonter` 是
符号链接也没问题（`codex debug prompt-input | grep fonter` 可自查是否加载到）。

**完全不用 agent 的做法**：自己 `codex`/ChatGPT 出 7 张单词图丢进 `01_words/<WORD>/`，
剩下三步全用命令行：

```bash
python3 scripts/segment_word.py --image 01_words/VAMPIRE/v2_attempt1.png --word VAMPIRE --out 02_letters/VAMPIRE
python3 scripts/build_family.py  --sources 02_letters/* --family MYFONT --out-dir 04_font --charset A-Z,0-9
python3 scripts/make_specimen.py --font 04_font/MYFONT.otf --out 05_preview/specimen.png --style geometric
```

**上传 GitHub / 换到新机器之后**

仓库里带了 `requirements.txt`、`scripts/setup.sh`、`setup.command`，所以**不需要手敲 pip**：

```bash
git clone <repo> ~/fontskill
ln -s ~/fontskill ~/.codex/skills/fonter     # 或整个目录拷进 ~/.codex/skills/
bash ~/.codex/skills/fonter/scripts/setup.sh  # 装依赖 + 自查
# macOS 也可以直接双击 setup.command
```

也可以**直接叫 codex 自己装**，一句话就够：

```
先跑 bash ~/.codex/skills/fonter/scripts/setup.sh 把依赖装好，
再用 ~/.codex/skills/fonter/scripts/check_env.py 确认全绿，然后继续做字体。
```

⚠️ **codex 的沙箱默认断网**（实测 `workspace-write` 下 curl 连 127.0.0.1:7890 都失败），
所以让 codex 装依赖时必须放开网络，任选一种：

```bash
codex exec -s workspace-write -c sandbox_workspace_write.network_access=true …   # 推荐
codex exec --dangerously-bypass-approvals-and-sandbox …                          # 图省事的做法
# 或者：自己双击 setup.command 跑一次，之后 codex 只需要跑脚本（脚本本身不联网）
```

脚本运行阶段（切分/组字/海报/体检）**完全不需要网络**，所以最省事的组合是：
「装依赖这一步人来跑（或 codex 带 network_access）→ 后面全部交给 codex」。

**已知环境坑**

- 机器上可能有多个 `python3`（`/usr/bin/python3` 与 Homebrew/Framework 版），
  `pip3 install` 装到的是 `which pip3` 对应的那个；装完用 `scripts/check_env.py` 确认。
- 本机 codex 直连 `chatgpt.com` / `api.openai.com` 会超时，跑 codex 时要带代理：
  `HTTPS_PROXY=http://127.0.0.1:7890 ALL_PROXY=socks5://127.0.0.1:7890`。
- 脚本不写任何临时文件到 `$CODEX_HOME`，中间产物全在项目目录里。

## 10. 预览海报（Specimen poster，交付必做）

做完整套字体后，**必须**用成品字体渲染一张「字体预览海报」。版式（当前版本）：

```
┌───────────────────────────────┐
│   QUARTZ                      │  ← 两个词，大字号两行，字体本身排，字距统一
│   BLUE                        │
│   RUN IT BACK AGAIN           │  ← 一句随机标语（skill 每次自己抽，每套字体不同）
│                               │
├───────────────────────────────┤  ← 通栏分割线，颜色 = 字体颜色
│  A B C D E F                   │  ← 只有一种大小写：6 列 × 5 行，逐格等大、等字高，
│  G H I J K L                   │     前四行排满（右边缘齐），末行不足则居中
│  M N O P Q R                   │
│  S T U V W X                   │
│      Y  Z                      │
└───────────────────────────────┘

  大小写都有时：A–Z 两行 + a–z 两行 + 数字一行（13 格/行，末行居中）
```

要点：
- **分割线用字体颜色**（不是灰色、不是白色），通栏，粗细约画面高的 0.6%。
- 大字下方那句标语**由脚本按字体名随机抽**（内置 35 句），同一字体结果固定、不同字体必然不同；
  不满意就 `--seed 3` 换，或 `--sentence "自己的标语"` 指定。
- 标语也用**字体本身**排（不是系统字体），字距同样统一。
- 网格**如实反映实际字符集**：只有大写 → A–Z；大写+数字 → A–Z 后直接接 0–9；小写+数字 → a–z + 0–9；
  大小写都有 → 两套 + 数字。只有「a 映射到 A 同一字形」的镜像小写**不重复排**。
- **行数按「填满下半」定，不是固定两行**：只有一种大小写（绝大多数情况）→ 5 行，
  列数 = ceil(字数 / 5)（26 个字 → 6 列，26+10 个 → 8 列），前几行一律**排满、宽度一致**，
  剩下的字放最后一行并**水平居中**（26 个 → A–F / G–L / M–R / S–X / Y Z）。
  绝对不要「每行均分」成 6/5/5/5/5——那样右边缘会戳出一个字来（用户明确否掉过）。
  大小写都有 → 每套 2 行、13 格/行（26 正好两行，边缘是齐的）。只有 `--grid-rows N` 才强制别的行数。

一条命令出图：

```bash
python3 scripts/make_specimen.py --font 04_font/<Family>.ttf \
  --out 05_preview/specimen.png --style <style> --digits on|off
#   不给 --word  → 按字体名抽**两个随机单词**（每套字体都不一样，自动打印抽到哪两个）
#              标语同理自动抽（35 句池），抽到的词与句都写进 specimen.json
#   --word "NOISE FIELD"  指定词组（两个词最好，会竖排两行）
#   --seed 3      换一对词（同一字体同一 seed 结果固定，便于复现）
#   --palette all        115 套高饱和撞色各出一张，便于挑
#   --palette magenta    指定配色（15 套经典款名 / 100 套「底色_字色」名，见 references/preview-specimen.md）
#   --grid-rows 2        强制 2 行（旧版效果，用于对照；默认 auto = 单大小写 5 行）
```

**海报是脚本用成品 TTF 渲的（PIL），绝对不要拿生图模型画海报**——生图模型会把字母画错、
漏字、把 A 画成别的东西，海报必须是字体本身的真实渲染。codex 在这里的职责是：
挑两个词（或 `--word auto` 让脚本抽）→ 跑脚本 → 看结果 → 配色/词不满意就换 `--seed` 重出。

**每套字体都要重新出一次两个词的预览**：不许把上一套（或上一轮）的 specimen.png 复制过来，
也不许所有字体复用同一对词。抽到的词必须写进 `build_log.md` 和 `specimen.json`（`words` 字段）。

硬规则（脚本已实现，不要绕过）：

1. **网格里每个字母/数字的墨迹高度必须完全一致**：先渲染、裁到墨迹、再按目标高度归一化，
   **不看字体度量**（度量里 Q 的尾巴、花体的卷草会干扰）。脚本会打印 `ink_heights_unique`，
   唯一值必须 ≤2 种（亚像素取整允许差 1px）。
2. **上半词组字距必须一致**：同样逐字量墨迹 + 固定间隙排，`specimen.json` 里
   `top_spacing` 的 `ink_gap_min/max` 必须相等（理想差 0）。
3. **配色走「高饱和潘通撞色」**：底色深/浓、字色亮/纯，明度差 ≥45%；几何极简 → 深墨绿/柠檬、
   经典蓝/芥末；粗黑 → 赤红/象牙、橘/墨蓝；液态有机 → 紫外光/亮黄、洋红/亮黄；
   哥特花体 → 赤红/象牙、黑紫/亮黄；笔刷涂鸦 → 橘红/墨蓝、青蓝/近黑。
   `--style` 不给就 `auto` 按墨迹覆盖率自动判。色值一律取自脚本里的 PANTONE 表，禁止手调野生色。
   表里共 **115 套**：15 套经典命名款（`forest` / `fiery` / `iris` …）+ 100 套扩展撞色
   （名字是「底色_字色」，如 `deep_teal_prism_pink`），全部 亮度差 ≥51%、色相拉开，
   且同一底色最多 4 种字色，不会出现「两张海报看着像同一套」。
   `--palette auto` 会在「风格对应的色相池」里按字体名散列取色，并**避开最近用过的 12 套**
   （历史记在 `~/.fonter/palette_history.json`，可用 `FONTER_PALETTE_HISTORY` 改位置）。
4. 文案小字用系统无衬线（Helvetica）——它是说明文字，不是字体样本，所以不暴露字体缺点。

出图后自检：

- `05_preview/specimen.json`：`verdict` 必须是 `PASS`；
- 把字体渲成 `05_preview/text_check.png`（一行示例句 + 一行数字），肉眼确认 **整句字距均匀、
  没有字母/数字大小不一、没有被裁断**；
- 海报**给用户看**，配色和随机词组不满意就换 `--seed` / `--palette` / `--word` 重出。

### 10a. 出图后的那句提问（两件事一起问，别只问一半）

海报出来后，向用户提问时**必须同时问这两件**，不要只问「满意吗」：

1. **这版配色/词组你满意吗？** 不满意就 `--seed` / `--palette` / `--word` 重出。
2. **要不要再出两张材质预览渲染图？**（把这张海报渲染成真实材质：草坪+喷漆、砖墙+喷漆、
   黑亚克力+水银、红宝石+刻痕…）

话术示例：

> 海报出来了（配色 forest、词组 FLAT BRISK）。
> ① 这版满意吗？不满意我换 seed / 配色重出。
> ② 要不要再出两张材质预览渲染图？我随机配了 **草坪 + 喷漆**、**磨砂玻璃 + 喷砂** 两组；
> 你想指定材质也行（比如「红砖墙 + 喷漆」「黑亚克力 + 水银」）。

用户点头才做（材质渲染要调 image_gen，一张约 2 分钟），**默认 2 张不同材质**便于对比；
用户没要求就交普通配色版即可，不要自作主张批量出图。

### 10b. 材质渲染图（可选，图生图）

用户要「把海报做成真实材质」时，拿 `05_preview/specimen.png` 当唯一版式与字形依据去图生图。

**材质搭配不写死在脚本里，也没有内置材质字典**：

- **用户指名了材质** → 原样照用户的来（用户说「砖墙喷漆」就只做砖墙喷漆，别自作主张换）。
- **用户没指名** → 由你（agent）**当场随机想一组搭配**（表面 + 媒介，越具体越好），
  再传给脚本。别每次都用同一组，也别只写「砖墙」两个字——要带表面细节与媒介工艺，
  例如「老旧红砖墙 + 街头喷漆」「退潮湿沙 + 压印」「黑亚克力 + 水银」「毛毡 + 刺绣」
  「拉丝铝 + 丝网印刷」「橡木 + 烙铁烧痕」「磨砂玻璃 + 喷砂」。

一条命令一组材质（产物落 `06_art/`）：

```bash
# 用户指定材质：
python3 scripts/render_material.py --project projects/<slug> \
    --material "老旧红砖墙 + 街头喷漆"

# 用户没指定：你自己随机想 2 组，一次传进去（默认出 2 张）
python3 scripts/render_material.py --project projects/<slug> \
    --material "退潮湿沙 + 压印" --material "磨砂玻璃 + 喷砂"

python3 scripts/render_material.py --project projects/<slug> --material "…" --dry-run  # 只看提示词，不花额度
```

脚本负责：从 `specimen.json` 取词组/标语/字符集写进「拼写不能错」硬规则、调
`codex exec -i specimen.png` 的 `image_gen`、出图后校验（竖版、非纯色、与参考图差异 ≥6、
>20KB，不合格重试一次）、归档 `<Family>_<材质>.png` + `.prompt.txt` + `materials.json`。

**手动链路**（不用脚本时，同样拿 `specimen.png` 当参考图）：

```bash
codex exec -i 05_preview/specimen.png --skip-git-repo-check -s workspace-write - <<'MD'
把参考图当版式与字形的唯一依据，只换材质：<材质描述，含表面细节与工艺>。
硬性要求：版式 1:1（两个词两行 / 一句标语 / 通栏分割线 / 下半字母网格的**行数与逐行字母全部保留**，
行数以 specimen.json 的 grid.row_characters 为准：单大小写 5 行、大小写都有 4 行 + 数字 1 行）；
字母形状与参考图逐字一致、不要换字体；拼写不能错（两个词是 X / Y，网格 A→Z、0→9 一字不漏）；
只改材质与光照，不加 logo/水印/边框/道具。输出 <项目>/06_art/<name>.png
MD
```

注意：
- 生图模型**仍可能把个别字母画错或漏行**（尤其花体网格），所以材质图只当**宣传/氛围图**，
  字形真值以 `make_specimen.py` 渲的那张为准。
- 材质描述要具体到「漆的雾化颗粒/流挂、金属镜面高光、刻痕翻边毛刺、沙粒塌陷与积水反光」
  这一层，否则会退化成平涂或滤镜。
- 一次一张，别在同一个 prompt 里要四张。
- 交付时写明：每套字体出了几张、用了哪些材质（都在 `06_art/materials.json` 里）。

## 11. 交付

- 交付清单：**两种格式的字体绝对路径**（`04_font/<Family>.ttf` + `04_font/<Family>.otf`）、
  覆盖的字符集、每个字母的来源词、海报 `specimen.png`、
  `metrics.json`（字距/字高结论）、以及安装方法（双击安装，或 `cp 04_font/<Family>.ttf ~/Library/Fonts/`）。
- 用户点头要材质图时，追加 `06_art/<Family>_<material>.png`（默认 2 张）与 `06_art/materials.json`；
  交付时注明「这是宣传/氛围图，字形真值仍是 specimen.png」。
- 未经用户明确同意，不要安装到 `~/Library/Fonts`，也不要改动用户已有文件。


## 12. 违禁项

- 不要重新设计字形、不要替换成别的字体风格、不要"顺手优化"笔画。
- 不要用 OCR 猜字母：字母顺序由目标单词决定。
- 不要跳过分割前的确认，也不要在同一提示词上原样重试。
- 不要把生成的图留在临时目录或 `$CODEX_HOME` 默认路径，最终产物一律进项目目录。
- **不要**让字母大小不齐：同一套字体所有大写字母墨迹高度必须等于 cap（默认 700/1000），
  数字也必须等于 cap；缺字宁可让用户补参考图，也不要拿系统字体或别的字母顶上。
- **不要**用各自不同的 advance 凑宽度：左右边距统一 `gap/2`，任意相邻字母的可见间隙都必须
  等于 `gap`（`metrics.json` 里 min/max 差 ≤2）。排一句话出现「忽紧忽松」= 返工。
- **不要**只交 TTF 就收工：OTF（CFF）必须一起出，Adobe 系软件优先吃它。
- **不要**把同一家族的 `.ttf` 和 `.otf` 同时装进 `~/Library/Fonts`：PS 会判重名「不可用」。
- **不要**在预览海报里手动调字号/颜色去"救"某个字母：网格一格一个字号是错的，
  海报暴露的大小不一致说明字体本身没规范化，回去修字体。

## 13. 已踩过的坑（都是真事故，别重犯）

| 现象 | 根因 | 正确做法 |
| --- | --- | --- |
| 字体里字腔（O/P/D 的内部）被填实 | 手工判定轮廓嵌套/方向时把洞当成了外轮廓 | potrace 输出本身「外轮廓一个方向、洞相反」，直接用它的方向，只在最大轮廓方向反了时整体翻转（`build_font.py` 已实现） |
| 字距检查显示 ±4~17 的假偏差 | 用 `glyf.xMin/xMax` 判字距 —— TrueType bbox 把二次曲线**控制点**也算进去，虚胖 | 逐字渲到像素、量真实墨迹再算间隙 |
| 二次曲线拟合把字形缩水 3% | `Cu2QuPen(max_err=0.4)` 实际误差远超 0.4 字体单位 | `max_err=0.05`，点数翻倍但字形准 |
| 反复测量同一字体结果不变 | `ImageFont.truetype(path, size)` 按路径缓存 | 用 `io.BytesIO(open(path,'rb').read())` 每次重读 |
| advance 与墨迹宽差半个单位 | advance 必须是整数、墨迹宽是小数 | 建完字体后跑「渲染校正」循环：按实测墨迹平移 + 重算 advance（最多 3 轮） |
| 装饰花体切分把卷草切给邻居 | 只用连通块/投影/DP | 加 `clusters` 策略（按 x 排序，在最宽的 n−1 个空隙合并连通块），`auto` 里排第三 |
| 数字等宽反而出现空隙 | tabular figures 会在数字之间多留空 | 默认比例宽；只有用户要「表格数字对齐」才 `--tabular-digits` |
| 用 `*_rejected_*` 目录组字 | 重生留下的旧切分没清 | 只吃人工复核过的 `02_letters_final/`，跳过所有 `*rejected*` |
| 预览网格里字母大小不齐 | 用字体度量（advance/bbox）排版 | 先渲成墨迹、按墨迹高度归一化，所有格子共用同一个 `ink_h` |
| 海报下半大片空白、字母又小又挤 | 只有大写（26 个字）也按 13 格/行排，只占 2 行 | 单大小写一律排 **5 行**、固定 6–8 列（`--grid-rows auto` 已是默认） |
| 网格右边缘戳出一个字 | 26 个字「均分」5 行必然 6/5/5/5/5，多的那个字单边凸出 | 固定列数、前几行排满、末行居中（26 → 6/6/6/6 + 居中 Y Z） |
| 连着做两套字体，海报都是「红底白字」 | `auto` 选色 = `STYLE_PALETTES[style][seed % 3]`，`--seed` 默认 0 → 同风格永远第一顺位 | `auto` 改成「风格色相池 + 字体名散列 + 避开最近 12 套」，池子从 15 套扩到 115 套 |
| 字体装上但 PS/AI 里「看不到 / 选不中 / 用不了」 | FontBuilder 默认 `fsType=4`、`fsSelection=0`、`ulCodePageRange=0`、上下标尺寸 0 | `build_font.py` 显式写这些字段；交付前跑 `font_doctor.py`，结论必须是「可以在 Adobe 里用」 |
| 字体在 PS 里能选，但打字「什么都没出现」 | 只有大写 → 用户打小写全是 .notdef；而 `.notdef` 原本是空的 | `.notdef` 画空心框 + 空格进 cmap + 默认把 a–z 映射到大写字形 |
| 同一家族装了 TTF 又装 OTF | 两个文件同一 family/PS 名 | PS 判重名「不可用」；一个家族只装一种格式 |

## 14. 交互与非交互

- 交互模式下，每个闸门（平面化确认、词表确认、分割前确认、大小写选择）都要停下来等用户回答。
- **海报出来后必问两件（§10a）**：① 这版配色/词组满意吗？② 要不要再出一张材质预览渲染图
  （材质组合随机抽）。不得只问满意、也不得在用户未点头时自作主张批量出材质图。
- 非交互模式（`codex exec` / 无人值守）下：无法提问时**按默认值继续**，但必须把每个闸门的
  产物写到磁盘（`reference_flat.png`、`words_review.png`、`letters_grid.png`），
  并在最终报告里列出「哪些闸门是自动通过的、用了什么默认值」，方便用户事后否决重来。
- 任何一步失败（图像生成失败、切不出字母、字体构建报错）都要：说明失败点 + 已尝试的方案 +
  建议的下一步，不要静默改用别的模型或悄悄降低要求。
