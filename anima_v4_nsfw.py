# -*- coding: utf-8 -*-
"""ANIMA-Wardrobe-V3 · NSFW 判定层（**自动生成，请勿手改**）

来源 : custom_nodes/Comfyui-Anima-Wardrobe/wardrobe_rules.py
生成 : tools/sync_nsfw_tables.py
源哈希: 59211a1ca513b6a3443b0e0d8dcf92beb5d0e9c3b1a9bd0a740e84f9498193e9

本文件是 Anima-Wardrobe 判定表的**逐字切片**，不是重写。
改判定表只能改造型台那一边，然后重跑：

    python tools/sync_nsfw_tables.py

再跑对拍确认两边没分家：

    python tests/check_nsfw_parity.py

⚠️ 唯一真源是造型台的 wardrobe_rules.py。任何「只在 V3 这边加一条」
   的做法都会让两个插件对同一句话给出不同档位 —— 那正是历史上
   「sfw 档抽出 suggestive 内容」这个 bug 的根因。
"""
# 切片过来的函数只依赖 re（造型台那边还有 json/os/random，本层用不到，
# 刻意不引 —— 少一个 import 就少一个「V3 和造型台依赖不同」的可能）。
import re


# 危险/极短词：只允许整词相等，避免子串误伤
EXACT_ONLY = {"top", "bottom", "belt", "tie", "mask", "hat", "cap", "vest", "cross"}


def _has(tag, words):
    t = tag.lower()
    for w in words:
        if w in EXACT_ONLY:
            if t == w:
                return True
        elif w in t:
            return True
    return False


# 直接命中即判 explicit：裸露部位、性行为、涩涩道具、体液
# 判定口径（写进 docs/ROLL_RULES.md，改动必须同步）：
#   explicit   = 画面里能直接看到性器官 / 乳头 / 全裸 / 性行为 / 性道具 / 体液
#   suggestive = 没有直接裸露，但透视、剪切、半脱、掀起、内衣外露、湿身
#   sfw        = 以上都没有
EXPLICIT_TAGS = {
    "completely nude", "nude", "naked", "spread pussy", "pussy cut",
    "exposed pussy", "bare ass", "butt crack cutout", "crotchless",
    "crotchless panties", "crotch cutout", "crotch zipper", "bottomless",
    "no panties", "topless", "nipples", "nipple slip", "nipple ring",
    "nipples visible through clothes", "areola slip", "breasts out",
    "one breast out", "breast curtain", "breasts curtain", "between breasts",
    "underboob", "sideboob", "underboob cutout", "pasties", "deepthroat",
    "throat bulge", "fellatio", "cunnilingus", "handjob", "paizuri",
    "masturbation", "fingering", "sexual intercourse", "vaginal", "anal",
    "creampie", "cum on body", "cum on sheets", "cum pool", "cum",
    "pussy juice stain", "used condom", "many used condoms", "condom belt",
    "vibrator", "dildo", "double dildo", "strap-on", "butt plug", "tail plug",
    "anal beads", "nipple clamps", "onahole", "artificial vagina",
    "masturbator", "ball gag", "bit gag", "ring gag", "bondage",
    "bondage outfit", "shibari", "pubic hair", "cameltoe", "o-ring harness",
    "body writing", "tally marks", "chastity cage", "chastity belt",
    "sex toy nearby", "vibrator on bed", "dildo on floor", "anal beads on table",
    "tape on pussy", "ofuda on pussy", "covered nipples", "groin",
    "frontal wedgie", "nipple",
}


# 例外：这些虽然含 nipple 字样，但语义是"被遮住"
EXPLICIT_EXCEPTIONS = {"covered nipples", "nipples covered"}


# 模糊命中：解决 'ofuda on pussy' / 'tape on pussy' 这类精确表抓不到的复合写法
EXPLICIT_PATTERNS = [
    r"\bpussy\b", r"\banus\b", r"\bnipples?\b", r"\bareola\b", r"\bdeepthroat\b",
    r"\bfellatio\b", r"\bcunnilingus\b", r"\bhandjob\b", r"\bpaizuri\b",
    r"masturbat", r"\bcreampie\b", r"\bcum\b", r"\banal\b", r"\bcrotchless\b",
    r"\bbottomless\b", r"no panties", r"\btopless\b", r"butt ?plug",
    r"\bdildo\b", r"\bvibrator\b", r"\bcondom\b", r"\bbondage\b", r"\bshibari\b",
    r"\bpasties\b", r"\bunderboob\b", r"\bsideboob\b", r"\bcameltoe\b",
    r"\bchastity\b", r"sex toy", r"^naked (?!jacket|apron|cape|cloak|coat|"
                               r"ribbon|tabard|poncho|vest|kimono|hanfu)",
    r"\bnude\b", r"\bcrotch cut\b", r"\bareola\b",
]


SUGGESTIVE_TAGS = {
    "see-through", "transparent", "translucent", "sheer", "thin",
    "see-through shirt", "transparent shirt", "see-through dress",
    "see-through leotard", "see-through sleeves", "see-through silhouette",
    "micro bikini", "micro skirt", "micro shorts", "micro dress",
    "micro panties", "highleg", "highleg panties", "highleg leotard",
    "high cut", "high slit", "side slit", "single side slit", "hip vent",
    "side cutout", "side cut-out", "waist cutout", "clothing cutout",
    "chest cutout", "navel cutout", "stomach cutout", "midriff cutout",
    "cleavage cutout", "deep v-neckline", "exposed chest", "center opening",
    "off shoulder", "shoulder slip", "strap slip", "bare shoulders",
    "single bare shoulder", "bare arms", "sleeveless", "backless",
    "backless outfit", "bare back", "shirt lift", "skirt lift", "dress lift",
    "clothes lift", "open shirt", "open jacket", "open clothes", "open front",
    "open fly", "unbuttoned", "unzipped", "partially undressed", "half-dressed",
    "pants down", "one leg out", "clothes around waist", "shirt removed",
    "dress removed", "revealing clothes", "strapless", "frontless outfit",
    "sideless outfit", "shrug", "hood up", "wet", "wet clothes", "wet shirt",
    "wet dress", "wet look", "wet body", "wet appearance", "skintight",
    "second skin", "latex", "pvc", "lingerie", "lace lingerie", "babydoll",
    "negligee", "chemise", "bodystocking", "garter belt", "no bra", "braless",
    "bra exposed", "panties peek", "upskirt", "downblouse", "reverse bunnysuit",
    "slingshot swimsuit", "g-string", "thong", "nipples visible",
    "one stocking rolled down", "single thighhigh", "mismatched legwear",
    "asymmetrical legwear", "single glove", "one shoe missing",
    "battle damage", "torn", "ripped", "tears", "cracked", "bloodstain",
    "oil body", "linked piercing", "leather clothing", "hip vent",
    "unworn panties", "clothes on floor", "used tissue",
}


ESCALATE_MIN = None  # 已停用：见下方 grade_explicitness 说明


# （保留常量名以免外部引用报错；不再参与判定）
ESCALATE_TAGS = set()


def _explicit_hits(low):
    """精确表 + 模糊正则表双查（模糊表是必需的：`ofuda on pussy` 这类复合写法精确表抓不到）。"""
    hits = [t for t in low if t in EXPLICIT_TAGS and t not in EXPLICIT_EXCEPTIONS]
    if hits:
        return hits
    for t in low:
        if t in EXPLICIT_EXCEPTIONS:
            continue
        if any(re.search(p, t) for p in EXPLICIT_PATTERNS):
            hits.append(t)
    return hits


def _suggestive_hits(low):
    return [t for t in low if t in SUGGESTIVE_TAGS or _has(t, list(SUGGESTIVE_TAGS))]


def _normalize_tags(tags):
    if isinstance(tags, str):
        return [t.strip().lower() for t in tags.split(",") if t.strip()]
    return [str(t).strip().lower() for t in (tags or []) if str(t).strip()]


def _nsfw_core(low):
    """⭐ 唯一的判定真源：NSFW 等级 + 内容分类。

    1. 命中 群体 / 极端插入扩张 / 极端拘束装置 / 极限体液 / 主奴标记 → 4 极端
    2. 命中 性行为 / 性道具 / 束缚 / 体液                              → 3 过激
    3. 否则 num = max(基线, 命中分类的最高等级)
       基线：explicit 表命中 → 2 / suggestive 表命中 → 1 / 否则 0

    ⚠️ 刻意**不做**「多个暗示标签叠加就升级」的启发式：
    那会让「擦边档」抽出被判过激的内容，档位与结果自相矛盾。
    分级 = 逐标签表的并集，规则可预期、可复现。
    """
    cats = _nsfw_categories(low)
    if any(c in cats for c in EXTREME_CATEGORIES):
        return NSFW_MAX, cats, "命中极端向内容（第 5 级）"
    if any(c in cats for c in HARDCORE_CATEGORIES):
        return 3, cats, "命中过激向内容"
    expl, sug = _explicit_hits(low), _suggestive_hits(low)
    num = 2 if expl else (1 if sug else 0)
    if cats:
        num = max(num, max(NSFW_TABLES[c]["level"] for c in cats))
    reason = ("命中成人裸露词" if expl else
              "命中暗示向标签" if sug else "无暴露向标签")
    return num, cats, reason


def grade_explicitness(tags):
    """三段式投影：num 0→sfw / 1→suggestive / ≥2→explicit。

    ⚠️ 这个函数是 `_nsfw_core` 的**投影**，不再自己判一套。
    历史上两套标度各判各的，直接导致「sfw 档抽出 suggestive 内容」和
    「擦边档抽出 NSFW2 内容」两个 bug。任何新的判定都只能加进 NSFW 分类表。
    """
    low = _normalize_tags(tags)
    num, cats, reason = _nsfw_core(low)
    key = "sfw" if num == 0 else "suggestive" if num == 1 else "explicit"
    hits = [t for c in cats.values() for t in c] or _explicit_hits(low) \
        or _suggestive_hits(low)
    return key, {"reason": reason, "hits": hits[:6]}


# ⭐ 等级词汇表 —— 唯一真源。控件值就是这里的 key（一定是合法值），
#    界面上显示的中文由 locales/*/nodeDefs.json 的 values 映射提供。
LEVELS = ("sfw", "suggestive", "explicit", "hardcore", "extreme", "any")


LEVEL_RANK = {"sfw": 0, "suggestive": 1, "explicit": 2, "hardcore": 3,
              "extreme": 4, "any": 99}


# 每个等级对应的 NSFW 数字（既做上限也做保底）
TARGET_NUM = {"sfw": 0, "suggestive": 1, "explicit": 2, "hardcore": 3,
              "extreme": 4, "any": 99}


# 控件的可选值 = 合法 key 本身（不再用中文当值，避免接口校验对不上）
LEVEL_CHOICES = list(LEVELS)


# 中文显示名：前端报告 / 文档 / 日志共用
LEVEL_ZH = {"sfw": "全年龄", "suggestive": "擦边", "explicit": "成人",
            "hardcore": "过激", "extreme": "极端", "any": "不限"}


# 兼容层：老工作流用过中文标签，外部调用可能传数字或旧 key，一律归一
LEVEL_ALIAS = {
    "0 · 全年龄": "sfw", "1 · 擦边": "suggestive", "2 · 成人": "explicit",
    "3 · 过激": "hardcore", "4 · 极端": "extreme", "不限": "any",
    "全年龄": "sfw", "擦边": "suggestive", "成人": "explicit",
    "过激": "hardcore", "极端": "extreme",
    "0": "sfw", "1": "suggestive", "2": "explicit", "3": "hardcore", "4": "extreme",
    "safe": "sfw", "ecchi": "suggestive", "nsfw": "explicit",
    "hardcore_nsfw": "hardcore", "extreme_nsfw": "extreme",
}


def resolve_level(value, default="suggestive"):
    """把任意等级表示统一成**合法 key**（一定是 LEVELS 之一）。

    ⭐ 契约：**永远不抛异常，返回值永远合法**。
      ① 空值 / 认不出来 → default（default 自身不合法时回退 suggestive）
      ② 中文标签 / 数字 / 旧英文 key → 经 LEVEL_ALIAS 归一
      ③ 已经是合法 key（大小写无关）→ 原样返回
    """
    fallback = default if default in LEVELS else "suggestive"
    if value is None or value == "":
        return fallback
    v = str(value).strip()
    if v in LEVEL_RANK:
        return v
    low = v.lower()
    if low in LEVEL_RANK:
        return low
    if v in LEVEL_ALIAS:
        return LEVEL_ALIAS[v]
    if low in LEVEL_ALIAS:
        return LEVEL_ALIAS[low]
    m = re.match(r"^([0-4])\b", v)          # 「0 · 全年龄」这类带数字前缀的写法
    if m:
        return LEVEL_ALIAS[m.group(1)]
    for zh, key in (("全年龄", "sfw"), ("擦边", "suggestive"), ("成人", "explicit"),
                    ("过激", "hardcore"), ("极端", "extreme"), ("不限", "any")):
        if zh in v:
            return key
    return fallback


def level_label(level):
    """等级 → 中文显示名（带数字前缀，便于在报告里一眼看级别）。"""
    key = resolve_level(level)
    if key == "any":
        return "不限"
    return f"{TARGET_NUM[key]} · {LEVEL_ZH[key]}"


# 五级 NSFW 标度（数字越大越露骨）。
# ⚠️ key 直接复用 LEVELS 的规范值 —— 历史上这里另起过 safe/ecchi/nsfw 一套，
#    结果「同一件事两个词」反复打架，现在统一成一套词汇。
NSFW_SCALE = [
    (0, "sfw", "全年龄", "无任何暴露向标签"),
    (1, "suggestive", "擦边", "轻度暗示：露肩 / 短裙 / 内衣轮廓 / 材质诱惑"),
    (2, "explicit", "成人", "明显裸露或透视：全裸 / 性器官 / 乳头 / 内衣外露 / 半脱"),
    (3, "hardcore", "过激", "性行为 / 性道具 / 体液 / 束缚调教"),
    (4, "extreme", "极端", "群体 → 极端插入扩张 / 拘束装置 / 极限体液 / 主奴标记"),
]


NSFW_MAX = 4


NSFW_NUM = {k: n for n, k, _l, _d in NSFW_SCALE}


NSFW_LABEL = {k: l for _n, k, l, _d in NSFW_SCALE}


NSFW_KEY_OF_NUM = {n: k for n, k, _l, _d in NSFW_SCALE}


# 「任意等级表示 → NSFW 数字」：any（不限）按顶格 4 处理，用于场所/细节的承载力判定
NUM_OF = {k: min(v, NSFW_MAX) for k, v in TARGET_NUM.items()}


# 内容分类表：用于回答「这个提示词里到底有什么成人向内容」
NSFW_TABLES = {
    "nudity": {
        "label": "裸露", "level": 2,
        "tags": {"completely nude", "nude", "naked", "topless", "bottomless",
                 "no panties", "pussy cut", "exposed pussy", "spread pussy",
                 "bare ass", "nipples", "nipple slip", "nipples visible through clothes",
                 "areola slip", "breasts out", "one breast out", "breast curtain",
                 "breasts curtain", "underboob", "sideboob", "underboob cutout",
                 "crotchless", "crotchless panties", "crotch cutout", "pasties",
                 "nipple ring", "cameltoe", "pubic hair", "tape on pussy",
                 "ofuda on pussy", "groin", "nipples visible"},
        "patterns": [r"\bpussy\b", r"\banus\b", r"\bnipples?\b", r"\bareola\b",
                     r"\bnude\b", r"\btopless\b", r"bottomless", r"no panties",
                     r"crotchless", r"\bcameltoe\b", r"\bunderboob\b", r"\bsideboob\b"],
    },
    "see_through": {
        "label": "透视/湿身", "level": 2,
        "tags": {"see-through", "transparent", "translucent", "sheer",
                 "see-through shirt", "transparent shirt", "see-through dress",
                 "see-through leotard", "see-through sleeves", "see-through silhouette",
                 "wet", "wet clothes", "wet shirt", "wet dress", "wet look",
                 "wet body", "wet appearance", "skintight", "second skin",
                 "lace lingerie", "lingerie", "bodystocking", "garter belt",
                 "no bra", "braless", "breast curtain", "reverse bunnysuit",
                 "transparent heels", "transparent pvc", "holographic clothing"},
        "patterns": [r"^see-through", r"^transparent", r"^translucent",
                     r"^wet\b", r"^wet ", r"\bsheer\b", r"see-through"],
    },
    "undressed": {
        "label": "半脱/掀起", "level": 2,
        "tags": {"shoulder slip", "strap slip", "areola slip", "panties peek",
                 "bra exposed", "shirt lift", "skirt lift", "dress lift",
                 "clothes lift", "open shirt", "open jacket", "open clothes",
                 "open front", "open fly", "open kimono", "open robe",
                 "unbuttoned", "unzipped", "partially undressed", "half-dressed",
                 "clothes pull", "pants down", "pants pull", "one leg out",
                 "clothes around waist", "shirt removed", "dress removed",
                 "clothes removed", "upskirt", "downblouse", "exposed chest",
                 "revealing clothes", "clothes on floor", "unworn panties",
                 "single bare shoulder", "one stocking rolled down",
                 "one shoe missing", "mismatched legwear", "asymmetrical legwear"},
        "patterns": [r"slip$", r"\bopen (shirt|jacket|front|fly|kimono|robe)\b",
                     r"undressed", r"half-dressed", r"pants down",
                     r"\bupskirt\b", r"\bdownblouse\b"],
    },
    "cutout": {
        "label": "裁剪/镂空", "level": 1,
        "tags": {"micro bikini", "micro skirt", "micro shorts", "micro dress",
                 "micro panties", "highleg", "highleg panties", "highleg leotard",
                 "high cut", "high slit", "side slit", "single side slit", "hip vent",
                 "side cutout", "side cut-out", "waist cutout", "clothing cutout",
                 "chest cutout", "navel cutout", "stomach cutout", "midriff cutout",
                 "cleavage cutout", "deep v-neckline", "center opening",
                 "cleavage", "off shoulder", "bare shoulders", "bare arms",
                 "bare back", "backless", "backless outfit", "sleeveless",
                 "strapless", "frontless outfit", "sideless outfit",
                 "slingshot swimsuit", "g-string", "thong", "crop top",
                 "crop top overhang", "short shorts", "lowleg pants",
                 "exposed pocket", "thigh gap"},
        "patterns": [r"cutout", r"cut-out", r"micro (skirt|shorts|dress|bikini|panties)",
                     r"^backless", r"bare (shoulders?|arms?|back)"],
    },
    "yuri": {
        "label": "百合", "level": 2,
        "tags": {"yuri", "girls love", "shoujo ai", "lesbian", "yuri couple",
                 "kiss", "french kiss"},
        # ⚠️ holding hands / looking at each other / love 刻意不收 —— 它们是通用互动词，
        #    收进来会把「SFW 双人正常互动」顶到 2 级
        "patterns": [r"\byuri\b", r"girls love", r"\blesbian\b", r"shoujo ai"],
    },
    # ===== 第 5 级（极端）专属分类：新增内容，只有 extreme 档才会命中 =====
    "group": {
        "label": "群体/多人", "level": 4,
        "tags": {"group sex", "threesome", "ffm threesome", "mmf threesome",
                 "foursome", "gangbang", "orgy", "spitroast", "bukkake"},
        "patterns": [r"group sex", r"\bgangbang\b", r"\borgy\b", r"threesome",
                     r"\bfoursome\b", r"spitroast", r"\bbukkake\b"],
    },
    "extreme_insert": {
        "label": "极端插入/扩张", "level": 4,
        "tags": {"double penetration", "triple penetration", "large insertion",
                 "gaping", "stomach bulge", "fisting", "anal fisting",
                 "vaginal fisting", "cervix"},
        "patterns": [r"double penetration", r"triple penetration",
                     r"large insertion", r"\bgaping\b", r"stomach bulge",
                     r"\bfisting\b", r"\bcervix\b"],
    },
    "extreme_bondage": {
        "label": "极端拘束/装置", "level": 4,
        "tags": {"suspension", "suspension bondage", "suspension bar",
                 "inverted suspension", "stocks", "pillory", "wooden horse",
                 "bondage furniture", "sex machine", "fuck machine",
                 "vacuum bed", "mummification", "restraint cage"},
        "patterns": [r"suspension", r"\bpillory\b", r"wooden horse",
                     r"bondage furniture", r"(sex|fuck) machine",
                     r"vacuum bed", r"mummification"],
    },
    "extreme_fluid": {
        "label": "极限体液", "level": 4,
        "tags": {"excessive cum", "cum inflation", "cum bath", "wet and messy",
                 "peeing", "urination", "incontinence", "golden shower",
                 "lactation", "milking", "squirt"},
        "patterns": [r"excessive cum", r"cum inflation", r"cum bath",
                     r"wet and messy", r"\bpeeing\b", r"\burination\b",
                     r"\bincontinence\b", r"golden shower", r"\bsquirt"],
    },
    "marked": {
        "label": "主奴/标记", "level": 4,
        "tags": {"slave", "pet play", "branding", "collar and leash",
                 "human pet", "leash in mouth"},
        "patterns": [r"\bbranding\b", r"\bslave\b", r"pet play",
                     r"collar and leash", r"human pet"],
    },
    "sexual": {
        "label": "性行为", "level": 3,
        "tags": {"deepthroat", "throat bulge", "fellatio", "cunnilingus", "handjob",
                 "paizuri", "masturbation", "fingering", "sexual intercourse",
                 "vaginal", "anal", "creampie", "doggystyle", "missionary",
                 "cowgirl position", "prone bone", "standing sex", "spread legs",
                 "presenting", "tribadism", "scissoring", "breast sucking",
                 "grinding", "straddling"},
        "patterns": [r"\bdeepthroat\b", r"\bfellatio\b", r"\bcunnilingus\b",
                     r"\bhandjob\b", r"\bpaizuri\b", r"masturbat", r"\bcreampie\b"],
    },
    "toy": {
        "label": "性道具", "level": 3,
        "tags": {"vibrator", "remote control vibrator", "dildo", "double dildo",
                 "strap-on", "suction cup dildo", "butt plug", "tail plug",
                 "anal beads", "nipple clamps", "clothespins", "onahole",
                 "artificial vagina", "masturbator", "chastity cage", "chastity belt",
                 "sex toy nearby", "vibrator on bed", "dildo on floor",
                 "anal beads on table", "spreader bar", "crop", "paddle"},
        "patterns": [r"\bdildo\b", r"\bvibrator\b", r"butt ?plug", r"anal beads",
                     r"sex toy", r"\bchastity\b"],
    },
    "bondage": {
        "label": "束缚/BDSM", "level": 3,
        "tags": {"bondage", "bondage outfit", "shibari", "ball gag", "bit gag",
                 "ring gag", "cloth gag", "tape over mouth", "blindfold", "eye mask",
                 "leash", "o-ring choker", "o-ring harness", "harness", "chest belt",
                 "handcuffs", "shackles", "ropes", "chains", "duct tape",
                 "tape bondage", "spiked collar", "red rope"},
        "patterns": [r"\bbondage\b", r"\bshibari\b", r"\bhandcuffs?\b", r"\bshackles?\b"],
    },
    "fluid": {
        "label": "体液/事后", "level": 3,
        "tags": {"cum", "cum on body", "cum on sheets", "cum pool", "creampie",
                 "pussy juice stain", "used condom", "many used condoms",
                 "condom belt", "condom wrapper", "condom box", "used tissue",
                 "sweat stain", "oil body", "candle wax", "whipped cream", "lotion",
                 "body writing", "tally marks", "handprint", "lipstick mark"},
        "patterns": [r"\bcum\b", r"\bcondom\b", r"pussy juice"],
    },
    "fetish": {
        "label": "暴露癖/情境", "level": 1,
        "tags": {"exposed", "against window", "outdoors", "public", "recording",
                 "webcam", "streaming", "torn", "ripped", "tears", "battle damage",
                 "bloodstain", "blood on clothes", "linked piercing",
                 "single glove", "lace trim", "neon trim"},
        "patterns": [r"\btorn\b", r"\bripped\b", r"\btears\b"],
    },
    "suggestive": {
        "label": "轻度暗示", "level": 1,
        "tags": {"nightgown", "babydoll", "negligee", "chemise", "camisole",
                 "corset", "bustier", "sundress", "silk robe", "satin robe",
                 "pajamas", "shrug", "hood up", "oversized shirt",
                 "boyfriend shirt", "boyfriend shirt"},
        "patterns": [r"crop top", r"oversized shirt"],
    },
}


# 命中这些分类即判过激（第 4 级上限）
HARDCORE_CATEGORIES = ("sexual", "toy", "bondage", "fluid")


# 命中这些分类即判极端（第 5 级）—— 直接升到标度顶格
EXTREME_CATEGORIES = ("group", "extreme_insert", "extreme_bondage",
                      "extreme_fluid", "marked")


# 分类标签的展示顺序（露骨度从高到低）
CATEGORY_ORDER = ("group", "extreme_insert", "extreme_bondage", "extreme_fluid",
                  "marked", "sexual", "toy", "bondage", "fluid", "nudity",
                  "see_through", "undressed", "yuri", "cutout", "fetish",
                  "suggestive")


def _nsfw_categories(low_tags):
    hits = {}
    for cat, spec in NSFW_TABLES.items():
        found = []
        for t in low_tags:
            if t in spec["tags"] or any(re.search(p, t) for p in spec.get("patterns", ())):
                found.append(t)
        if found:
            hits[cat] = found
    return hits


def grade_nsfw(tags):
    """返回 NSFW 等级 + 内容分类明细。

    等级判定（第 5 级为本次新增）：
      · 命中 群体 / 极端插入扩张 / 极端拘束装置 / 极限体液 / 主奴标记 → 4 极端
      · 命中 性行为/性道具/束缚/体液                                  → 3 过激
      · 否则 取 max(基线等级, 命中分类的等级)                         → 0/1/2
    基线等级复用 grade_explicitness（不另写一套匹配逻辑，避免两套表打架）。
    """
    low = _normalize_tags(tags)
    num, cats, reason = _nsfw_core(low)
    level = NSFW_KEY_OF_NUM[num]
    detail = {NSFW_TABLES[c]["label"]: cats[c]
              for c in CATEGORY_ORDER if c in cats}
    return {
        "level": level, "num": num, "label": NSFW_LABEL[level],
        "max": NSFW_MAX,
        "scale": [{"num": n, "key": k, "label": l, "desc": d}
                  for n, k, l, d in NSFW_SCALE],
        "categories": detail,
        "hits": [t for c in CATEGORY_ORDER if c in cats for t in cats[c]],
        "base": {0: "sfw", 1: "suggestive", 2: "explicit", 3: "explicit",
                 4: "explicit"}[num],
        "reason": reason,
        "hardcore_categories": HARDCORE_CATEGORIES,
        "extreme_categories": EXTREME_CATEGORIES,
        "is_extreme": num >= NSFW_MAX,
    }


def format_nsfw(report):
    """把 grade_nsfw 的结果排成人类可读的多行文本。"""
    lines = [f"NSFW 等级 : {report['num']} / {report.get('max', NSFW_MAX)}"
             f"  ·  {report['label']}（{report['level']}）",
             f"判定基线 : {report['reason']}"]
    if report["categories"]:
        lines.append("成人向内容 :")
        for label, items in report["categories"].items():
            lines.append(f"  · {label}（{len(items)}）: {', '.join(items[:5])}"
                         + (" …" if len(items) > 5 else ""))
    else:
        lines.append("成人向内容 : 无")
    return "\n".join(lines)


def strip_nsfw(text, max_num=1):
    """把超过 max_num 的成人向标签从文本里剔掉，返回 (剩余文本, 被剔除的标签)。"""
    removed = []
    keep = []
    for t in str(text or "").split(","):
        t = t.strip()
        if not t:
            continue
        n = grade_nsfw([t])["num"]
        if n > max_num:
            removed.append(t)
        else:
            keep.append(t)
    return ", ".join(keep), removed
