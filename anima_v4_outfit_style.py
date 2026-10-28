# -*- coding: utf-8 -*-
"""V3 的**服装智配层**（v3.19.0）。

两件事，各自一套表：

  ① 风格智配 —— 给服装六类（outfit / top / bottom / socks / shoes / accessory）
     的每条选项打 1–2 个风格标；抽到"定调单品"后，其余部位按**风格亲和度**
     加权（软约束），并对**物理上不可能**的组合硬剔除（铁律）。

  ② 颜色合成 —— 独立颜色字段 `cloth_color` 抽到后，把颜色**拼进**目标单品的
     第一个 tag（`purple` + `thighhighs` → `purple thighhighs`）。
     组合 tag 是否真实存在由 `presets/anima_v4_color_matrix.json` 离线判定
     （safebooru post_count ≥ 30），未命中则**放弃着色**并回显原因 ——
     宁可没有颜色，也不吐无效 tag。

**为什么单独一个文件**：这两张表都是纯人工维护的**语义知识**，会随词库增删
持续调整。rules.py 只调下面这几个函数，不关心表长什么样（与 anima_v4_link.py
同一套设计哲学）。

**为什么用"禁止/加权"而不是"只允许"**：黑名单在词库增删时是安全的 ——
新增一条选项默认"不受约束"，忘更新表只是少一条约束；
白名单会让新选项**默认被排除**，表现就是"我加了词条却抽不到"。

⚠️ 表里的键与值一律用**英文原文**（与 pools 的 `en` 逐字一致，含逗号与空格）。
   `tests/check_v3_color.py` 会断言"表里每个键都真实存在于词库"。
"""
from __future__ import annotations

import json
import os

# ===========================================================================
# 一、风格体系
# ===========================================================================
#
# 9 个风格组。刻意做得**粗**：组太细会让每条词条都能"自成一派"，
# 亲和度失去意义；9 组正好覆盖词库里的全部服装语义。
#
STYLES = [
    ("academic", "学院"),
    ("office", "职场"),
    ("traditional", "传统"),
    ("sporty", "运动"),
    ("casual", "日常"),
    ("home", "居家"),
    ("night", "夜店"),
    ("fantasy", "奇幻"),
    ("swim", "泳装"),
    # v3.38.0 新增 4 组亚文化风格。与上面 9 组（按"场合"切）不同，这 4 组按
    # "风格流派"切，所以同一个单品可以同时挂两组标（`gothic lolita` 既是哥特
    # 也是洛丽塔），互相不排斥 —— `_styles_of` 返回的是集合，锚点命中任一个
    # 都能吃到 SAME_STYLE_BOOST。
    ("gothic", "哥特"),
    ("lolita", "洛丽塔"),
    ("punk", "朋克"),
    ("techwear", "战术风"),
    # v3.38.0 再补 3 组：亚文化细分。判据是"词库里有足够能当定调单品的整套服装"，
    # 没有 outfit 支撑的风格加进来只会 fail-open（选了没效果），所以宁缺勿滥。
    ("jirai", "暗黑少女"),
    ("gyaru", "辣妹"),
    ("maid", "女仆"),
]

STYLE_ZH = dict(STYLES)
STYLE_OF_KEY = {zh: k for k, zh in STYLES}

#: 控件「服装风格」的取值（第一个是默认）。「随机」= 智能匹配开、锚点自动；
#: 「不限」= 智能匹配整体关闭（回到 v3.18 的行为，便于对照复现）。
STYLE_CHOICES = ["随机", "不限"] + [zh for _k, zh in STYLES]

#: 抽到与锚点**同风格**时的权重倍数。2.2 是实测手感：
#: 再高会让整套服装塌成一种风格（失去随机多样性），再低则看不出差别。
SAME_STYLE_BOOST = 2.2
#: 完全不相干的两个风格组之间的倍数（不归零 —— 用户要的是"合理"不是"死板"）
FAR_STYLE_FACTOR = 0.35

#: 组间兼容度（无序对）。未列出的对 = FAR_STYLE_FACTOR。
STYLE_COMPAT: dict[tuple, float] = {
    ("academic", "casual"): 0.75,
    ("academic", "sporty"): 0.85,
    ("academic", "swim"): 0.60,
    ("office", "casual"): 0.70,
    ("office", "night"): 0.50,
    ("casual", "sporty"): 0.85,
    ("casual", "home"): 0.80,
    ("casual", "night"): 0.75,
    ("casual", "swim"): 0.65,
    ("casual", "traditional"): 0.50,
    ("night", "fantasy"): 0.75,
    ("night", "swim"): 0.60,
    ("traditional", "fantasy"): 0.40,
    ("office", "home"): 0.40,
    # v3.38.0 新组与既有组的兼容度（未列出的对仍是 FAR_STYLE_FACTOR 0.35）
    ("gothic", "night"): 0.85,
    ("gothic", "lolita"): 0.80,
    ("gothic", "fantasy"): 0.55,
    ("gothic", "casual"): 0.45,
    ("gothic", "academic"): 0.40,
    ("lolita", "academic"): 0.60,
    ("lolita", "casual"): 0.55,
    ("lolita", "fantasy"): 0.65,
    ("punk", "night"): 0.70,
    ("punk", "casual"): 0.65,
    ("punk", "sporty"): 0.55,
    ("punk", "techwear"): 0.70,
    ("techwear", "sporty"): 0.75,
    ("techwear", "casual"): 0.70,
    ("techwear", "office"): 0.45,
    ("jirai", "gothic"): 0.80,
    ("jirai", "night"): 0.75,
    ("jirai", "lolita"): 0.65,
    ("jirai", "casual"): 0.60,
    ("gyaru", "casual"): 0.75,
    ("gyaru", "night"): 0.65,
    ("gyaru", "swim"): 0.55,
    ("maid", "fantasy"): 0.80,
    ("maid", "lolita"): 0.65,
    ("maid", "home"): 0.60,
}

#: 每条选项的风格标。空字符串 = **中性**（不参与锚定、也不被约束）。
#: 中性是刻意留的：赤足 / 裸腿 / 缠胸布这类"没有风格倾向"的东西，
#: 强行归类反而会让搭配变窄。
STYLE_OF: dict[str, dict[str, str]] = {
    # ── ⑥ 整套服装 ──────────────────────────────────────────
    "outfit": {
        "school uniform": "academic",
        "serafuku": "academic",
        "office lady": "office",
        "maid": "fantasy",
        "china dress": "traditional",
        "kimono": "traditional",
        "yukata": "traditional",
        "bunny girl": "night",
        "dress": "casual",
        "camisole dress": "casual",
        "evening gown": "office",
        "wedding dress": "office",
        "one-piece swimsuit": "swim",
        "bikini": "swim",
        "micro bikini": "swim night",
        "competitive swimsuit": "swim sporty",
        "gym uniform": "academic sporty",
        "cheerleader uniform": "academic sporty",
        "nurse": "office",
        "miko": "traditional",
        "police uniform": "office",
        "flight attendant uniform": "office",
        "gothic lolita": "night",
        "jirai kei": "night",
        "ryousangata": "night",
        "gyaru": "night",
        "idol costume": "fantasy",
        "sweater and skirt": "casual",
        "hoodie and shorts": "casual",
        "apron only": "home",
        "bath towel": "home",
        "sleeping kimono": "home",
        "sarashi": "",
        "school swimsuit": "swim academic",
        "competition school swimsuit": "swim sporty",
        "old school swimsuit": "swim academic",
        "new school swimsuit": "swim academic",
        "white bikini": "swim",
        "sports bikini": "swim sporty",
        "halterneck": "swim",
        "bikini top only": "swim",
        "sundress": "casual",
        "sweater dress": "casual",
        "sailor dress": "academic",
        "sleeveless dress": "casual",
        "pinafore dress": "casual",
        "bubble skirt": "casual",
        "hanfu": "traditional",
        "hakama": "traditional",
        "suit": "office",
        "tuxedo": "office",
        "romper": "casual",
        "jumpsuit": "casual",
        "suspender skirt": "casual",
        "suspender shorts": "casual",
        # v3.19.0 新增
        "race queen": "night sporty",
        "magical girl": "fantasy",
        "teacher": "office",
        "military uniform": "fantasy",
        "cyberpunk": "fantasy",
        "ballerina": "fantasy",
        "nun": "fantasy",
        "knight": "fantasy",
        "track suit": "sporty",
        "ninja": "fantasy",
        "witch": "fantasy",
        "vampire": "fantasy",
        "waitress": "office",
        "bartender": "office",
        "leotard": "sporty",
    },
    # ── 上装与外套 ──────────────────────────────────────────
    "top": {
        "t-shirt": "casual",
        "shirt": "office",
        "blouse": "office",
        "sailor shirt": "academic",
        "polo shirt": "casual sporty",
        "sweater": "casual",
        "turtleneck": "casual",
        "off-shoulder sweater": "night",
        "cardigan": "casual",
        "sweater vest": "academic",
        "vest": "casual",
        "hoodie": "casual",
        "crop top": "night",
        "tank top": "casual",
        "camisole": "night",
        "tube top": "night",
        "sleeveless shirt": "casual",
        "sports bra": "sporty",
        "puffy sleeves": "casual",
        "leather jacket": "night",
        "denim jacket": "casual",
        "bomber jacket": "casual",
        "jacket": "casual",
        "trench coat": "office",
        "coat": "office",
        "blazer": "office",
        "fur coat": "night",
        "fur-trimmed coat": "night",
        "cape": "fantasy",
        "poncho": "casual",
        # v3.19.0 新增
        "frilled shirt": "casual",
        "off-shoulder shirt": "night",
        "cropped hoodie": "casual",
        "down jacket": "casual",
        "military jacket": "fantasy",
        "halterneck": "night",
        "bathrobe": "home",
        "techwear": "fantasy",
        "fur collar": "night",
        "capelet": "casual",
    },
    # ── 下装 ────────────────────────────────────────────────
    "bottom": {
        "jeans": "casual",
        "shorts": "casual",
        "short shorts": "night",
        "denim shorts": "casual",
        "gym shorts": "sporty",
        "high-waist shorts": "casual",
        "bike shorts": "sporty",
        "pleated skirt": "academic",
        "miniskirt": "night",
        "skirt": "casual",
        "pencil skirt": "office",
        "long skirt": "casual",
        "denim skirt": "casual",
        "cargo pants": "casual",
        "track pants": "sporty",
        "high-waist pants": "casual",
        "yoga pants": "sporty",
        "leggings": "sporty",
        "overalls": "casual",
        "bloomers": "sporty",
        "harem pants": "casual",
        "capri pants": "casual",
        "sarong": "casual",
        "corset": "night",
        "bustier": "night",
        "thong": "night",
        "g-string": "night",
        "swim briefs": "swim",
        "sweater around waist": "casual",
        # v3.19.0 新增
        "a-line skirt": "casual",
        "tennis skirt": "sporty",
        "cargo skirt": "casual",
        "frilled skirt": "night",
        "wide-leg pants": "office",
        "jodhpurs": "sporty",
        "skort": "sporty",
        "leather pants": "night",
        "suit pants": "office",
        "high-waist skirt": "office",
    },
    # ── 腿上 ────────────────────────────────────────────────
    "socks": {
        "black thighhighs": "night",
        "white thighhighs": "academic",
        "pantyhose": "office",
        "ankle socks": "casual",
        "barefoot": "",
        "garter straps": "night",
        "fishnet thighhighs": "night",
        "black pantyhose": "office",
        "white pantyhose": "office",
        "fishnet pantyhose": "night",
        "argyle pantyhose": "academic",
        "laddered pantyhose": "night",
        "striped thighhighs": "casual",
        "kneehighs": "academic",
        "single thighhigh": "night",
        "loose socks": "academic",
        # v3.19.0 新增
        "thighhighs": "night",
        "thighhighs, garter straps": "night",
        "lace-trimmed thighhighs, garter straps": "night",
        "fishnet thighhighs, garter straps": "night",
        "purple thighhighs, garter straps": "night",
        "red thighhighs, garter straps": "night",
        "black thighhighs, garter straps": "night",
        "white thighhighs, garter straps": "night",
        "lace-trimmed thighhighs": "night",
        "leg warmers": "home",
        "tabi": "traditional",
        "frilled socks": "academic",
        "white socks": "academic",
        "striped socks": "casual",
        "toeless legwear": "casual",
        "lace pantyhose": "night",
        "crotchless pantyhose": "night",
        "torn pantyhose": "night",
        # ── v3.20.0 腿上扩章（32 条）────────────────────────────
        # ⚠️ 彩色固化款的风格必须与它的基类一致（过膝袜=夜场、连裤袜=职场、
        #    短袜=日常），否则同款不同色会被智配分到不同风格里去。
        "torn thighhighs": "night",
        "bodystocking": "night",
        "fishnet bodystocking": "night",
        "black bodystocking": "night",
        "pantyhose, garter belt": "office",
        "pantyhose, garter straps": "office",
        "latex thighhighs": "night",
        "gradient thighhighs": "night",
        "shiny pantyhose": "night",
        # v3.42.23：织入亮丝细碎星点的三色连裤袜 —— 与 `shiny pantyhose`
        # 同归「夜店」（闪亮材质 = 夜场单品），不另开风格
        "black glittery pantyhose": "night",
        "white glittery pantyhose": "night",
        "pale pink glittery pantyhose": "night",
        "lavender glittery pantyhose": "night",
        "pale burgundy glittery pantyhose": "night",
        # v3.42.25：同样的亮丝星点材质补到长筒袜 —— 五色过膝袜 + 五色吊带版，
        # 一律归「夜店」（与 pantyhose 版同组）
        "black glittery thighhighs": "night",
        "white glittery thighhighs": "night",
        "pale pink glittery thighhighs": "night",
        "lavender glittery thighhighs": "night",
        "pale burgundy glittery thighhighs": "night",
        "black glittery thighhighs, garter straps": "night",
        "white glittery thighhighs, garter straps": "night",
        "pale pink glittery thighhighs, garter straps": "night",
        "lavender glittery thighhighs, garter straps": "night",
        "pale burgundy glittery thighhighs, garter straps": "night",
        "ribbed socks": "casual",
        "fishnet socks": "night",
        "asymmetrical legwear": "night",
        "mismatched legwear": "night",
        "bow legwear": "academic",
        "ribbon legwear": "casual",
        "socks over pantyhose": "academic",
        "no-show socks": "casual",
        "lace-trimmed socks": "casual",
        "thighhighs over pantyhose": "night",
        "layered legwear": "casual",
        "purple thighhighs": "night",
        "red thighhighs": "night",
        "blue thighhighs": "night",
        "pink thighhighs": "night",
        "purple pantyhose": "office",
        "red pantyhose": "office",
        "blue pantyhose": "office",
        "pink pantyhose": "office",
        "purple socks": "casual",
        "red socks": "casual",
        "blue socks": "casual",
        "pink socks": "casual",
    },
    # ── 鞋子 ────────────────────────────────────────────────
    "shoes": {
        "high heels": "office",
        "mary janes": "academic",
        "sneakers": "casual sporty",
        "boots": "casual",
        "thigh boots": "night",
        "bare feet": "",
        "loafers": "academic",
        "sandals": "casual",
        "ankle boots": "casual",
        "knee boots": "casual",
        "high heel boots": "night",
        "geta": "traditional",
        "uwabaki": "academic",
        "slippers": "home",
    },
    # ── 配饰 ────────────────────────────────────────────────
    "accessory": {
        "necklace": "office",
        "choker": "night",
        "earrings": "office",
        "bracelet": "casual",
        "ring": "office",
        "wristwatch": "office",
        "glasses": "casual",
        "sunglasses": "casual",
        "beret": "casual",
        "straw hat": "casual",
        "scarf": "casual",
        "handbag": "office",
        "thigh strap": "night",
    },
}

#: 风格 → 该风格的字段**硬剔除**表。只收"穿在一起就是错的"，
#: 凡是"有点怪但现实里有人这么穿"的一律不收（交软加权去压）。
STYLE_BANS: dict[tuple, set] = {
    ("swim", "top"): {
        "down jacket", "coat", "fur coat", "fur-trimmed coat", "military jacket",
        "trench coat", "blazer", "sweater", "turtleneck", "cardigan", "hoodie",
        "leather jacket", "techwear", "bathrobe",
    },
    ("swim", "bottom"): {
        "jeans", "cargo pants", "suit pants", "wide-leg pants", "leather pants",
        "track pants", "yoga pants", "leggings", "long skirt", "high-waist pants",
        "jodhpurs",
    },
    ("swim", "socks"): {
        "pantyhose", "black pantyhose", "white pantyhose", "lace pantyhose",
        "argyle pantyhose", "kneehighs", "loose socks", "lace-trimmed thighhighs",
        "leg warmers", "tabi",
    },
    ("swim", "shoes"): {
        "thigh boots", "knee boots", "high heel boots", "loafers", "uwabaki",
        "slippers", "geta",
    },
    ("office", "socks"): {
        "loose socks", "frilled socks", "white socks", "torn pantyhose",
        "crotchless pantyhose",
    },
    ("office", "shoes"): {"sneakers", "geta", "uwabaki", "slippers", "bare feet"},
    ("traditional", "shoes"): {"sneakers", "thigh boots", "high heel boots"},
    ("home", "shoes"): {
        "high heels", "thigh boots", "knee boots", "high heel boots", "loafers",
    },
    ("sporty", "socks"): {
        "pantyhose", "lace pantyhose", "crotchless pantyhose", "argyle pantyhose",
    },
    ("academic", "shoes"): {"thigh boots", "high heel boots"},
}

#: 按**具体定调单品**的铁律（风格表兜不住的那些个例）。
ANCHOR_BANS: dict[str, dict] = {
    "wedding dress": {
        "shoes": {"sneakers", "geta", "uwabaki", "slippers", "bare feet"},
        "socks": {"loose socks", "frilled socks", "white socks", "torn pantyhose"},
    },
    "evening gown": {
        "shoes": {"sneakers", "geta", "uwabaki", "slippers", "bare feet", "boots"},
        "socks": {"loose socks", "frilled socks", "white socks"},
    },
    "hanfu": {"shoes": {"sneakers", "thigh boots", "high heel boots"}},
    "kimono": {"shoes": {"sneakers", "thigh boots", "high heel boots"}},
    "yukata": {"shoes": {"sneakers", "high heel boots"}},
    "miko": {"shoes": {"sneakers", "high heel boots"}},
    "hakama": {"shoes": {"sneakers"}},
    "bikini": {"top": {"down jacket", "coat", "sweater", "turtleneck",
                       "military jacket"}},
    "micro bikini": {"top": {"down jacket", "coat", "sweater", "turtleneck",
                             "military jacket", "cardigan", "blazer"}},
    "one-piece swimsuit": {"top": {"down jacket", "coat", "sweater", "turtleneck",
                                   "blazer"}},
    "school uniform": {"shoes": {"thigh boots", "high heel boots"}},
    "nun": {"top": {"crop top", "tube top", "camisole", "sports bra"}},
}


# ===========================================================================
# 二、颜色词与合成矩阵
# ===========================================================================

#: 颜色字段的英文值（与词库 cloth_color 的 en 逐字一致）。
#: ⚠️ 只有这 12 个是 danbooru 真实的基础颜色 tag —— `navy blue / burgundy /
#:    dark green / beige / teal / lavender / champagne / silver` 全部实测
#:    37/37 组合失效（矩阵见 presets/anima_v4_color_matrix.json），
#:    留着它们等于让"着色"永远走退化分支，是假功能。
COLOR_TAGS = [
    "black", "white", "grey", "red", "orange", "yellow",
    "green", "aqua", "blue", "purple", "pink", "brown",
]

COLOR_ZH = {
    "black": "黑色", "white": "白色", "grey": "灰色", "red": "红色",
    "orange": "橙色", "yellow": "黄色", "green": "绿色", "aqua": "青色",
    "blue": "蓝色", "purple": "紫色", "pink": "粉色", "brown": "棕色",
}

#: 颜色合成的目标优先级 —— 越靠前越"具体"。
#: 袜子 > 下装 > 上装 > 整套：同时抽到「过膝袜 + 裙子 + 整套校服」时，
#: 颜色落在袜子上，因为它是画面里最容易被颜色识别的单品（也是用户点名的场景）。
#: v3.20.0：颜色拆成**两个独立通道** —— 各管各的部位，互不抢落点。
#:
#:   sock_color  → 只管 socks（腿上）
#:   cloth_color → 只管 bottom / top / outfit（身上）
#:
#: 为什么必须拆：v3.19.0 把 socks 放在 cloth_color 的第一个落点，于是
#: 「紫色连衣裙」经常被抽成「紫袜子 + 素裙子」—— 袜子和裙子是两个独立的
#: 视觉块，硬塞同一个颜色反而更不协调。现在想给袜子单独配色就填 sock_color。
SOCK_COLOR_TARGETS = ("socks",)
BODY_COLOR_TARGETS = ("bottom", "top", "outfit")

_MATRIX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "presets", "anima_v4_color_matrix.json")
_MATRIX = None


def matrix() -> dict:
    """颜色×款式有效矩阵（懒加载）。文件缺失 → 空矩阵（全部走退化）。"""
    global _MATRIX
    if _MATRIX is None:
        try:
            with open(_MATRIX_PATH, "r", encoding="utf-8") as fh:
                _MATRIX = (json.load(fh) or {}).get("matrix", {})
        except Exception:
            _MATRIX = {}
    return _MATRIX


def combo_ok(color: str, garment: str) -> bool:
    """`{color} {garment}` 是否是可用的真实组合 tag。"""
    row = matrix().get(str(color or "").strip().lower())
    if not isinstance(row, dict):
        return False
    cell = row.get(str(garment or "").strip().lower())
    return bool(isinstance(cell, dict) and cell.get("ok"))


def has_color_tag(value: str) -> bool:
    """这个字段值里是否已经带了颜色（`black thighhighs` 之类）。"""
    for t in str(value or "").split(","):
        t = t.strip().lower()
        if not t:
            continue
        for c in COLOR_TAGS:
            if t == c or t.startswith(c + " "):
                return True
    return False


# ===========================================================================
# 三、对外 API（rules.py 只用这几个）
# ===========================================================================

#: 「整套服装」里**不是**完整成套的那几个 —— 它们本来就该和别的衣服共存。
#: 其余 outfit 一律视为「完整成套」，抽到后再叠上装/下装就是三层衣服，
#: 模型会画成「连衣裙外面套衬衫再套裤子」（实测踩到过）。
OUTFIT_PARTIAL = {"apron only", "bath towel", "sleeping kimono", "sarashi",
                  "bikini top only"}

#: 整套服装已定调时，上装 / 下装的权重倍数。
#: 不归零：保留"外套敞开 + 内搭"这种合理的层叠可能性（0.06 时大约每 16 次
#: 抽到一次，出片是加分项而不是噪音）。
LAYER_SUPPRESS = 0.06


def _styles_of(field_key: str, en: str) -> set:
    raw = (STYLE_OF.get(field_key) or {}).get(str(en or "").strip().lower(), "")
    return {s for s in raw.split() if s}


def style_of_value(field_key: str, en: str) -> set:
    return _styles_of(field_key, en)


#: 场景 → 风格（只登记**强关联**的，其余留空=不干预）。
#: 为什么场景也当锚点：泳池边穿大衣、教室里穿晚礼服，靠"随机"是抽得出
#: 但一眼就知道不对。场景是天然的定调器，而且它排在服装之前（draw 里
#: place 预抽），拿得到。
PLACE_STYLE = {
    "beach": "swim", "poolside": "swim", "onsen": "swim", "in bathtub": "swim",
    "showering": "swim", "waterfall": "swim", "underwater": "swim",
    "lake": "swim", "river": "swim",
    "bedroom": "home", "on bed": "home", "hotel room": "home",
    "bathroom": "home", "kitchen": "home", "apartment": "home",
    "balcony": "home",
    "classroom": "academic", "library": "academic", "rooftop": "academic",
    "office": "office", "elevator": "office",
    "shrine": "traditional",
    "bar (place)": "night", "concert": "night", "stage": "night",
    "stadium": "sporty",
    "church": "fantasy", "castle": "fantasy", "ruins": "fantasy",
    "cave": "fantasy", "graveyard": "fantasy", "lighthouse": "fantasy",
    "street": "casual", "crosswalk": "casual", "park": "casual",
    "garden": "casual", "forest": "casual", "field": "casual",
    "flower field": "casual", "mountain": "casual", "hill": "casual",
    "road": "casual", "bridge": "casual",
}


def resolve_choice(choice: str) -> str:
    """把控件的中文取值翻成风格 key。

    返回 ""（= 不干预）或具体风格 key 或 "auto"（自动锚定）。
    """
    c = str(choice or "").strip()
    if not c or c in ("不限", "随机"):
        return "" if c == "不限" else "auto"
    return STYLE_OF_KEY.get(c, "auto")


def anchor_of(state: dict, choice: str = "随机") -> tuple:
    """定调风格。返回 (style_key, 来源说明)；无法定调时 ("", "")。

    优先级：
      ① 控件指定了具体风格 → 就是它（用户显式选择，压过一切）
      ② 场景 → 风格（泳池边=泳装、教室=学院；拿得到是因为 place 预抽在服装前）
      ③ 已抽到的整套服装 outfit → 它的风格
      ④ 上装 top / 下装 bottom 的并集（取第一个）
    """
    picked = resolve_choice(choice)
    if picked and picked != "auto":
        return picked, "控件指定"
    if picked == "":
        return "", ""
    # ② 场景定调
    place = str(state.get("place") or "").strip().lower()
    ps = PLACE_STYLE.get(place, "")
    if ps:
        return ps, "场景"
    # ③④ 自动锚定：整套 > 上装 > 下装
    for key in ("outfit", "top", "bottom"):
        st = _styles_of(key, state.get(key))
        if st:
            return sorted(st)[0], "整套服装" if key == "outfit" else (
                "上装" if key == "top" else "下装")
    return "", ""


def style_bans(state: dict, field_key: str, choice: str = "随机") -> set:
    """当前锚点下，该字段禁止的取值（英文原文）。"""
    out: set = set()
    anchor, _src = anchor_of(state, choice)
    if not anchor:
        return out
    out |= set(STYLE_BANS.get((anchor, field_key)) or ())
    # 具体单品的铁律：无论是自动锚定还是控件指定，都按"实际抽到的整套"判
    outfit = str(state.get("outfit") or "").strip().lower()
    if outfit:
        out |= set((ANCHOR_BANS.get(outfit) or {}).get(field_key) or ())
    return out


def allowed_outfit(pool: list, choice: str) -> list:
    """控件**显式指定**风格时，整套服装做硬收敛（只留同风格 + 中性）。

    为什么整套要硬收敛、其它部位不用：整套服装是"定调单品"，它错了整张图
    就错了 —— 选「泳装」却抽出护士服，后面再怎么加权也救不回来。
    软加权压不住的原因是组内选项数量差异：swim 只有 10 条 ×2.2 = 22，
    其余 60 条 ×0.35 = 21，两者几乎打平（实测 4/4 全错）。

    「随机」/「不限」时**不做**任何过滤，保持软加权。
    """
    picked = resolve_choice(choice)
    if picked in ("", "auto"):
        return pool
    same = []
    for it in pool:
        # 候选池的元素是 (中文, 英文, 档位) —— 只按英文判风格，原样返回
        if picked in _styles_of("outfit", it[1]):
            same.append(it)
    # v3.38.0：有同风格候选时**不再混中性单品**（缠胸布 / 浴巾这类）。
    # 以前无条件放行中性，实测「辣妹」30 抽里有 7 抽出缠胸布 —— 中性单品的
    # 语义是"没有风格倾向"，放在一个强风格里就是穿错衣服。中性只在
    # "这个风格一条 outfit 都没有"时兜底，避免剔光后 fail-open 回原池。
    if same:
        return same
    neutral = [it for it in pool if not _styles_of("outfit", it[1])]
    return neutral or pool


def layer_bias(state: dict, field_key: str, choice: str = "随机") -> float:
    """整套服装已定调时压掉上装/下装（防三层叠穿）。

    ⚠️ 「不限」= 智配整体关闭，**连层级抑制也一起关** —— 否则"对照复现
       v3.18 行为"这句话就不成立（用户拿它当 A/B 开关用）。
    """
    if field_key not in ("top", "bottom"):
        return 1.0
    if resolve_choice(choice) == "":
        return 1.0
    outfit = str(state.get("outfit") or "").strip().lower()
    if outfit and outfit not in OUTFIT_PARTIAL:
        return LAYER_SUPPRESS
    return 1.0


def style_bias(state: dict, field_key: str, en: str, choice: str = "随机") -> float:
    """该选项在当前锚点下的权重倍数（1.0 = 不干预）。

    = 层级抑制（整套压上下装）× 风格亲和（同风格 2.2 / 兼容 0.4~0.85）。
    """
    lb = layer_bias(state, field_key, choice)
    anchor, _src = anchor_of(state, choice)
    if not anchor:
        return lb
    st = _styles_of(field_key, en)
    if not st:
        return lb                       # 中性单品不干预
    if anchor in st:
        base = lb * SAME_STYLE_BOOST
        # v3.38.7：同风格候选之间再分先后（只作用于整套服装）
        if field_key == "outfit":
            base *= outfit_prefer(anchor, en)
        return base
    best = 0.0
    for s in st:
        pair = (anchor, s) if (anchor, s) in STYLE_COMPAT else (s, anchor)
        best = max(best, float(STYLE_COMPAT.get(pair, FAR_STYLE_FACTOR)))
    return lb * best


def _apply_color(state: dict, field_key: str, targets, notes: list):
    """单个颜色字段的合成：从 targets 里挑第一个能着色的部位拼上去。"""
    color = str(state.get(field_key) or "").strip().lower()
    if not color:
        return
    state.pop(field_key, None)        # 颜色只以合成形式出现，绝不单飞

    target, first, why = "", "", ""
    for key in targets:
        val = str(state.get(key) or "").strip()
        if not val:
            continue
        head = val.split(",")[0].strip()
        if has_color_tag(head):
            if not why:
                why = ("颜色「%s」跳过：%s 已自带颜色（%s）"
                       % (COLOR_ZH.get(color, color), key, head))
            continue
        if not combo_ok(color, head):
            if not why:
                why = ("颜色「%s」跳过：`%s %s` 不是有效组合 tag（矩阵未收录）"
                       % (COLOR_ZH.get(color, color), color, head))
            continue
        target, first = key, head
        break

    if not target:
        # ⚠️ 不是所有款式都能着色：`kneehighs` 没有任何 `{color} kneehighs`
        #    组合 tag（12 色全失效）。这时**换下一个部位试**，实在没有就不上色。
        notes.append(why or ("颜色「%s」无落点（%s 没有可着色的单品），已跳过"
                             % (COLOR_ZH.get(color, color), "/".join(targets))))
        return

    parts = [p.strip() for p in str(state.get(target) or "").split(",") if p.strip()]
    if not parts:
        return
    parts[0] = "%s %s" % (color, first)
    state[target] = ", ".join(parts)
    notes.append("颜色合成：%s → %s（%s）"
                 % (COLOR_ZH.get(color, color), state[target], target))


def colorize(state: dict) -> list:
    """把两个颜色字段拼进各自的目标单品。**原地**改 state，返回说明列表。

    规则：
      · `sock_color` 只作用 socks；`cloth_color` 只作用 下装/上装/整套
      · 目标值已带颜色 → 跳过（老条目 `black thighhighs` 保留不动）
      · 目标值是多 tag（`thighhighs, garter straps`）→ 只给**第一个** tag 上色
      · 组合 tag 未经验证 → **不上色**，回显原因（宁缺勿错）
      · 两个颜色字段都不会单独输出（避免裸色 tag 串味）
    """
    notes: list = []
    _apply_color(state, "sock_color", SOCK_COLOR_TARGETS, notes)
    _apply_color(state, "cloth_color", BODY_COLOR_TARGETS, notes)
    return notes


def summary() -> dict:
    """给面板/自检用的一览（不做任何 IO 以外的副作用）。"""
    return {
        "styles": [{"key": k, "zh": zh} for k, zh in STYLES],
        "choices": list(STYLE_CHOICES),
        "same_boost": SAME_STYLE_BOOST,
        "far_factor": FAR_STYLE_FACTOR,
        "color_tags": list(COLOR_TAGS),
        "color_targets": list(COLOR_TARGETS),
        "matrix_colors": len(matrix()),
    }

# ===========================================================================
# v3.38.0：新增 4 个亚文化风格组的**增量标注**
# ===========================================================================
#
# 为什么用"追加合并"而不是直接改上面那张 242 条的大表：
#   上面那 9 组是经过实拍的搭配结果，手改容易一改坏一片。这里只写"要补什么标"，
#   加载时按词条合并（保序去重），既有标一律不动 —— `gothic lolita` 原来是
#   `night`，合并后是 `night gothic lolita`，夜场语义不丢。
#
# ⚠️ 每个新组都必须有**足够的整套服装（outfit）词条**：`allowed_outfit()` 在
#    控件显式指定风格时对 outfit 做硬收敛，只留"同风格 + 中性"。某个组一条
#    outfit 都没有的话，过滤结果为空 → fail-open 回原池 → 用户看到的是
#    "我选了哥特，它还是出护士服"。
_EXTRA_STYLE_OF: dict[str, dict[str, str]] = {
    "outfit": {
        "gothic lolita": "gothic lolita",
        # ⚠️ v3.38.5：`jirai kei`（地雷系）**不进哥特组**。实跑 6 张里 3 张抽到它，
        #    画面是"暗黑甜美"，用户判"这不是哥特"。它有自己的「暗黑少女」组。
        "jirai kei": "punk",
        "vampire": "gothic",
        # ⚠️ v3.38.1：`nun` / `witch` **不进**哥特组。实测选「哥特」抽出修女服，
        #    用户一眼判定"这不哥特" —— 它们是角色扮演（fantasy），不是风格流派。
        #    哥特只留 gothic lolita / jirai kei / vampire 三条整装载体。
        "ryousangata": "lolita",
        "pinafore dress": "lolita",
        "bubble skirt": "lolita",
        "sailor dress": "lolita academic",
        "cyberpunk": "punk techwear",
        "military uniform": "punk techwear",
        "jumpsuit": "techwear",
        "track suit": "techwear sporty",
    },
    "top": {
        "leather jacket": "gothic punk",
        "turtleneck": "gothic",
        "off-shoulder sweater": "gothic",
        "vest": "gothic",
        "cape": "gothic fantasy",
        "fur collar": "gothic",
        "blouse": "lolita",
        "frilled shirt": "lolita",
        "puffy sleeves": "lolita",
        "cardigan": "lolita casual",
        "capelet": "lolita",
        "sweater vest": "lolita academic",
        "bomber jacket": "punk techwear",
        "cropped hoodie": "punk techwear",
        "military jacket": "techwear",
        "techwear": "techwear",
        "hoodie": "techwear casual",
    },
    "bottom": {
        "corset": "gothic",
        "bustier": "gothic",
        "leather pants": "gothic punk",
        "pencil skirt": "gothic office",
        "long skirt": "gothic",
        "frilled skirt": "lolita",
        "a-line skirt": "lolita",
        "high-waist skirt": "lolita",
        "pleated skirt": "lolita academic",
        "cargo pants": "punk techwear",
        "miniskirt": "punk",
        "denim shorts": "punk casual",
        "cargo skirt": "techwear",
        "leggings": "techwear sporty",
        "track pants": "techwear sporty",
        "bike shorts": "techwear sporty",
    },
    "socks": {
        "fishnet thighhighs": "gothic punk",
        "lace-trimmed thighhighs": "gothic lolita",
        "black thighhighs": "gothic",
        "bodystocking": "gothic",
        "black pantyhose": "gothic",
        "white thighhighs": "lolita",
        "kneehighs": "lolita",
        "frilled socks": "lolita",
        "lace-trimmed socks": "lolita",
        "loose socks": "lolita academic",
        "torn thighhighs": "punk",
        "fishnet socks": "punk",
        "torn pantyhose": "punk",
        "ankle socks": "techwear sporty",
        "no-show socks": "techwear",
    },
    "shoes": {
        "high heels": "gothic night",
        "boots": "gothic punk",
        "thigh boots": "gothic",
        "ankle boots": "gothic lolita punk",
        "high heel boots": "gothic punk",
        "mary janes": "lolita",
        "sneakers": "techwear sporty",
    },
    "accessory": {
        "choker": "gothic lolita punk",
        "thigh strap": "gothic punk",
        "earrings": "gothic",
        "necklace": "lolita gothic",
        "beret": "lolita",
        "sunglasses": "punk techwear",
        "wristwatch": "techwear office",
        "glasses": "techwear",
        "handbag": "techwear lolita",
    },
}

for _fk, _m in _EXTRA_STYLE_OF.items():
    _cur = STYLE_OF.setdefault(_fk, {})
    for _en, _add in _m.items():
        _old = _cur.get(_en, "")
        _cur[_en] = " ".join(dict.fromkeys((_old + " " + _add).split()))

# ---------------------------------------------------------------------------
# v3.38.0 第二批：地雷系 / 辣妹 / 女仆
# ---------------------------------------------------------------------------
# 这三组的 outfit 基数分别是 2 / 2+1 / 2 条 —— 少是**刻意的**：它们本来就是
# 窄风格，硬塞宽泛单品会把"地雷系"稀释成"随便一件暗色衣服"。其余部位补得宽，
# 保证锚定之后上装/下装/袜子/鞋子/配饰都有得挑。
_EXTRA_STYLE_OF_2: dict[str, dict[str, str]] = {
    "outfit": {
        "jirai kei": "jirai",
        "ryousangata": "jirai",
        # v3.38.7（方案 A）：只用日系地雷/量产型当载体，模型画出来是**白色蕾丝甜系**
        # （实跑 4 张全是白衬衫 + 蓝裙 + 花朵发饰），"暗黑少女"名不副实。
        # 补两条真正暗黑的载体：哥特萝莉 + 吸血鬼装，地雷系退为调剂。
        "gothic lolita": "jirai",
        "vampire": "jirai",
        "gyaru": "gyaru",
        "camisole dress": "gyaru",
        "micro bikini": "gyaru",
        "maid": "maid",
        "apron only": "maid",
    },
    "top": {
        "off-shoulder sweater": "jirai",
        "cardigan": "jirai",
        "cropped hoodie": "jirai",
        "frilled shirt": "jirai",
        "camisole": "gyaru",
        "tube top": "gyaru",
        "crop top": "gyaru",
        "off-shoulder shirt": "gyaru",
        "puffy sleeves": "maid",
        "blouse": "maid",
        "capelet": "maid",
    },
    "bottom": {
        "miniskirt": "jirai gyaru",
        "pleated skirt": "jirai",
        "high-waist skirt": "jirai",
        "denim shorts": "gyaru",
        "high-waist shorts": "gyaru",
        "short shorts": "gyaru",
        "a-line skirt": "maid",
        "frilled skirt": "maid",
    },
    "socks": {
        "black thighhighs": "jirai",
        "loose socks": "jirai gyaru",
        "kneehighs": "jirai",
        "ankle socks": "gyaru",
        "white thighhighs": "maid",
        "frilled socks": "maid",
    },
    "shoes": {
        "ankle boots": "jirai",
        "high heel boots": "jirai",
        "sneakers": "gyaru",
        "high heels": "gyaru",
        "mary janes": "maid",
    },
    "accessory": {
        "choker": "jirai",
        "earrings": "jirai gyaru",
        "handbag": "jirai gyaru maid",
        "sunglasses": "gyaru",
        "necklace": "maid",
        "beret": "maid",
    },
}

for _fk, _m in _EXTRA_STYLE_OF_2.items():
    _cur = STYLE_OF.setdefault(_fk, {})
    for _en, _add in _m.items():
        _old = _cur.get(_en, "")
        _cur[_en] = " ".join(dict.fromkeys((_old + " " + _add).split()))

# ===========================================================================
# v3.38.0：妆容跟随风格（智配原本只管服装六类，妆容是独立随机）
# ===========================================================================
#
# 为什么必须补这一层：用户选「哥特」跑出来的图，服装是 nun + leather jacket，
# 妆容却是 `no makeup` —— 因为 `makeup` 不在 STYLE_OF 里，`style_bias` 对它
# 返回 1.0，等于完全不受风格影响。服装对了妆不对，整张图仍然不成立。
#
# 值必须是 `makeup` 字段里**真实存在的选项原文**（check_v3_color 会校验）。
STYLE_MAKEUP: dict[str, list[str]] = {
    # ⚠️ v3.38.5：哥特必须真的"哥特"。原来这组里塞了 `mole under eye`（泪痣）——
    #    它把命中率刷上去了，但语义上是中系/日常妆，用户一眼判"这不是哥特妆"。
    #    现在改成**分层权重**：完整哥特组合妆 > 黑唇 > 眼影，泪痣彻底移出。
    #    数值 = 该选项的权重倍数；不在表里的按 STYLE_MAKEUP_FAR 处理。
    "gothic": {
        "pale skin, black lipstick, eyeshadow": 12.0,
        "black lipstick": 4.0,
        "eyeshadow": 2.0,
    },
    "lolita": ["light makeup", "blush", "glossy lips", "bitten lip"],
    "punk": {
        "black lipstick": 5.0, "eyeshadow": 4.0, "facepaint": 3.0,
        "eyeliner": 1.5,
    },
    "techwear": ["no makeup", "eyeliner"],
    # 地雷系同理：完整的地雷妆（黑眼圈+腮红+眼线+水光唇）优先，泪痣只是配角
    # ⚠️ v3.38.6：用户反馈"暗黑少女不够暗黑，妆容也要复合"。
    #    原表只有地雷妆（黑眼圈+腮红+水光唇）——那套偏"病态可爱"，脸上是亮的。
    #    现在把 `eyeshadow`（暗色眼影，最直接的"暗"）提到 6，水光唇从 2 压到 0.4，
    #    让"暗色眼妆"和"地雷妆"平分，整体脸色沉下来。
    "jirai": {
        "eyebags, blush, eyeliner, glossy lips": 6.0,
        "eyeshadow": 6.0,
        "eyeliner": 2.0,
        "blush": 1.0,
        "glossy lips": 0.4,
        "mole under eye": 0.4,
    },
    "gyaru": ["thick eyelashes", "glossy lips", "colored eyelashes", "blush"],
    "maid": ["light makeup", "blush", "glossy lips"],
    "academic": ["light makeup", "blush", "bitten lip"],
    "office": ["red lipstick", "light makeup", "eyeliner"],
    "traditional": ["red lipstick", "light makeup"],
    "sporty": ["no makeup", "light makeup"],
    "casual": ["light makeup", "glossy lips", "freckles"],
    "home": ["no makeup", "light makeup"],
    "night": ["red lipstick", "eyeshadow", "glossy lips", "thick eyelashes"],
    "fantasy": ["eyeshadow", "colored eyelashes", "glitter"],
    "swim": ["no makeup", "glossy lips"],
}

#: 命中该风格的妆容倍数 / 未命中的倍数。
#: ⚠️ v3.38.3：从 3.5/0.35 提到 6.0/0.12。上一版理论命中率 71%、实测只有 57–60%
#:    （实跑 48 张里 29 张命中，与本地 40 抽的 57% 一致），"哥特却出 glossy lips"
#:    依然常见。6 : 0.12 让期望命中率到 ~93%，同时保留 3–4 个候选仍有变化。
STYLE_MAKEUP_BOOST = 6.0
#: ⚠️ v3.38.5：0.12 → 0.02。用户明确"妆容一定要是哥特"，0.12 时 40 抽里仍有
#: 17% 的杂项（glitter / bitten lip / light makeup）。压到 0.02 后基本绝迹，
#: 但**不设 0** —— 万一某风格的候选在当前档位全被过滤，全 0 会让妆容字段整个消失。
STYLE_MAKEUP_FAR = 0.02


def field_option_bias(field_key: str, choice: str, en: str) -> float:
    """单个字段的**选项级**风格偏置（目前只服务妆容）。

    服装六类走 `style_bias()`（那条链路是"锚点 + 兼容度"），妆容没有锚点概念，
    只需要"这个风格该配哪几种妆"的直方图，所以单独开一个入口。
    「随机 / 不限」一律返回 1.0，保持原有行为不变。
    """
    picked = resolve_choice(choice)
    if picked in ("", "auto"):
        return 1.0
    if field_key == "makeup":
        want = STYLE_MAKEUP.get(picked)
        if isinstance(want, dict):
            # 分层权重：命中表里的按表取值，没列的一律冷处理
            return float(want.get(str(en or "").strip().lower(),
                                  STYLE_MAKEUP_FAR))
        boost, far = STYLE_MAKEUP_BOOST, STYLE_MAKEUP_FAR
    elif field_key in ("place", "light_fx", "weather"):
        want = (STYLE_SCENE_BIAS.get(field_key) or {}).get(picked)
        if not want:
            return 1.0
        return (STYLE_SCENE_BOOST
                if str(en or "").strip().lower() in want else STYLE_SCENE_FAR)
    elif field_key in ("cloth_color", "sock_color"):
        want = STYLE_COLOR.get(picked)
        # 颜色比妆容更"硬"一点：哥特出黄袜子比妆容跑偏更刺眼
        boost, far = 8.0, 0.08
    else:
        return 1.0
    if not want:
        return 1.0
    return boost if str(en or "").strip().lower() in want else far

# ===========================================================================
# v3.38.4：新风格的**配件黑名单**与**颜色倾向**
# ===========================================================================
#
# 用户实跑 8 张哥特，提示词里出现 geta（木屐）/handbag（手袋）/beret（贝雷帽）/
# yellow thighhighs（黄袜）—— 这些和哥特正面冲突。根因是 `style_bias()` 对
# **中性单品**返回 1.0（"无风格倾向"= 不约束），而木屐/手袋/贝雷帽恰恰都没标风格。
# 黑名单走 `style_bans()`（硬剔除、fail-open），比软加权可靠。
#
# ⚠️ 键与值必须是词库里**真实存在**的英文原文（`check_v3_color` 会校验）。
_STYLE_BANS_EXTRA: dict[tuple, set] = {
    ("gothic", "shoes"): {
        "geta", "uwabaki", "sneakers", "slippers", "sandals", "bare feet",
        "loafers",
    },
    ("gothic", "accessory"): {
        "beret", "straw hat", "handbag", "glasses", "wristwatch", "scarf",
    },
    # ⚠️ 彩色款在 `socks` 里是**独立选项**（`pink pantyhose` / `blue thighhighs`），
    #    不是 `sock_color` 合成的 —— 只禁短袜会漏掉它们（实测哥特出粉袜）。
    ("gothic", "socks"): {
        "white socks", "striped socks", "tabi", "leg warmers", "ankle socks",
        "no-show socks", "loose socks", "argyle pantyhose", "ribbed socks",
        "white thighhighs", "white pantyhose",
        "purple socks", "red socks", "blue socks", "pink socks",
        "purple thighhighs", "red thighhighs", "blue thighhighs",
        "pink thighhighs",
        "purple pantyhose", "red pantyhose", "blue pantyhose",
        "pink pantyhose",
        "purple thighhighs, garter straps", "red thighhighs, garter straps",
    },
    ("gothic", "top"): {
        "t-shirt", "polo shirt", "sports bra", "tank top", "tube top",
        "hoodie", "cropped hoodie", "down jacket", "bathrobe", "poncho",
    },
    ("gothic", "bottom"): {
        "jeans", "cargo pants", "denim shorts", "gym shorts", "track pants",
        "yoga pants", "leggings", "bloomers", "sweater around waist",
        "wide-leg pants", "jodhpurs",
    },
    ("lolita", "shoes"): {
        "geta", "uwabaki", "sneakers", "slippers", "bare feet", "thigh boots",
        "high heel boots",
    },
    ("lolita", "accessory"): {"sunglasses", "wristwatch", "handbag"},
    ("lolita", "bottom"): {
        "jeans", "cargo pants", "leather pants", "track pants", "yoga pants",
        "gym shorts", "bike shorts", "jodhpurs",
    },
    ("punk", "shoes"): {"geta", "uwabaki", "slippers", "mary janes", "sandals"},
    ("punk", "accessory"): {"beret", "straw hat", "handbag"},
    ("punk", "socks"): {
        "frilled socks", "white socks", "lace-trimmed socks", "loose socks",
    },
    ("techwear", "shoes"): {
        "geta", "uwabaki", "slippers", "high heels", "mary janes", "sandals",
        "thigh boots",
    },
    ("techwear", "accessory"): {"beret", "straw hat", "handbag", "necklace"},
    ("techwear", "socks"): {
        "frilled socks", "lace-trimmed socks", "white thighhighs", "tabi",
    },
    ("maid", "shoes"): {"geta", "uwabaki", "sneakers", "slippers", "thigh boots"},
    ("maid", "accessory"): {"sunglasses", "handbag"},
    ("jirai", "shoes"): {
        "geta", "uwabaki", "slippers", "sandals", "loafers", "sneakers",
    },
    ("jirai", "accessory"): {"straw hat", "beret", "handbag", "straw hat"},
    # 白袜会让整体发亮（实跑里就是白蕾丝袜配深裙）
    ("jirai", "socks"): {
        "white thighhighs", "white pantyhose", "white socks", "frilled socks",
        "lace-trimmed socks",
    },
    ("gyaru", "accessory"): {"beret", "straw hat"},
}
for _k, _v in _STYLE_BANS_EXTRA.items():
    STYLE_BANS.setdefault(_k, set()).update(_v)


#: 风格 → 该出的颜色（`cloth_color` 与 `sock_color` 共用一张表）。
#: 这是"哥特却出黄袜子"的直接对策：颜色字段原本独立随机，与风格毫无关系。
STYLE_COLOR: dict[str, list[str]] = {
    "gothic": ["black", "purple", "red"],
    "lolita": ["white", "pink", "black"],
    "punk": ["black", "red", "grey"],
    "techwear": ["black", "grey", "brown"],
    "maid": ["black", "white"],
    # v3.38.7：去掉 pink —— 粉色一上身就亮，与"暗黑"直接冲突
    "jirai": ["black", "purple", "red"],
    "gyaru": ["pink", "white", "orange"],
    "night": ["black", "red", "purple"],
    "fantasy": ["black", "purple", "white"],
    "academic": ["blue", "white", "black"],
    "office": ["black", "grey", "white"],
    "traditional": ["red", "white", "black"],
    "sporty": ["blue", "white", "red"],
    "casual": ["white", "blue", "brown"],
    "home": ["white", "pink", "grey"],
    "swim": ["blue", "white", "white"],
}

# ===========================================================================
# v3.38.6：风格也要管**场景 / 光线 / 天气**
# ===========================================================================
#
# 用户实跑「暗黑少女」：服装是黑蕾丝 + 深红披肩（对），但背景是**白天城堡 + 灰白天空**，
# 整张图被拉亮，暗黑感荡然无存。根因是 place / light_fx / weather 三个字段与风格
# 完全无关，各抽各的。
#
# ⚠️ 这里用**软加权**而不是硬过滤：boost 4 / far 0.3。
#    硬过滤会把"哥特装 + 便利店"这类反差玩法彻底锁死，而反差不等于错。
#    实测 4 : 0.3 已经能让 night/fog/neon 占到 80% 以上。
STYLE_SCENE_BIAS = {
    "place": {
        "gothic": ["church", "graveyard", "castle", "ruins", "alley", "stairwell"],
        "jirai": ["alley", "street", "bar (place)", "ruins", "stairwell", "concert"],
        "punk": ["concert", "stage", "alley", "street", "bar (place)", "stairwell"],
        "techwear": ["street", "ruins", "alley", "stairwell", "cave", "train station"],
        "night": ["bar (place)", "concert", "stage", "hotel room"],
        "lolita": ["garden", "flower field", "cafe", "church", "castle"],
        "maid": ["cafe", "hotel room", "apartment", "kitchen", "hallway"],
        "academic": ["classroom", "library", "rooftop", "hallway", "stairwell"],
        "office": ["office", "elevator", "train interior", "cafe", "hotel room"],
        "traditional": ["shrine", "garden", "castle", "onsen"],
        "sporty": ["stadium", "park", "field", "rooftop"],
        "casual": ["street", "cafe", "park", "crosswalk", "convenience store",
                   "bus stop", "apartment"],
        "home": ["bedroom", "on bed", "kitchen", "bathroom", "apartment", "balcony"],
        "fantasy": ["castle", "ruins", "church", "cave", "forest", "graveyard"],
        "swim": ["beach", "poolside", "onsen", "lake", "underwater"],
    },
    "light_fx": {
        "gothic": ["candlelight", "moonlight", "dark background"],
        "jirai": ["dark background", "neon lights", "candlelight", "moonlight"],
        "punk": ["neon lights", "dark background"],
        "techwear": ["dark background", "backlighting"],
        "night": ["neon lights", "dark background"],
        "lolita": ["soft lighting", "god rays", "warm lighting"],
        "maid": ["warm lighting", "soft lighting"],
        "academic": ["soft lighting", "morning light"],
        "office": ["soft lighting", "studio lighting"],
        "traditional": ["warm lighting", "moonlight"],
        "sporty": ["soft lighting", "backlighting"],
        "casual": ["soft lighting", "warm lighting"],
        "home": ["warm lighting", "soft lighting"],
        "fantasy": ["moonlight", "candlelight", "dark background"],
        "swim": ["caustics", "god rays", "backlighting"],
    },
    "weather": {
        "gothic": ["night", "fog", "overcast", "thunderstorm"],
        "jirai": ["night", "fog", "overcast", "smoke"],
        "punk": ["night", "smoke", "overcast"],
        "techwear": ["overcast", "fog", "smoke"],
        "night": ["night", "smoke", "sparks"],
        "lolita": ["cherry blossoms", "clear sky", "falling leaves"],
        "maid": ["clear sky", "falling leaves"],
        "academic": ["clear sky", "cherry blossoms"],
        "office": ["clear sky", "overcast"],
        "traditional": ["cherry blossoms", "falling leaves", "snow"],
        "sporty": ["clear sky", "sunset"],
        "casual": ["clear sky", "falling leaves"],
        "home": ["clear sky", "rain"],
        "fantasy": ["fog", "starry sky", "smoke"],
        "swim": ["clear sky", "sunset"],
    },
}

#: 场景/光线的加权倍数。比服装软（服装错了整张图就错了，背景错了只是氛围淡）。
STYLE_SCENE_BOOST = 4.0
#: ⚠️ v3.38.6：0.3 → 0.06。0.3 时实测命中只有 41%（place）/ 56%（light_fx）——
#: 因为 place 有 61 个选项，6 个命中 ×4 只占 59% 理论份额，再被场景联动一比就更低。
#: 0.06 后理论份额 90%+，代价是"哥特装 + 便利店"这类反差组合基本消失
#: （用户要的是"够暗黑"，这个取舍合理；真要反差可在面板把 place 权重拉高）。
STYLE_SCENE_FAR = 0.06

#: 风格组内、对**整套服装**的额外偏好（同风格候选之间的先后）。
#: `allowed_outfit()` 只是硬过滤，组内各条**等概率** —— 于是「暗黑少女」里
#: 4 条载体各 25%，日系甜美系占了半壁。这里给"更贴风格名"的那几条加权。
#: 值为倍数；不在表里 = 1.0。
STYLE_OUTFIT_PREFER: dict[tuple, float] = {
    # 暗黑少女：哥特萝莉/吸血鬼才是"暗"，地雷/量产型只作调剂
    ("jirai", "gothic lolita"): 3.0,
    ("jirai", "vampire"): 2.5,
    ("jirai", "jirai kei"): 1.0,
    ("jirai", "ryousangata"): 0.6,
    # 哥特：哥特萝莉优先于吸血鬼装
    ("gothic", "gothic lolita"): 3.0,
    ("gothic", "vampire"): 1.5,
    # 洛丽塔：哥特萝莉/背心裙/泡泡裙优先于水手裙
    ("lolita", "gothic lolita"): 2.0,
    ("lolita", "pinafore dress"): 2.0,
    ("lolita", "bubble skirt"): 2.0,
    ("lolita", "sailor dress"): 1.0,
}


def outfit_prefer(anchor: str, en: str) -> float:
    return float(STYLE_OUTFIT_PREFER.get((anchor, str(en or "").strip().lower()),
                                         1.0))
