#!/usr/bin/env python3
"""用刚做好的字体渲染一张「字体预览海报」（对标 05_preview 的参考样张）。

版式（参考 12112.png）：
  上半  随机词组 / 指定词组，用生字体本身排，字距统一
  中部  条码 + 说明小字 + 分隔线
  下半  A–Z（及数字）整齐排列，每格等大、等字高；
        只有一种大小写（常见：只有大写）时均分 5 行，避免下半留大片空白

用法:
  python3 make_specimen.py --font 04_font/POLYMER.ttf --out 05_preview/specimen.png \
      --style geometric --word "HYPER SECTOR"        # 不给 --word 就随机
  python3 make_specimen.py --font ... --digits off    # 不要数字
  python3 make_specimen.py --font ... --palette all   # 每套潘通撞色各出一张

  --grid-rows N       字母均分 N 行（默认 auto：只有一种大小写 → 5 行，大小写都有 → 各 2 行）
  --grid-adaptive     按实际墨迹宽度排格，行内固定间隙（默认关）
  --headline-scale F  两词和标语字号倍数，仍受安全宽度限制（默认 1.0）

铁律:
  * 网格里每个字母/数字的墨迹高度完全一致（先量墨迹再按高度归一化，不看字体度量）。
  * 每行字距 = 固定 value，靠「逐字量墨迹 + 固定间隙」排，不用 font 的 advance，
    所以不会出现排出来的句子里字距忽大忽小。
"""
from __future__ import annotations

import _bootstrap  # noqa: F401  —— 缺依赖时给安装命令，而不是 traceback
import argparse
import colorsys
import hashlib
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 潘通撞色方案
# 每套都是「深底 + 撞色亮字」或「亮底 + 深字」的高对比组合，取自 Pantone TCX 常见色。
# 共 115 套：前 15 套是手工命名的经典款（命令行 --palette forest 之类），
# 后 100 套是高饱和撞色扩展库（名字是「底色_字色」，如 deep_teal_prism_pink）。
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

    # ---- 以下 100 套由 gen_palettes 生成：Pantone TCX 双色配对，亮度差 ≥ 51%、
    # 色相拉开；每个底色最多配 4 个色相彼此拉开的字色，避免连着两套海报撞成同一个样。
    "dress_blues_vibrant_yellow": dict(bg="#2B3A55", fg="#FFDA29", pantone="19-4024 Dress Blues / 13-0858 Vibrant Yellow"),  # 亮度差 61%, 色相差 169°
    "true_navy_vibrant_yellow":  dict(bg="#3F5277", fg="#FFDA29", pantone="19-4110 True Navy / 13-0858 Vibrant Yellow"),  # 亮度差 52%, 色相差 170°
    "sky_captain_vibrant_yellow": dict(bg="#262F3D", fg="#FFDA29", pantone="19-4118 Sky Captain / 13-0858 Vibrant Yellow"),  # 亮度差 65%, 色相差 167°
    "reflecting_pond_peach_bud": dict(bg="#203E4A", fg="#F6B08A", pantone="19-4326 Reflecting Pond / 14-1220 Peach Bud"),  # 亮度差 52%, 色相差 176°
    "majolica_blue_vibrant_yellow": dict(bg="#274357", fg="#FFDA29", pantone="19-3925 Majolica Blue / 13-0858 Vibrant Yellow"),  # 亮度差 59%, 色相差 155°
    "dark_denim_vibrant_yellow": dict(bg="#35465C", fg="#FFDA29", pantone="19-4013 Dark Denim / 13-0858 Vibrant Yellow"),  # 亮度差 57%, 色相差 164°
    "deep_teal_prism_pink":      dict(bg="#18454B", fg="#FBB1C1", pantone="19-4914 Deep Teal / 13-3206 Prism Pink"),  # 亮度差 53%, 色相差 160°
    "botanical_garden_prism_pink": dict(bg="#1A3B2B", fg="#FBB1C1", pantone="19-5413 Botanical Garden / 13-3206 Prism Pink"),  # 亮度差 56%, 色相差 164°
    "dark_green_prism_pink":     dict(bg="#1F3A2C", fg="#FBB1C1", pantone="19-0415 Dark Green / 13-3206 Prism Pink"),  # 亮度差 56%, 色相差 162°
    "kombu_green_rose_quartz":   dict(bg="#354230", fg="#F7CAC9", pantone="19-0312 Kombu Green / 13-1520 Rose Quartz"),  # 亮度差 59%, 色相差 102°
    "ponderosa_pine_rose_quartz": dict(bg="#203B32", fg="#F7CAC9", pantone="19-5511 Ponderosa Pine / 13-1520 Rose Quartz"),  # 亮度差 62%, 色相差 159°
    "black_iris_cyber_yellow":   dict(bg="#2A2B47", fg="#FFD400", pantone="19-3921 Black Iris / 13-0859 Cyber Yellow"),  # 亮度差 63%, 色相差 172°
    "purple_heart_screaming_green": dict(bg="#3B2A47", fg="#D3F05B", pantone="19-3628 Purple Heart / 14-0244 Screaming Green"),  # 亮度差 69%, 色相差 157°
    "imperial_purple_screaming_green": dict(bg="#5B3A6E", fg="#D3F05B", pantone="19-3620 Imperial Purple / 14-0244 Screaming Green"),  # 亮度差 61%, 色相差 154°
    "ultra_violet_screaming_green": dict(bg="#5F4B8B", fg="#D3F05B", pantone="18-3838 Ultra Violet / 14-0244 Screaming Green"),  # 亮度差 55%, 色相差 173°
    "burgundy_icy_blue":         dict(bg="#64313E", fg="#CBE4EF", pantone="19-1617 Burgundy / 13-4410 Icy Blue"),  # 亮度差 64%, 色相差 146°
    "rhubarb_icy_blue":          dict(bg="#7C2E3D", fg="#CBE4EF", pantone="18-1434 Rhubarb / 13-4410 Icy Blue"),  # 亮度差 63%, 色相差 150°
    "chocolate_brown_icy_blue":  dict(bg="#4E3B31", fg="#CBE4EF", pantone="19-0912 Chocolate Brown / 13-4410 Icy Blue"),  # 亮度差 63%, 色相差 178°
    "charcoal_gray_cyber_yellow": dict(bg="#3C3F41", fg="#FFD400", pantone="18-0601 Charcoal Gray / 13-0859 Cyber Yellow"),  # 亮度差 56%, 色相差 154°
    "stretch_limo_cyber_yellow": dict(bg="#1E1E22", fg="#FFD400", pantone="19-4005 Stretch Limo / 13-0859 Cyber Yellow"),  # 亮度差 69%, 色相差 170°
    "bistro_green_rose_quartz":  dict(bg="#2A4B3E", fg="#F7CAC9", pantone="19-5420 Bistro Green / 13-1520 Rose Quartz"),  # 亮度差 57%, 色相差 155°
    "quetzal_green_lemon":       dict(bg="#006865", fg="#F9E13F", pantone="18-5020 Quetzal Green / 12-0736 Lemon"),  # 亮度差 54%, 色相差 126°
    "sodalite_blue_cyber_yellow": dict(bg="#253668", fg="#FFD400", pantone="19-3952 Sodalite Blue / 13-0859 Cyber Yellow"),  # 亮度差 60%, 色相差 175°
    "vulcan_lemon":              dict(bg="#2A2D3B", fg="#F9E13F", pantone="19-3906 Vulcan / 12-0736 Lemon"),  # 亮度差 68%, 色相差 177°
    "carafe_sky_blue":           dict(bg="#45312B", fg="#7CC5E6", pantone="19-1116 Carafe / 15-4319 Sky Blue"),  # 亮度差 51%, 色相差 175°
    "fudge_bright_white":        dict(bg="#4F3327", fg="#F7F6F2", pantone="19-1216 Fudge / 11-0601 Bright White"),  # 亮度差 74%, 色相差 30°
    "gibraltar_sea_peach_bud":   dict(bg="#173B4F", fg="#F6B08A", pantone="19-4045 Gibraltar Sea / 14-1220 Peach Bud"),  # 亮度差 53%, 色相差 180°
    "capers_rose_quartz":        dict(bg="#3A4425", fg="#F7CAC9", pantone="19-0528 Capers / 13-1520 Rose Quartz"),  # 亮度差 58%, 色相差 78°
    "eclipse_lemon":             dict(bg="#2A2B2E", fg="#F9E13F", pantone="19-3810 Eclipse / 12-0736 Lemon"),  # 亮度差 69%, 色相差 173°
    "dark_olive_bright_white":   dict(bg="#3B3A24", fg="#F7F6F2", pantone="19-0419 Dark Olive / 11-0601 Bright White"),  # 亮度差 74%, 色相差 9°
    "fir_green_lemon":           dict(bg="#1F4436", fg="#F9E13F", pantone="19-5920 Fir Green / 12-0736 Lemon"),  # 亮度差 62%, 色相差 105°
    "tawny_port_lime_punch":     dict(bg="#5C3A3A", fg="#C6E52B", pantone="19-1218 Tawny Port / 13-0550 Lime Punch"),  # 亮度差 56%, 色相差 70°
    "vintage_indigo_primrose_yellow": dict(bg="#2B3A4A", fg="#F6D155", pantone="19-3920 Vintage Indigo / 13-0755 Primrose Yellow"),  # 亮度差 60%, 色相差 165°
    "bright_white_quetzal_green": dict(bg="#F7F6F2", fg="#006865", pantone="11-0601 Bright White / 18-5020 Quetzal Green"),  # 亮度差 64%, 色相差 130°
    "lemon_quetzal_green":       dict(bg="#F9E13F", fg="#006865", pantone="12-0736 Lemon / 18-5020 Quetzal Green"),  # 亮度差 54%, 色相差 126°
    "primrose_yellow_sodalite_blue": dict(bg="#F6D155", fg="#253668", pantone="13-0755 Primrose Yellow / 19-3952 Sodalite Blue"),  # 亮度差 60%, 色相差 179°
    "vibrant_yellow_quetzal_green": dict(bg="#FFDA29", fg="#006865", pantone="13-0858 Vibrant Yellow / 18-5020 Quetzal Green"),  # 亮度差 52%, 色相差 129°
    "cyber_yellow_sodalite_blue": dict(bg="#FFD400", fg="#253668", pantone="13-0859 Cyber Yellow / 19-3952 Sodalite Blue"),  # 亮度差 60%, 色相差 175°
    "lime_punch_sodalite_blue":  dict(bg="#C6E52B", fg="#253668", pantone="13-0550 Lime Punch / 19-3952 Sodalite Blue"),  # 亮度差 61%, 色相差 155°
    "spring_bud_sodalite_blue":  dict(bg="#B7E04B", fg="#253668", pantone="14-0446 Spring Bud / 19-3952 Sodalite Blue"),  # 亮度差 59%, 色相差 148°
    "fiery_red_lime_punch":      dict(bg="#D01A2E", fg="#C6E52B", pantone="18-1664 Fiery Red / 13-0550 Lime Punch"),  # 亮度差 56%, 色相差 77°
    "fuchsia_rose_antique_white": dict(bg="#C7437F", fg="#F2E7D5", pantone="17-2031 Fuchsia Rose / 11-0105 Antique White"),  # 亮度差 52%, 色相差 65°
    "raspberry_sorbet_pineapple_slice": dict(bg="#D23C77", fg="#F7E6A3", pantone="18-2133 Raspberry Sorbet / 12-0718 Pineapple Slice"),  # 亮度差 52%, 色相差 71°
    "hot_pink_pineapple_slice":  dict(bg="#E2306B", fg="#F7E6A3", pantone="18-1950 Hot Pink / 12-0718 Pineapple Slice"),  # 亮度差 54%, 色相差 68°
    "pink_peacock_lime_punch":   dict(bg="#C62168", fg="#C6E52B", pantone="18-2043 Pink Peacock / 13-0550 Lime Punch"),  # 亮度差 53%, 色相差 96°
    "bright_chartreuse_sodalite_blue": dict(bg="#C9E265", fg="#253668", pantone="14-0445 Bright Chartreuse / 19-3952 Sodalite Blue"),  # 亮度差 62%, 色相差 153°
    "cream_gold_quetzal_green":  dict(bg="#F5E1A8", fg="#006865", pantone="12-0712 Cream Gold / 18-5020 Quetzal Green"),  # 亮度差 56%, 色相差 134°
    "antique_white_quetzal_green": dict(bg="#F2E7D5", fg="#006865", pantone="11-0105 Antique White / 18-5020 Quetzal Green"),  # 亮度差 59%, 色相差 141°
    "sulphur_quetzal_green":     dict(bg="#E8DE6C", fg="#006865", pantone="15-0646 Sulphur / 18-5020 Quetzal Green"),  # 亮度差 53%, 色相差 123°
    "screaming_green_sodalite_blue": dict(bg="#D3F05B", fg="#253668", pantone="14-0244 Screaming Green / 19-3952 Sodalite Blue"),  # 亮度差 66%, 色相差 153°
    "peach_bud_gibraltar_sea":   dict(bg="#F6B08A", fg="#173B4F", pantone="14-1220 Peach Bud / 19-4045 Gibraltar Sea"),  # 亮度差 53%, 色相差 180°
    "icy_blue_fiery_red":        dict(bg="#CBE4EF", fg="#D01A2E", pantone="13-4410 Icy Blue / 18-1664 Fiery Red"),  # 亮度差 62%, 色相差 155°
    "custard_gibraltar_sea":     dict(bg="#F4E19A", fg="#173B4F", pantone="12-0815 Custard / 19-4045 Gibraltar Sea"),  # 亮度差 67%, 色相差 154°
    "fair_aqua_fiery_red":       dict(bg="#A9D6D0", fg="#D01A2E", pantone="14-4510 Fair Aqua / 18-1664 Fiery Red"),  # 亮度差 54%, 色相差 179°
    "rose_quartz_deep_teal":     dict(bg="#F7CAC9", fg="#18454B", pantone="13-1520 Rose Quartz / 19-4914 Deep Teal"),  # 亮度差 59%, 色相差 174°
    "prism_pink_deep_teal":      dict(bg="#FBB1C1", fg="#18454B", pantone="13-3206 Prism Pink / 19-4914 Deep Teal"),  # 亮度差 53%, 色相差 160°
    "lilac_sachet_gibraltar_sea": dict(bg="#C2B4D8", fg="#173B4F", pantone="14-3812 Lilac Sachet / 19-4045 Gibraltar Sea"),  # 亮度差 52%, 色相差 62°
    "sunny_lime_gibraltar_sea":  dict(bg="#D6D94B", fg="#173B4F", pantone="15-0538 Sunny Lime / 19-4045 Gibraltar Sea"),  # 亮度差 60%, 色相差 140°
    "meadowlark_gibraltar_sea":  dict(bg="#E2C55E", fg="#173B4F", pantone="13-0822 Meadowlark / 19-4045 Gibraltar Sea"),  # 亮度差 56%, 色相差 155°
    "pineapple_slice_gibraltar_sea": dict(bg="#F7E6A3", fg="#173B4F", pantone="12-0718 Pineapple Slice / 19-4045 Gibraltar Sea"),  # 亮度差 69%, 色相差 154°
    "cayenne_lime_punch":        dict(bg="#A2343A", fg="#C6E52B", pantone="18-1652 Cayenne / 13-0550 Lime Punch"),  # 亮度差 52%, 色相差 73°
    "dress_blues_prism_pink":    dict(bg="#2B3A55", fg="#FBB1C1", pantone="19-4024 Dress Blues / 13-3206 Prism Pink"),  # 亮度差 54%, 色相差 128°
    "sky_captain_prism_pink":    dict(bg="#262F3D", fg="#FBB1C1", pantone="19-4118 Sky Captain / 13-3206 Prism Pink"),  # 亮度差 58%, 色相差 131°
    "reflecting_pond_screaming_green": dict(bg="#203E4A", fg="#D3F05B", pantone="19-4326 Reflecting Pond / 14-0244 Screaming Green"),  # 亮度差 65%, 色相差 125°
    "majolica_blue_prism_pink":  dict(bg="#274357", fg="#FBB1C1", pantone="19-3925 Majolica Blue / 13-3206 Prism Pink"),  # 亮度差 52%, 色相差 142°
    "deep_teal_vibrant_yellow":  dict(bg="#18454B", fg="#FFDA29", pantone="19-4914 Deep Teal / 13-0858 Vibrant Yellow"),  # 亮度差 60%, 色相差 137°
    "botanical_garden_cyber_yellow": dict(bg="#1A3B2B", fg="#FFD400", pantone="19-5413 Botanical Garden / 13-0859 Cyber Yellow"),  # 亮度差 61%, 色相差 101°
    "dark_green_cyber_yellow":   dict(bg="#1F3A2C", fg="#FFD400", pantone="19-0415 Dark Green / 13-0859 Cyber Yellow"),  # 亮度差 61%, 色相差 99°
    "kombu_green_icy_blue":      dict(bg="#354230", fg="#CBE4EF", pantone="19-0312 Kombu Green / 13-4410 Icy Blue"),  # 亮度差 63%, 色相差 95°
    "ponderosa_pine_lemon":      dict(bg="#203B32", fg="#F9E13F", pantone="19-5511 Ponderosa Pine / 12-0736 Lemon"),  # 亮度差 65%, 色相差 108°
    "purple_heart_peach_bud":    dict(bg="#3B2A47", fg="#F6B08A", pantone="19-3628 Purple Heart / 14-1220 Peach Bud"),  # 亮度差 55%, 色相差 106°
    "imperial_purple_rose_quartz": dict(bg="#5B3A6E", fg="#F7CAC9", pantone="19-3620 Imperial Purple / 13-1520 Rose Quartz"),  # 亮度差 56%, 色相差 83°
    "ultra_violet_icy_blue":     dict(bg="#5F4B8B", fg="#CBE4EF", pantone="18-3838 Ultra Violet / 13-4410 Icy Blue"),  # 亮度差 55%, 色相差 60°
    "burgundy_screaming_green":  dict(bg="#64313E", fg="#D3F05B", pantone="19-1617 Burgundy / 14-0244 Screaming Green"),  # 亮度差 64%, 色相差 87°
    "rhubarb_screaming_green":   dict(bg="#7C2E3D", fg="#D3F05B", pantone="18-1434 Rhubarb / 14-0244 Screaming Green"),  # 亮度差 63%, 色相差 83°
    "bistro_green_lemon":        dict(bg="#2A4B3E", fg="#F9E13F", pantone="19-5420 Bistro Green / 12-0736 Lemon"),  # 亮度差 59%, 色相差 104°
    "vulcan_rose_quartz":        dict(bg="#2A2D3B", fg="#F7CAC9", pantone="19-3906 Vulcan / 13-1520 Rose Quartz"),  # 亮度差 65%, 色相差 132°
    "carafe_spring_bud":         dict(bg="#45312B", fg="#B7E04B", pantone="19-1116 Carafe / 14-0446 Spring Bud"),  # 亮度差 59%, 色相差 63°
    "gibraltar_sea_bright_chartreuse": dict(bg="#173B4F", fg="#C9E265", pantone="19-4045 Gibraltar Sea / 14-0445 Bright Chartreuse"),  # 亮度差 62%, 色相差 129°
    "bright_white_black_iris":   dict(bg="#F7F6F2", fg="#2A2B47", pantone="11-0601 Bright White / 19-3921 Black Iris"),  # 亮度差 79%, 色相差 170°
    "lemon_stretch_limo":        dict(bg="#F9E13F", fg="#1E1E22", pantone="12-0736 Lemon / 19-4005 Stretch Limo"),  # 亮度差 74%, 色相差 172°
    "primrose_yellow_pink_peacock": dict(bg="#F6D155", fg="#C62168", pantone="13-0755 Primrose Yellow / 18-2043 Pink Peacock"),  # 亮度差 53%, 色相差 72°
    "vibrant_yellow_pink_peacock": dict(bg="#FFDA29", fg="#C62168", pantone="13-0858 Vibrant Yellow / 18-2043 Pink Peacock"),  # 亮度差 55%, 色相差 75°
    "cyber_yellow_pink_peacock": dict(bg="#FFD400", fg="#C62168", pantone="13-0859 Cyber Yellow / 18-2043 Pink Peacock"),  # 亮度差 52%, 色相差 76°
    "lime_punch_pink_peacock":   dict(bg="#C6E52B", fg="#C62168", pantone="13-0550 Lime Punch / 18-2043 Pink Peacock"),  # 亮度差 53%, 色相差 96°
    "spring_bud_fiery_red":      dict(bg="#B7E04B", fg="#D01A2E", pantone="14-0446 Spring Bud / 18-1664 Fiery Red"),  # 亮度差 54%, 色相差 83°
    "bright_chartreuse_fiery_red": dict(bg="#C9E265", fg="#D01A2E", pantone="14-0445 Bright Chartreuse / 18-1664 Fiery Red"),  # 亮度差 57%, 色相差 79°
    "cream_gold_stretch_limo":   dict(bg="#F5E1A8", fg="#1E1E22", pantone="12-0712 Cream Gold / 19-4005 Stretch Limo"),  # 亮度差 76%, 色相差 164°
    "antique_white_black_iris":  dict(bg="#F2E7D5", fg="#2A2B47", pantone="11-0105 Antique White / 19-3921 Black Iris"),  # 亮度差 73%, 色相差 159°
    "sulphur_stretch_limo":      dict(bg="#E8DE6C", fg="#1E1E22", pantone="15-0646 Sulphur / 19-4005 Stretch Limo"),  # 亮度差 73%, 色相差 175°
    "screaming_green_hot_pink":  dict(bg="#D3F05B", fg="#E2306B", pantone="14-0244 Screaming Green / 18-1950 Hot Pink"),  # 亮度差 52%, 色相差 92°
    "icy_blue_stretch_limo":     dict(bg="#CBE4EF", fg="#1E1E22", pantone="13-4410 Icy Blue / 19-4005 Stretch Limo"),  # 亮度差 76%, 色相差 42°
    "custard_hot_pink":          dict(bg="#F4E19A", fg="#E2306B", pantone="12-0815 Custard / 18-1950 Hot Pink"),  # 亮度差 52%, 色相差 67°
    "sunny_lime_fiery_red":      dict(bg="#D6D94B", fg="#D01A2E", pantone="15-0538 Sunny Lime / 18-1664 Fiery Red"),  # 亮度差 55%, 色相差 68°
    "pineapple_slice_hot_pink":  dict(bg="#F7E6A3", fg="#E2306B", pantone="12-0718 Pineapple Slice / 18-1950 Hot Pink"),  # 亮度差 54%, 色相差 68°
    "purple_heart_sky_blue":     dict(bg="#3B2A47", fg="#7CC5E6", pantone="19-3628 Purple Heart / 15-4319 Sky Blue"),  # 亮度差 53%, 色相差 76°
    "imperial_purple_icy_blue":  dict(bg="#5B3A6E", fg="#CBE4EF", pantone="19-3620 Imperial Purple / 13-4410 Icy Blue"),  # 亮度差 61%, 色相差 80°
    "bright_white_pink_peacock": dict(bg="#F7F6F2", fg="#C62168", pantone="11-0601 Bright White / 18-2043 Pink Peacock"),  # 亮度差 68%, 色相差 74°
    "lemon_pink_peacock":        dict(bg="#F9E13F", fg="#C62168", pantone="12-0736 Lemon / 18-2043 Pink Peacock"),  # 亮度差 57%, 色相差 78°
    "cream_gold_hot_pink":       dict(bg="#F5E1A8", fg="#E2306B", pantone="12-0712 Cream Gold / 18-1950 Hot Pink"),  # 亮度差 53%, 色相差 64°
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

# 风格 → 底色色相区间（度）。auto 选色时用它在 100+ 套里扩大取色范围，
# 不再像以前那样「同一个 style 永远第一顺位那套」（曾连着两套都出红白）。
STYLE_HUES = {
    "geometric": [(140, 265)],
    "minimal": [(175, 265)],
    "bold": [(330, 360), (0, 50)],
    "heavy": [(330, 360), (0, 50)],
    "blob": [(255, 335)],
    "organic": [(60, 180)],
    "blackletter": [(330, 360), (0, 25), (250, 300)],
    "ornate": [(330, 360), (250, 320)],
    "brush": [(0, 60), (300, 360)],
    "graffiti": [(0, 60), (140, 200)],
    "script": [(260, 360)],
    "rounded": [(300, 360), (0, 60), (140, 210)],
    "tech": [(150, 265)],
}

# 网格行数：只有一种大小写（最常见 = 只有大写）时排 5 行把下半填满，
# 大小写都有时每套 2 行（13 格/行），和参考样张一致。
GRID_ROWS_SINGLE_CASE = 5
GRID_ROWS_MULTI_CASE = 2
MIN_CHARS_PER_ROW = 5          # 字数太少时别硬凑 5 行（12 个字排 5 行会很空）
PALETTE_HISTORY_KEEP = 12      # 记住最近用过的 N 套配色，auto 时避开

DEFAULT_HISTORY = Path.home() / ".fonter" / "palette_history.json"


def _hex_hue(hexcolor):
    r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _, _ = colorsys.rgb_to_hls(r, g, b)
    return h * 360


def style_pool(style):
    """风格对应的候选配色：手写首选 + 所有底色色相落在该风格区间里的扩展色。"""
    pool = [p for p in STYLE_PALETTES.get(style, []) if p in PALETTES]
    ranges = STYLE_HUES.get(style, [])
    for name, pal in PALETTES.items():
        if name in pool:
            continue
        hue = _hex_hue(pal["bg"])
        if any(lo <= hue <= hi for lo, hi in ranges):
            pool.append(name)
    return pool or list(PALETTES)


def palette_history_path():
    return Path(os.environ.get("FONTER_PALETTE_HISTORY", str(DEFAULT_HISTORY)))


def read_palette_history():
    try:
        data = json.loads(palette_history_path().read_text())
        return [p for p in data.get("recent", []) if isinstance(p, str)]
    except Exception:
        return []


def remember_palette(name):
    """把这次用的配色记进历史（下一次 auto 会避开它）。"""
    try:
        recent = [p for p in read_palette_history() if p != name]
        recent.append(name)
        path = palette_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"recent": recent[-PALETTE_HISTORY_KEEP:]}, ensure_ascii=False))
    except Exception:
        pass


def pick_auto_palette(family, style, seed=0):
    """auto 选色：风格池 → 剔除最近用过的 → 按字体名散列取一套。

    同一字体同一 seed 拿到的配色不会「永远第一顺位」；换字体必然换配色，
    连着做几套字体也不会重复用同一套（这是之前红白撞车的根因）。
    """
    pool = style_pool(style)
    recent = set(read_palette_history())
    fresh = [p for p in pool if p not in recent] or pool
    key = f"palette|{family}|{style}|{seed}|{len(recent)}"
    idx = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % len(fresh)
    return fresh[idx]


def chunk_rows(chars, per_row):
    """按固定格数顺序切行（数字行用：10 个数字就是一行）。"""
    per_row = max(1, int(per_row))
    return [chars[i:i + per_row] for i in range(0, len(chars), per_row)]


def plan_rows(chars, rows_target):
    """把字符集切成「行行等长 + 末行不足则居中」的网格。

    26 个字切 5 行不可能行行等长（6/5/5/5/5 一定会有一行多一个，右边缘就戳出去），
    所以改成**固定列数**：列数 = ceil(字数 / 目标行数)（26 → 6 列、26+10 → 8 列），
    前几行一律排满同一宽度的矩形，剩下的字放最后一行并水平居中，
    看起来像「字母表排完了」的收尾，而不是某一行多戳出一个字。
    """
    if not chars:
        return []
    per_row = max(MIN_CHARS_PER_ROW, -(-len(chars) // max(1, int(rows_target))))
    return chunk_rows(chars, per_row)

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
    left, top, right, bottom = f.getbbox(ch)
    canvas = Image.new("L", (max(1, right-left)+4, max(1, bottom-top)+4), 0)
    ImageDraw.Draw(canvas).text((2-left, 2-top), ch, font=f, fill=255)
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
def render(font_path, out_path, word, sentence, style, palette_name, digits, width, desc, seed, grid_rows="auto", grid_adaptive=False, headline_scale=1.0):
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
        palette_name = pick_auto_palette(Path(font_path).stem, style, seed)
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
    cap_h = H * 0.150 * headline_scale
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

    line_factor = 1.24 if headline_scale == 1.0 else 1.08
    block_h = len(lines) * cap_h * line_factor
    y = max(H * 0.06, (H * 0.44 - block_h) / 2 + H * 0.03)
    if headline_scale != 1.0:
        y = H * 0.035
    spacing_report = []
    headline_top = y
    for ln, (placed, w) in zip(lines, layouts):
        draw_layout(canvas, placed, (W - w) / 2, y, fg)
        gmin, gmax = ink_gaps(placed)
        spacing_report.append(dict(line=ln, width=int(w), ink_h=round(cap_h), y=round(y), ink_gap_min=round(gmin, 2),
                                   ink_gap_max=round(gmax, 2)))
        y += cap_h * line_factor

    # ---- 大字下方：一句随机标语（也用字体本身排，字距统一）----
    sent = sentence
    if not any(c.islower() for c in ttf_charset):
        sent = sent.upper()
    elif not any(c.isupper() for c in ttf_charset):
        sent = sent.lower()
    cap_sent = min(H * 0.040, max(H * 0.022, (H * 0.050) * (len(sent) / 24) ** -0.35))
    cap_sent *= headline_scale
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
    # Keep the complete enlarged headline safely above the divider.
    overflow = sent_y + round(cap_sent) - (int(H * 0.545) - 20)
    if headline_scale != 1.0 and overflow > 0:
        raise ValueError("Headline exceeds vertical safe area; reduce --headline-scale")
    draw_layout(canvas, placed_s, (W - w_s) / 2, sent_y, fg)
    gmin, gmax = ink_gaps(placed_s)
    spacing_report.append(dict(line=sent, width=int(w_s), ink_h=round(cap_sent), y=round(sent_y),
                               ink_gap_min=round(gmin, 2), ink_gap_max=round(gmax, 2)))

    # ---- 通栏分割线：颜色与字体一致 ----
    div_y = int(H * 0.545)
    div_h = max(3, int(round(H * 0.006)))
    ImageDraw.Draw(canvas).rectangle([0, div_y, W, div_y + div_h - 1], fill=fg)

    # ---- 下半：字母 / 数字网格（每格等大）----
    show_upper = up
    show_low = low if (up or not low) else low
    letter_sets = [st for st in (show_upper, show_low) if st]
    digit_set = nums if (digits and nums) else []
    single_case = len(letter_sets) == 1

    if single_case:
        # 只有一种大小写时（最常见：只有大写 A–Z），
        # 26 个字母排两行会在下半留出一大片空白、字母也被挤小。
        # 更饱满的做法：字 + 数字合成一条流，均分到 5 行（26 → 6/5/5/5/5）。
        flow = list(letter_sets[0]) + digit_set if letter_sets else list(digit_set)
        grid_rows_sets = [flow] if flow else []
        rows_target = GRID_ROWS_SINGLE_CASE
    else:
        grid_rows_sets = letter_sets + ([digit_set] if digit_set else [])
        rows_target = GRID_ROWS_MULTI_CASE
    if grid_rows != "auto":
        rows_target = int(grid_rows)

    grid_left = W * 0.075
    grid_w = W * 0.85
    top = div_y + div_h + int(H * 0.035)
    bottom = H - int(H * 0.050)

    rows = []
    if single_case:
        for s_ in grid_rows_sets:
            rows.extend(plan_rows(s_, rows_target))
    else:
        for s_ in letter_sets:
            # 大小写都有：每套 13 格/行（26 个字正好两行，边缘是齐的）
            rows.extend(chunk_rows(s_, 13 if grid_rows == "auto" else -(-len(s_) // rows_target)))
        if digit_set:
            # 数字永远按 13 格/行切（10 个数字就一行，别摊成两行小数字）
            rows.extend(chunk_rows(digit_set, 13))
    per_row = max(len(r) for r in rows) if rows else 1
    cell_w = grid_w / per_row
    n_chars = max(len(s_) for s_ in grid_rows_sets) if grid_rows_sets else 0
    row_h = (bottom - top) / max(1, len(rows))

    # 候选字高：受行高和「最宽的字不能溢出格子」双重限制，所有字共用同一个高度
    probe = {}
    probe_h = row_h * 0.9
    for ch in {c for s_ in grid_rows_sets for c in s_}:
        m = glyph_mask(font_path, ch, int(probe_h * 2.2))
        if m is not None:
            probe[ch] = (m.width / m.height)
    widest_ratio = max(probe.values()) if probe else 1.0
    row_fill = 0.78 if len(rows) >= 3 else 0.70
    ink_h = min(row_h * row_fill, (cell_w * 0.86) / max(widest_ratio, 0.01))
    if grid_adaptive:
        gap = max(1, round(W * 0.016))
        ink_h = min(row_h * 0.70, *(
            (grid_w - gap * (len(row) - 1)) / sum(probe[c] for c in row)
            for row in rows))
        ink_h = int(ink_h)
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
                   "row_h": round(row_h_used, 1), "ink_h": round(ink_h, 1), "row_characters": ["".join(row) for row in rows], "cells": {}}

    for ri, row in enumerate(rows):
        row_top = y_start + ri * row_h_used
        n = len(row)
        # 每行都水平居中：26 个字均分 5 行必然有几行少一个，
        # 左对齐会让多出来的那个字单侧凸出去，居中后是左右各半个格，看起来才对称
        off = (per_row - n) * cell_w / 2
        adaptive_masks = {}
        if grid_adaptive:
            adaptive_masks = {ch: normalize_h(glyph_mask(font_path, ch, int(ink_h * 2.4)), ink_h) for ch in row}
            row_width = sum(m.width for m in adaptive_masks.values()) + gap * (n - 1)
            cursor = round((W - row_width) / 2)
        for ci, ch in enumerate(row):
            m = glyph_mask(font_path, ch, int(ink_h * 2.4))
            if m is None:
                continue
            m = normalize_h(m, ink_h)
            cx = grid_left + off + ci * cell_w + (cell_w - m.width) / 2
            if grid_adaptive:
                m = adaptive_masks[ch]
                cx = cursor
                cursor += m.width + gap
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
        grid_rows=grid_rows, grid_adaptive=grid_adaptive, headline_scale=headline_scale,
        divider_clearance=div_y - (round(sent_y) + round(cap_sent)),
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
            out.append(dict(y=y, gap_min=min(gaps), gap_max=max(gaps), n=len(items)))
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
    ap.add_argument("--palette", default="auto",
                    help="配色名（115 套：forest/fiery/… 或 底色_字色 如 deep_teal_prism_pink），"
                         "或 auto（按风格随机且避开最近用过的），或 all（每套各出一张）")
    ap.add_argument("--digits", default="on", choices=["on", "off"])
    ap.add_argument("--desc", default=DEFAULT_DESC)
    ap.add_argument("--width", type=int, default=1688)
    ap.add_argument("--grid-rows", default="auto",
                    help="字母/数字均分 N 行；auto = 只有一种大小写 5 行、大小写都有各 2 行")
    ap.add_argument("--grid-adaptive", action="store_true")
    ap.add_argument("--headline-scale", type=float, default=1.0)
    args = ap.parse_args()
    if args.grid_rows != "auto":
        try:
            args.grid_rows = int(args.grid_rows)
            assert 1 <= args.grid_rows <= 26
        except (ValueError, AssertionError):
            ap.error("--grid-rows must be auto or an integer from 1 to 26")
    if args.headline_scale <= 0:
        ap.error("--headline-scale must be positive")

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
                      args.digits == "on", args.width, args.desc, args.seed,
                      args.grid_rows, args.grid_adaptive, args.headline_scale)
        meta["words"] = picked
        metas.append(meta)
        if args.palette != "all":
            remember_palette(meta["palette"])
        print(f"[specimen] {outp}  palette={meta['palette']} ({meta['pantone']})  "
              f"网格 {meta['grid']['rows']} 行 × {meta['grid']['per_row']} 格  "
              f"字高一致性 {meta['ink_heights_unique']}  {meta['verdict']}")
        for sp in meta["top_spacing"]:
            print(f"   行「{sp['line']}」墨迹间隙 {sp['ink_gap_min']}–{sp['ink_gap_max']} px（固定值，理想差 0）")

    Path(str(args.out)).with_suffix(".json").write_text(json.dumps(metas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
