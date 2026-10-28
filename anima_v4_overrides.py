# -*- coding: utf-8 -*-
"""V3 侧的**人工校准层**。

设计原则（很重要，改动前先读）：

    「文本判档」和「选项准入」是两件事。

    · **文本判档**（grade_nsfw / grade_explicitness）必须与造型台
      **逐字节一致** —— 否则同一个提示词在两个插件里会给出不同档位，
      那正是历史上「sfw 档抽出 suggestive 内容」的根因。
    · **选项准入**是可以有上下文的：同一个英文标签放在不同字段里，
      语义可能完全不同。判定表只看到标签，看不到字段。

所以本文件做两件方向相反的事，各自单向，绝不越界：

    A. **下调**（LEVEL_DEMOTE）—— 判定表看错了上下文时把它降回来；
    B. **上抬**（LEVEL_RAISE，v3.8.0 新增）—— 判定表**没收录**这个词时补上档位。

两者共同的三条纪律：

    1. 单向 —— DEMOTE 只降不升、RAISE 只升不降，任何一条都不能反向改数；
    2. 精确到 (字段 key, 选项英文原文)，**不用模式匹配** ——
       按模式降级会连带把 `wet clothes` 这类真·透视词一起放进来，
       按模式上抬同样会误伤（`^pov ` 会把 `pov hands` 这种全年龄项也抬上去）；
    3. 每条必须写理由，且会在生成报告里逐条列出，方便随时复核。

⚠️ 为什么需要 LEVEL_RAISE（而不是直接往判定表里加词）：
   判定表的唯一真源是**造型台** `wardrobe_rules.py`（`tools/sync_nsfw_tables.py`
   逐字切片过来，`tests/check_nsfw_parity.py` 源码级对拍）。给 V3 单独加词会
   立刻破坏对拍。而「第一人称下体视角 `pov crotch`」这类词，判定表按
   `crotch cut` 才判 2 档，单写 `crotch` 判 **0 档** —— 不补就会漏进 SFW。
   所以补档位这件事按 (字段, 选项) 粒度落在本层：改这里不用动造型台。

⚠️ 想加一条之前先问自己：这是「判定表看错了上下文」，还是
   「我单纯不喜欢这个判定」？后者应该去改造型台的表，而不是在这里开洞。
"""
from __future__ import annotations

# 键：(字段 key, 选项英文原文)  值：(下调到的档位数字, 理由)
LEVEL_DEMOTE: dict[tuple[str, str], tuple[int, str]] = {
    ("hair_fx", "wet hair"): (
        0,
        "「湿发」是单纯的头发状态（刚洗完/淋过雨），画面里不含任何透视或裸露语义。"
        "判定表的 see_through 分类里有 ^wet 模式，本意是抓 wet clothes / wet shirt，"
        "在「头发」字段属于误命中 —— 不降级的话，全年龄档连湿发都抽不出来。",
    ),
    ("hair_fx", "wet hair, hair over eyes"): (
        0,
        "同上，「湿发贴脸」也只是发型状态。两个 wet hair 必须一起降，"
        "否则同一字段里两个选项档位不一致，用户无法理解为什么一个能选一个不能。",
    ),
    # ── v3.15.0：分层口径校正（一批「非插入类」从 3 档降到 2 档）──────────
    #
    # ⚠️ 这一批的理由与上面「湿发」**不同**：湿发是"判定表看错了上下文"，
    #    而这一批是"判定表的**分级粒度**与用户要的分层不一致"：
    #
    #    判定表把所有性行为一律归到「硬核」层（凡命中 sexual 分类就判 3），
    #    但 danbooru 的通行走法是：**插入**才是 hardcore，
    #    口交 / 手交 / 乳交 / 足交 / 指交 / 自慰 / 素股 / 腿交 这些
    #    **非插入**行为属 explicit（露骨）层。
    #
    #    后果：`pose_nsfw` 段被锁在 3 档起，于是「露骨档能露体、
    #    却一个行为都抽不出来」—— 这是个断层（露骨档只能拍定妆照）。
    #    本节把非插入类降到 2，配合 SECTION_FLOOR['pose_nsfw'] 3→2 一起生效。
    #
    # ⚠️ **插入类一律不动**（missionary / doggystyle / cowgirl / mating press /
    #    full nelson / prone bone / standing sex / stand and carry / sex from
    #    behind / vaginal / anal / penetration / leg lock / irrumatio /
    #    double penetration 仍留在 3–4 档）。
    #    这条边界就是用户 2026-10-16 拍板的「裸露 + 非插入行为」。
    ("n_act", "handjob"): (2, "手交：非插入行为，属露骨层。"),
    ("n_act", "blowjob"): (2, "口交：非插入行为，属露骨层。"),
    ("n_act", "deepthroat"): (2, "深喉：口交的子类，仍是非插入行为。"),
    ("n_act", "anilingus"): (2, "舔肛：非插入行为。"),
    ("n_act", "footjob"): (2, "足交：非插入行为。"),
    ("n_act", "ass job"): (2, "臀交：体外摩擦，非插入。"),
    ("n_act", "sumata"): (2, "素股：体外摩擦，非插入。"),
    ("n_act", "paizuri"): (2, "乳交：非插入行为。"),
    ("n_act", "fingering"): (2, "指交：手指进入属露骨层（danbooru 亦归 explicit），"
                                 "但不属「性交」的硬核层。"),
    ("n_act", "masturbation"): (2, "自慰：单人行为，非插入。"),
    ("n_act", "mutual masturbation"): (2, "相互自慰：非插入行为。"),
    ("n_act", "dildo riding"): (2, "骑假阳具：单人 + 道具，非真实插入。"),
    ("n_act", "intercrural"): (2, "腿交：股间摩擦，非插入。"),
    ("n_act", "facesitting"): (2, "颜骑：非插入行为（骑脸，不涉性交）。"),
    # 体态细节：这四条在非插入语境里同样成立（自慰时张开双腿 / 抬起双腿）
    ("n_pos", "spread legs"): (2, "张开双腿：姿态本身，非插入语境同样成立。"),
    ("n_pos", "legs up"): (2, "双腿高举：姿态本身。"),
    ("n_pos", "bent over"): (2, "弯腰撅臀：姿态本身（同一标签在「暗示姿势」字段里是 1 档，"
                                 "这里按 n_pos 的上下文判 2 档）。"),
    ("n_pos", "head down"): (2, "低头：纯姿态。"),
    # 高潮 / 体液：感受与体液的呈现早于插入，属露骨层
    ("n_orgasm", "moaning"): (2, "呻吟：声音表现，非插入专属。"),
    ("n_orgasm", "panting"): (2, "喘息：同上。"),
    ("n_orgasm", "aroused"): (2, "情动：状态词，未涉行为。"),
    ("n_orgasm", "bedroom eyes"): (2, "魅惑眼神：表情层。"),
    ("n_orgasm", "after sex"): (2, "事后余韵：状态层（不描述当下的插入行为）。"),
    ("n_cum", "facial"): (2, "颜射：口交语境的结果。"),
    ("n_cum", "cum on breasts"): (2, "射在胸口：乳交语境的常见结果。"),
    ("n_cum", "cum in mouth"): (2, "口中含精：口交语境的常见结果。"),
    ("n_cum", "cum string"): (2, "精液拉丝：同上，属细节呈现。"),
    ("n_fluid", "pussy juice"): (2, "爱液：湿润表现，属露骨层。"),
    ("n_fluid", "love juice trail"): (2, "爱液滴落：同上。"),
    ("n_fluid", "saliva string"): (2, "唾液拉丝：同上。"),
    ("n_fluid", "sweat"): (2, "香汗淋漓：体液呈现，本身不涉行为。"),
    ("n_fluid", "tears"): (2, "泪痕：同上。"),
}


def demote(field_key: str, en: str, num: int):
    """把判定表给出的档位按本表下调。返回 (最终档位, 理由或 None)。"""
    hit = LEVEL_DEMOTE.get((field_key, en))
    if not hit:
        return num, None
    target, why = hit
    # 只降不升：万一调用方传进来的 num 本来就比 target 低，保持原值。
    if target >= num:
        return num, None
    return target, why


# ---------------------------------------------------------------------------
# 逐选项**上抬**表（只升不降 · v3.8.0）
# ---------------------------------------------------------------------------
#
# 与 LEVEL_DEMOTE 完全对称：精确到 (字段 key, 选项英文原文)，只升不降。
#
# 为什么必须有这张表：
#   判定表是逐标签的，遇到**没收录**的词一律判 0。第一人称视角扩展词条
#   （v3.8.0 加进「视角」字段）里有一批就是这种：
#       viewpoint  'pov crotch'   → 判 0（表里只有 `crotch cut`）
#       viewpoint  'pov breasts'  → 判 0
#       viewpoint  'pov legs'     → 判 0
#   不补档位的话，SFW 档会把「第一人称下体视角」抽出来 —— 正是本插件
#   最核心那条承诺（低档绝不越界）的反面。
#
# ⚠️ `pov, fellatio` / `pov, sexual intercourse` / `pov, cowgirl position`
#    这三条**不需要**登记在这里：它们的第二个标签都在判定表里（fellatio 有
#    模糊模式、sexual intercourse / cowgirl position 在 sexual 分类表里），
#    判定表直接判 3 档。**能被判定表正确判定的，就不要在这里重复登记** ——
#    登记的是"判定表的盲区"，不是"我觉得该是多少档"。
LEVEL_RAISE: dict[tuple[str, str], tuple[int, str]] = {
    # ── v3.20.0：腿上词库扩章的两条盲区 ──────────────────────────────
    #
    # ⚠️ 为什么必须补：`bodystocking`（连身网衣）整体判 2 档，但它的变体
    #    `fishnet bodystocking` / `black bodystocking` 作为**整串**未被判定表
    #    收录，落进 1 档 —— 于是「全年龄档」也能抽出近乎全身透视的连身网衣。
    #    同义族的档位必须一致，否则用户看到"一个能选一个不能"。
    ("socks", "fishnet bodystocking"): (
        2, "渔网连身衣＝覆盖躯干+双腿的全身透视网装，裸露程度等同 bodystocking（2 档）。"
           "判定表只收了 bodystocking 整词，带前缀的变体落进 1 档 —— 属盲区。"),
    ("socks", "black bodystocking"): (
        2, "同上：颜色前缀不改变连身网衣的裸露性质，必须与 bodystocking 同档。"),
    # ⚠️ 不要给「多 tag 选项」做 LEVEL_RAISE：成品层按**标签**折算
    #    （见 rules.level_floor_tags），`pantyhose, garter straps` 抬到 2 会
    #    把裸 `pantyhose` 一起抬到 2 —— 结果是 SFW 档把连裤袜整个剔掉
    #    （tests/check_v3_repair.py 的「连裤袜 × 赤足」当场变红，实测踩到）。
    #    两条吊带连裤袜的档位差异属判定表口径遗留，不在这里开洞。

    ("viewpoint", "pov breasts"): (
        1,
        "第一人称俯视自己胸口：画面必然带到胸部轮廓，属轻度暗示（擦边档起）。"
        "判定表的裸体分类只收 `breasts out` / `underboob` 这类直接裸露词，"
        "`breasts` 单独出现判 0 —— 在「视角」字段属于盲区。",
    ),
    ("viewpoint", "pov legs"): (
        1,
        "第一人称俯视自己腿部：镜头直对腿部线条，属轻度暗示（擦边档起）。"
        "同上，判定表未收录 `legs` 单字，判 0 属盲区。",
    ),
    ("viewpoint", "pov crotch"): (
        2,
        "第一人称直视自己裆部：画面主体就是胯部特写，属明显暗示裸露（成人档起）。"
        "判定表的裸体分类只写了 `crotch cut` 模式，`crotch` 单字判 0 —— 盲区。",
    ),
    # ── v3.14.0：新增「暗示姿势」字段（pose_risque）的档位 ──────────────
    #
    # 为什么要整批登记：判定表（造型台）对**姿态类**词几乎全是 0 档 ——
    # 它的分类是按"裸露程度"做的，而「弯腰撅臀」「前倾」这类词的暗示性
    # 来自**姿态**而非裸露，于是整批落进盲区。
    #
    # ⚠️ 这批键的字段名是 `pose_risque`（不是 `n_pos`）。同一个英文 tag
    #    在 `n_pos` 里是 L3（体位细节），在 `pose_risque` 里是 L1/L2 ——
    #    `option_level()` 按字段查，两者互不干扰 ✓
    # ⚠️ 但 `tag_level()`（成品层档位判据）取的是**最低档**，所以
    #    `bent over` 一旦抬到 1，在 SFW 档就会被 repair 剔除 —— 这正是
    #    我们要的（暗示姿势不该出现在全年龄档）。
    ("pose_risque", "bent over"): (
        1, "弯腰撅臀：姿态本身即带性暗示（臀线突出），但无任何裸露 —— 擦边档起。"),
    ("pose_risque", "leaning forward"): (
        1, "前倾：常配合俯视/胸前视角，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "arched back"): (
        1, "弓背挺胸：突出胸部与腰部曲线，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "leaning back"): (
        1, "后仰：展开身体的邀请姿态，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "leg up"): (
        1, "抬腿：腿部抬高，画面重心移向胯部，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "hand on own chest"): (
        1, "手抚胸前：动作指向胸部，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "arm between breasts"): (
        1, "手臂夹胸：强调胸部挤压，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "hands on own thighs"): (
        1, "双手抚腿：手贴大腿内侧，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "stretching"): (
        1, "伸展：双臂上举带出胸腰线条，属轻度暗示 —— 擦边档起。"
           "（它原来是 `action` 段的「伸懒腰」，v3.14.0 移到这里）"),
    ("pose_risque", "tiptoes"): (
        1, "踮脚：抬升重心、绷直小腿与臀线，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "top-down bottom-up"): (
        1, "上下同框：从脚到头的纵向构图，常带腿部特写，属轻度暗示 —— 擦边档起。"
           "（原在 `n_pos`，v3.14.0 移到暗示姿势）"),
    ("pose_risque", "hugging own legs"): (
        1, "抱膝蜷坐：膝部贴近胸口、裙摆上收，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "hair flip"): (
        1, "甩发：颈肩舒展、常用于展示侧身曲线，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "skirt pull"): (
        1, "拉拽裙摆：手持续牵动裙面，属轻度暗示 —— 擦边档起。"),
    ("pose_risque", "panty pull"): (
        2, "拉扯内裤：动作直接作用于内衣，属明显暗示（成人档起）。"),
    ("pose_risque", "bikini pull"): (
        2, "拉扯比基尼：同上，泳装版本，属明显暗示（成人档起）。"),
    ("pose_risque", "undressing"): (
        2, "宽衣：正在脱掉衣物的过程，属明显暗示（成人档起）。"),
    ("pose_risque", "after sex"): (
        2, "事后余韵：语境直接指向性行为之后，属明显暗示（成人档起）。"),
}


def raise_(field_key: str, en: str, num: int):
    """把判定表给出的档位按本表上抬。返回 (最终档位, 理由或 None)。

    与 demote 对称：**只升不降**，传进来的 num 已经不低于 target 就原样返回。
    """
    hit = LEVEL_RAISE.get((field_key, en))
    if not hit:
        return num, None
    target, why = hit
    if target <= num:
        return num, None
    return target, why


def calibrate(field_key: str, en: str, num: int):
    """完整的人工校准链：先上抬（补判定表盲区）再下调（纠正误判上下文）。

    返回 (最终档位, [(方向, 原始档, 最终档, 理由), ...])。

    ⚠️ 顺序不能反：RAISE 与 DEMOTE 目前覆盖的 (字段, 选项) 集合**不相交**，
       所以顺序其实无所谓；但先补盲区再纠正语义才是可读的顺序，将来万一
       出现交叉，也不会因为顺序不同而给出不同结果（下面 raise 之后再 demote，
       demote 拿到的是已上抬的值，仍然只降不升 —— 两种顺序下 demote 的
       目标值比较对象不同，所以真要交叉时必须显式写死优先方）。
       目前实证：交集为空（见 tests/check_v3_repair.py 的断言）。
    """
    changes = []
    n, why = raise_(field_key, en, num)
    if why:
        changes.append(("raise", int(num), int(n), why))
    m, why2 = demote(field_key, en, n)
    if why2:
        changes.append(("demote", int(n), int(m), why2))
    return m, changes


# ---------------------------------------------------------------------------
# 段级保底档位（只升不降）
# ---------------------------------------------------------------------------
#
# 为什么必须有这张表：
#   判定表是**逐标签**的，遇到没收录的词就一律判 0 档。实测发现
#   ⑪⑫⑬ 段里有若干标签落在盲区里，例如
#       n_body   'clitoris'        → 判 0（表里没有这个词）
#       n_orgasm 'after sex'       → 判 0（表里没有这个词）
#       n_fabric 'red velvet'      → 判 0（表里没有这个词）
#   结果就是「SFW 档抽出阴蒂和事后余韵」—— 一个会直接毁掉用户信任的漏洞。
#
#   靠往判定表里补词是补不完的（永远会有下一个漏掉的词）。正确的兜底是
#   **段级下限**：这四个段从设计上就是 NSFW 专用段，段内任何内容都
#   不应该出现在低档，与单个词是否被收录无关。
#
# 方向与 LEVEL_DEMOTE 相反：这张表**只升不降**。
# 两者叠加后的最终档位 = max(判定表, 段下限)，再经 LEVEL_DEMOTE 下调。
# 因为下调表只覆盖「头发段」，而头发段没有下限，所以两张表不会互相打架。
SECTION_FLOOR: dict[str, int] = {
    "cloth_nsfw": 2,      # 🔞 服装状态：最低也要到「成人」档
    # ⚠️ pose_nsfw 于 v3.15.0 从 3 降到 2。
    #    原因：段里有一批**非插入类**行为（口交/手交/乳交/足交/指交/自慰/
    #    素股/腿交 —— 见上面 LEVEL_DEMOTE 的那一节），按分层口径属「露骨」
    #    而非「硬核」。段下限锁在 3 会让**露骨档一个行为都抽不出来**
    #    （只能露体、不能有动作），是个明显的断层。
    #    降到 2 之后，**插入类仍然只在 3 档起出现** —— 它们的档位来自
    #    判定表本身（judge 判 3），段下限只是"兜底不低于"，不是"一律拉到 3"。
    "pose_nsfw": 2,       # 🔞 体位与性行为：非插入类在露骨档起，插入类仍靠判定表守 3 档
    "special_nsfw": 3,    # 🔞 特殊主题（绳缚/道具/群体）
    "canon": 2,           # 🔞 法典场景：14 组预设最低就是 2 档
}


def floor_of(section_id: str) -> int:
    return int(SECTION_FLOOR.get(section_id, 0))


def apply_floor(section_id: str, num: int) -> int:
    """段下限：只升不降。"""
    return max(int(num), floor_of(section_id))


# ---------------------------------------------------------------------------
# v3.15.0 批量上抬：`SECTION_FLOOR['pose_nsfw']` 由 3 降到 2 的**配套**
# ---------------------------------------------------------------------------
#
# 为什么需要这一批：
#   段下限此前把 pose_nsfw 整段兜在 3 档，于是段里凡是**判定表判 0** 的词
#   —— 姿态类 `boy on top` / 道具类 `bound wrists` / 状态类 `orgasm, trembling`
#   （判定表按"裸露程度"分类，这些词一条都收不进去）—— 都被顺带抬到了 3。
#
#   v3.15.0 把段下限降到 2，是为了放「非插入行为」进露骨档
#   （见 LEVEL_DEMOTE 里那一节），但**副作用是这些盲区词也一起掉到 2 档**：
#   露骨档会冒出 `ahegao` / `mind break` / `x-ray` / `bound wrists` 这类
#   明显属于硬核层的东西。
#
#   所以这一批做的是「逐词标定」：把该留 3 档的盲区词显式抬回去。
#   比原来"整段一刀切"更精确，代价是要维护这张清单
#   （`tests/check_v3_gate.py` 与 `check_v3_link.py` 会盯着它别漏）。
_RAISE_POSE_NSFW_BLIND = {
    # 插入类行为 —— 判定表认不出这些写法
    "n_act": [
        "sex from behind", "reverse cowgirl position", "mating press",
        "full nelson", "stand and carry", "leg lock", "clothed sex",
        "irrumatio", "penetration",
    ],
    # 性交体位与束缚 —— 纯姿态/道具词，判定表判 0
    "n_pos": [
        "girl on top", "boy on top", "all fours, sex", "legs behind head",
        "squatting cowgirl position", "upright straddle", "against wall, sex",
        "bound wrists", "bound arms",
    ],
    # 高潮的过激呈现 —— 状态类，判定表判 0
    "n_orgasm": [
        "orgasm, trembling", "body writhe", "heart-shaped pupils",
        "fucked silly", "mind break", "ahegao, rolled back eyes",
    ],
    # 透视断面：把内部结构直接画出来，属硬核层
    "n_cum": ["x-ray"],
}
for _fk, _items in _RAISE_POSE_NSFW_BLIND.items():
    for _en in _items:
        LEVEL_RAISE.setdefault((_fk, _en), (
            3,
            "硬核层：判定表对这类写法判 0（它按裸露程度分类，姿态/道具/状态词"
            "一条都收不进去），此前靠 `SECTION_FLOOR['pose_nsfw']=3` 一刀切兜着；"
            "v3.15.0 段下限降到 2 之后必须显式抬回，否则会漏进露骨档。",
        ))
