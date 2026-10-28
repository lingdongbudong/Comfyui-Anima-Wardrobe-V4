# -*- coding: utf-8 -*-
"""构建 ANIMA-Wardrobe-V3 的角色库（联网，一次性）。

数据来源三条腿：

  ① **造型台基线** `Comfyui-Anima-Wardrobe/presets/character_pool.json`
     7999 条里筛出 5981 女性，每条已带作品 / 人气 / 发色瞳色 / 官方特征 tags。
     但**对新生代作品严重欠覆盖**（绝区零 20 / 星穹铁道 15 / 胜利女神 26），
     而且 HSR 的 84 个角色被错归到 `honkai (series)` 大类下。

  ② **safebooru 补全**（danbooru.donmai.us 在国内被墙，safebooru 是它的
     SFW 镜像，同一套 API，可达）。按作品枚举**真实存在的**角色 tag，
     所以产出的 tag 一定能被 danbooru 认得 —— 这是"标签准确无误"的机器保证。

  ③ **源 HTML 的 222 条**（带中文名与 APPEAR 外貌表），作为其中一部分合并进来。

过滤规则（用户明确要求 + 工程必要）：
  · 只收女性（wiki 正文的代词判定 + 造型台的 g 字段双重确认）
  · 排除宝可梦系列
  · 排除变体 tag（同一角色有基础 tag 与 `_(xxx)` 换装 tag，只留基础形式）
  · 目标作品（绝区零 / 星穹铁道 / 胜利女神）**保底收录，不占人气名额**

用法：
    python tools/build_characters.py --dry          # 只统计不写盘
    python tools/build_characters.py                # 写 presets/anima_v4_characters.json
    python tools/build_characters.py --no-net       # 离线重跑（复用 .cache 里的 wiki 缓存）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
CUSTOM_NODES = os.path.dirname(PLUGIN)

WARDROBE_POOL = os.path.join(CUSTOM_NODES, "Comfyui-Anima-Wardrobe",
                             "presets", "character_pool.json")
WARDROBE_OFFICIAL = os.path.join(CUSTOM_NODES, "Comfyui-Anima-Tools-main",
                                 "js", "character_official_data.json")
POOLS_JSON = os.path.join(PLUGIN, "presets", "anima_v4_pools.json")
OUT_JSON = os.path.join(PLUGIN, "presets", "anima_v4_characters.json")
CACHE_DIR = os.path.join(PLUGIN, "tools", ".cache_chars")

MIRROR = "https://safebooru.donmai.us"

# ── 用户明确要求排除的作品 ────────────────────────────────────────
EXCLUDED_WORKS = {"pokemon", "pokemon (series)", "pocket monsters"}

# ── 保底作品：这些作品的角色无论人气多低都要收 ────────────────────
TARGET_WORKS = {
    "zenless zone zero": "绝区零",
    "honkai: star rail": "崩坏：星穹铁道",
    "goddess of victory: nikke": "胜利女神：妮姬",
    # v3.12.0 追加：鸣潮。不进保底的话，鸣潮角色只有 pop 最高的两位能挤进
    # 人气名额（实测只有长离 1447 / 女主 1054），造型台池里躺着的另外 6 位全丢。
    "wuthering waves": "鸣潮",
}

# ── 角色「形态」白名单（v3.12.0）──────────────────────────────────
#
# 背景：canonical_of() 只保留**基础角色 tag**，任何 `角色_(形态)_(作品)` 一律丢弃 ——
#       因为那多半是换装 / 同人 cosplay 变体（`jane_doe_(zenith)_(swimsuit)`）。
#       但有一类变体是**角色本身的官方形态**（异格 / 变身 / 另一套立绘），
#       用户要求它们**分开成条**（不是合并进主角色）。
#
# ⚠️ 为什么必须手工列：形态 tag 与皮肤 tag 的**写法完全一样**
#       `yangyang_(xuanling)_(wuthering_waves)`  ← 3.5 五星形态
#       `changli_(laurel_nymph)_(wuthering_waves)` ← 限定皮肤
#    程序区分不了，只能人工登记。
#
# 加新条目的规矩：
#   · key   = danbooru **完整 tag**（含 `_(作品)` 后缀，一字不差）
#   · value = 中文显示名（留空则退化成英文原名）
#   · ⚠️ **男角色的变体不要加** —— `male_rover_(perpetual_spark)` /
#     `scar_(aberrant_nightmare)` 刻意不在表里，靠"不在白名单"自然挡掉。
#   · ⚠️ 只登记真实存在的 tag（`leg_ring` 那类不存在的写法写了也白写）。
FORM_VARIANTS = {
    # ── 鸣潮 · 官方异格 / 形态 ──────────────────────────────────
    "yangyang_(xuanling)_(wuthering_waves)": "秧秧·玄翎",
    "female_rover_(perpetual_spark)_(wuthering_waves)": "女漂泊者·永焰",
    "denia_(breakdown)_(wuthering_waves)": "德妮娅·崩解",
    "zani_(infernal)_(wuthering_waves)": "赞妮·炎狱",
    "aemeath_(young)_(wuthering_waves)": "艾梅斯·幼年",
    "aemeath_(exostrider_armament)_(wuthering_waves)": "艾梅斯·机甲装备",
    "aemeath_(student)_(wuthering_waves)": "艾梅斯·学生",
    "hsin_(illumining_form)_(wuthering_waves)": "心·明照形态",
    "hsin_(moon_fox)_(wuthering_waves)": "心·月狐形态",
    "sanhua_(exorcistic_adjuration)_(wuthering_waves)": "散华·驱邪",
    "yangyang_(bird)_(wuthering_waves)": "秧秧·鸟形态",
    "lynae_(mercenary)_(wuthering_waves)": "琳奈·佣兵",
    "phrolova_(ostina)_(wuthering_waves)": "弗洛洛·奥斯蒂娜",
    # ── 鸣潮 · 限定皮肤（用户口径：异格 + 皮肤都收）──────────────
    "chisa_(peach_parfait)_(wuthering_waves)": "千咲·蜜桃帕菲",
    "lynae_(peppermint)_(wuthering_waves)": "琳奈·薄荷",
    "carlotta_(splashing_summer)_(wuthering_waves)": "珂莱塔·夏日",
    "changli_(laurel_nymph)_(wuthering_waves)": "长离·桂冠宁芙",
    "jinhsi_(peach_blossom)_(wuthering_waves)": "今汐·桃夭",
    "mornye_(plush_dream)_(wuthering_waves)": "茉宁·绒梦",
}

# ── 可玩角色白名单（v3.12.0）──────────────────────────────────────
#
# 背景：safebooru 是按「这个作品下**所有** character tag」枚举的，里面混着
#       NPC / 路怪 / 声骸 / 机械 / 周本 BOSS。实测鸣潮 192 个基础 tag 里
#       只有 ~46 个是**可玩角色**（共鸣者），其余是「芙露德莉斯」（周本头目）、
#       `nimbus_wraith`（杂兵）、`imperator`（BOSS）、`npc_...`（通用 NPC）这类。
#
# ⚠️ 为什么程序分不出来：
#     danbooru 把 NPC 和可玩角色**都标成 character 类**（category=4）；
#     `1girl` / `1boy` 共现只能剔**男性**（`brant` 75% 1boy → 男 ✓），
#     但区分不了「女性 NPC / 女性 BOSS」和「可玩女性角色」
#     （实测 `hecate`（BOSS）90% 1girl，比很多真角色还高）。
#     → 只能人工维护名单。
#
# 命中规则：
#   · 作品**登记在表里** → 只收表里的 tag（外加 FORM_VARIANTS 的形态/皮肤）
#   · 作品**不在表里** → 保持原行为（全量收），不影响其它 288 个作品
#
# ⚠️ 名单口径 = **可玩角色**（Game8 的 "All Playable Characters"，3.7 版本）。
#     游戏更新出新角色时要手工补 —— 这是"干净"换来的代价。
# ⚠️ 只登记**女性**角色；男性（brant / jiyan / aalto / calcharo / xiangli_yao /
#     mortefi / geshu_lin / yuanwu / luuk_herssen / qiuyuan / scar）刻意不登记。
PLAYABLE_ROLES = {
    "wuthering waves": {
        # 主角（可男可女；这里只收女）
        "rover_(wuthering_waves)", "female_rover_(wuthering_waves)",
        # 3.x 世代
        "hsin_(wuthering_waves)", "suoming_(wuthering_waves)", "jingran_(wuthering_waves)",
        "qingxiao_(wuthering_waves)", "suisui_(wuthering_waves)", "yangyang_(wuthering_waves)",
        "lucilla_(wuthering_waves)", "denia_(wuthering_waves)", "hiyuki_(wuthering_waves)",
        "sigrika_(wuthering_waves)", "aemeath_(wuthering_waves)", "mornye_(wuthering_waves)",
        "lynae_(wuthering_waves)", "chisa_(wuthering_waves)", "galbrena_(wuthering_waves)",
        "iuno_(wuthering_waves)", "augusta_(wuthering_waves)", "phrolova_(wuthering_waves)",
        "lupa_(wuthering_waves)", "cartethyia_(wuthering_waves)", "ciaccona_(wuthering_waves)",
        "zani_(wuthering_waves)", "cantarella_(wuthering_waves)", "phoebe_(wuthering_waves)",
        "roccia_(wuthering_waves)", "carlotta_(wuthering_waves)", "camellya_(wuthering_waves)",
        "buling_(wuthering_waves)", "lily_(wuthering_waves)",
        # 1.x / 2.0 世代
        "changli_(wuthering_waves)", "jinhsi_(wuthering_waves)", "yinlin_(wuthering_waves)",
        "shorekeeper_(wuthering_waves)", "zhezhi_(wuthering_waves)", "youhu_(wuthering_waves)",
        "encore_(wuthering_waves)", "verina_(wuthering_waves)", "sanhua_(wuthering_waves)",
        "baizhi_(wuthering_waves)", "chixia_(wuthering_waves)", "danjin_(wuthering_waves)",
        "taoqi_(wuthering_waves)", "jianxin_(wuthering_waves)", "lumi_(wuthering_waves)",
    },
}

# ── 三保底作品的名单（v3.13.0）：量太大，放独立 JSON ────────────────
#
# 鸣潮的名单只有 46 条、且来源是 Game8 的可玩角色表，留在上面代码里；
# 绝区零 / 崩铁 / 妮姬三家合计 300+ 条，放 `tools/playable_roles.json`。
#
# ⚠️⚠️ 这三家的名单**大多不带作品后缀**（`ju_fufu` / `hoshimi_miyabi` /
#    `claret_flint`）—— 光靠 `*(zenless_zone_zero)` 枚举根本拿不到，枚举出来的
#    反而是 `ellen_(zenless_zone_zero)` 这类 **NPC 空壳**。所以 fetch_work_tags()
#    里专门加了「按白名单直接拉取」这条腿。
#
# 来源 = danbooru 官方「角色列表」wiki 页的 *Playable characters* 区块。
# 重生成 + 对拍：`python tools/build_playable_roles.py [--check]`
#
# 过滤口径（用户 2026-10-15 拍板）：
#   · 只收**女性**（wiki 代词 + 1girl/1boy 共现双判据）
#   · 剔**非人类单位**（邦布 / 宠物 / 召唤物 / 武器 / 机械）
#   · **收**联动角色（妮姬 × PERSONA / Nier / 电锯人 / Re:Zero 等）
PLAYABLE_ROLES_JSON = os.path.join(HERE, "playable_roles.json")


def _load_playable_roles_json():
    """把 tools/playable_roles.json 合并进 PLAYABLE_ROLES。

    ⚠️ 读不到就返回空 dict（**不报错**）—— 名单文件缺失不应该让构建整个失败，
        退化成"这三家不做白名单过滤"（= v3.12.0 的行为）比崩掉好。
    """
    try:
        with open(PLAYABLE_ROLES_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    roles = data.get("roles") or {}
    return {k: set(v or []) for k, v in roles.items() if isinstance(v, list)}


PLAYABLE_ROLES.update(_load_playable_roles_json())

# tag → 它所属的（已登记）作品。白名单里的 tag 唯一确定了作品，用来**修正
# 造型台的粗分类**：造型台把 `bronya_rand` 标成 `honkai (series)`，
# 但它其实是崩铁的布洛妮娅 —— 不修的话 UI 里会多出一个 "honkai (series)" 分组。
_TAG_TO_WORK = {}
for _w, _ts in PLAYABLE_ROLES.items():
    for _t in _ts:
        _TAG_TO_WORK.setdefault(_t, _w)


def _allow_of(c):
    """该角色所属作品的白名单；**未登记的作品返回 None**（= 不做白名单过滤）。

    三个来源依次试（缺一不可，全是实测踩出来的）：

    ① `_TAG_TO_WORK[tag]` —— 最可靠。造型台的角色**裸名**（`bronya_rand`）
       对不上任何作品 key，但白名单里有了它，就能反查出它属于崩铁。
    ② `work` —— 大多数情况够用，但造型台给的是**粗分类**：崩铁的角色全被
       塞进 `honkai (series)` 大桶，跟 TARGET_SLUGS 的 key（`honkai: star rail`）
       对不上。对不上就会**绕过白名单过滤**（实测 `pom-pom_(honkai:_star_rail)`
       就是这么漏进来的）。
    ③ `work_tag` —— build() 里从 tag 括号修正出来的规范作品名。
    """
    w = _TAG_TO_WORK.get(c.get("tag") or "")
    if w:
        return PLAYABLE_ROLES.get(w)
    for k in (c.get("work"), c.get("work_tag")):
        a = PLAYABLE_ROLES.get(k or "")
        if a is not None:
            return a
    return None

# ── 繁 → 简 兜底表（v3.12.0）──────────────────────────────────
#
# 为什么需要：中文名是从 wiki 抓的，而 wiki 的默认变体常常是**繁体**
#   （实测 2879 条里 132 条带繁体字：`龍驤` / `雪風` / `愛彌斯` / `卡提希婭`）。
# 用户口径：**中文名一律简体**。
#
# 优先 `zhconv`（装了就是全量转换）；没装就用下面这张表兜底 ——
# 表里是**本库实际用到**的 167 个字，够当前全量用。
# ⚠️ 新增角色若带来新的繁体字，兜底表会漏转。补法：
#     pip install zhconv && python -c "
#       import json,zhconv
#       d=json.load(open('presets/anima_v4_characters.json',encoding='utf-8'))
#       p={}
#       for c in d['characters']:
#         z=c.get('zh') or ''; s=zhconv.convert(z,'zh-cn')
#         for a,b in zip(z,s):
#           if a!=b: p[a]=b
#       print(json.dumps(p,ensure_ascii=False))"
ZH_FALLBACK = {
    "賀": "贺", "洩": "泄", "響": "响", "傘": "伞", "剛": "刚", "電": "电", "聖": "圣",
    "蓮": "莲", "鶴": "鹤", "風": "风", "長": "长", "門": "门", "儀": "仪", "時": "时",
    "塚": "冢", "鈴": "铃", "龍": "龙", "驤": "骧", "鳳": "凤", "宮": "宫", "叢": "丛",
    "雲": "云", "園": "园", "誕": "诞", "沖": "冲", "紗": "纱", "棲": "栖", "華": "华",
    "亞": "亚", "蘇": "苏", "務": "务", "頼": "赖", "鵜": "鹈", "飼": "饲", "緒": "绪",
    "尋": "寻", "漣": "涟", "艦": "舰", "優": "优", "貴": "贵", "鮮": "鲜", "呂": "吕",
    "織": "织", "霧": "雾", "島": "岛", "楓": "枫", "鷺": "鹭", "張": "张", "覇": "霸",
    "熾": "炽", "鳶": "鸢", "飛": "飞", "陽": "阳", "蘭": "兰", "備": "备", "倫": "伦",
    "蘿": "萝", "隊": "队", "組": "组", "姉": "姊", "輿": "舆", "愛": "爱", "綾": "绫",
    "獅": "狮", "朧": "胧", "葉": "叶", "皐": "皋", "間": "间", "磯": "矶", "飾": "饰",
    "櫻": "樱", "鯨": "鲸", "羅": "罗", "弔": "吊", "納": "纳", "機": "机", "環": "环",
    "綴": "缀", "夢": "梦", "勢": "势", "鷹": "鹰", "涼": "凉", "倉": "仓", "見": "见",
    "癒": "愈", "驪": "骊", "駒": "驹", "書": "书", "録": "录", "獸": "兽", "醬": "酱",
    "鎌": "镰", "氷": "冰", "綿": "绵", "無": "无", "鳥": "鸟", "蒼": "苍", "絆": "绊",
    "氣": "气", "紅": "红", "彌": "弥", "進": "进", "棗": "枣", "詩": "诗", "颯": "飒",
    "駿": "骏", "結": "结", "養": "养", "憂": "忧", "來": "来", "麗": "丽", "撫": "抚",
    "將": "将", "戶": "户", "遠": "远", "雛": "雏", "開": "开", "敗": "败", "親": "亲",
    "濃": "浓", "樫": "㭴", "嵐": "岚", "輪": "轮", "輝": "辉", "揮": "挥", "場": "场",
    "級": "级", "灣": "湾", "東": "东", "變": "变", "調": "调", "譜": "谱", "術": "术",
    "栞": "刊", "毬": "球", "馬": "马", "寧": "宁", "審": "审", "勝": "胜", "獎": "奖",
    "絶": "绝", "婭": "娅", "岡": "冈", "憐": "怜", "鑽": "钻", "寶": "宝", "歷": "历",
    "貞": "贞", "鍋": "锅", "樹": "树", "黃": "黄", "動": "动", "槍": "枪", "魯": "鲁",
    "蹟": "迹", "藍": "蓝", "鳴": "鸣", "慶": "庆", "極": "极", "潤": "润", "紀": "纪",
    "罰": "罚", "喬": "乔", "盤": "盘", "燈": "灯", "鑒": "鉴", "淵": "渊",
}

try:                                        # 有 zhconv 就全量转（可选依赖）
    from zhconv import convert as _zhconv_convert
except Exception:                           # pragma: no cover
    _zhconv_convert = None


# ── 中文名人工校正表（v3.12.0）────────────────────────────────────
#
# 为什么需要：中文名是从 wiki 抓的，`pick_zh()` 会在 wiki 的别名列表里挑一个，
#   偶尔会挑到**不是名字**的东西。实测鸣潮抓到过：
#       `iuno` / `augusta` → "鸣潮日月组"   ← 那是 wiki 的分类名，不是角色名
#       `sigrika` / `sanhua` → "鸣潮西格莉卡" / "鸣潮散华"  ← 带上了作品名前缀
#   优先级**最高**（压过 FORM_VARIANTS 与源 HTML）。
#
# ⚠️ 只填**明显错误**的；全名（`珂莱塔·莫塔里`）与官方本名（`chixia` 的
#    "马小芳"其实是本名"炽霞"…按玩家叫法写）都算可接受，不必强填。
ZH_FIX = {
    "iuno_(wuthering_waves)": "尤诺",
    "augusta_(wuthering_waves)": "奥古斯塔",
    "sigrika_(wuthering_waves)": "西格莉卡",
    "sanhua_(wuthering_waves)": "散华",
    "chixia_(wuthering_waves)": "炽霞",
    # ── v3.13.0：绝区零 3.2 / 3.3 的新角色 ────────────────────────
    # ⚠️ 这批角色是**新建的 tag**，wiki 的 other_names 里还没有中文名 ——
    #    名字取自官网 / 官方前瞻（2026-10-15 时点）。
    "claret_flint": "克拉蕾",
    "roxy_ifrita_pryce": "洛克茜",
    "phoenix_reffaella": "菲欧妮",
    "sigrid_de_l'azur": "希格莉德",
    "velina_airgid": "维琳娜",
    "remielle_dan": "蕾米埃尔",
    "norma_hollowell": "诺姆",
    "nangong_yu": "南宫羽",
    # ── v3.13.0：联动角色 ────────────────────────────────────────
    # ⚠️ 这些 tag 属于**原作品**（妮姬的联动列表里挂着它们），
    #    wiki 的别名列表只有日文 / 韩文，`pick_zh()` 挑不出来。
    "2b_(nier:automata)": "2B",
    "a2_(nier:automata)": "A2",
    "makima_(chainsaw_man)": "玛奇玛",
    "power_(chainsaw_man)": "帕瓦",
    "himeno_(chainsaw_man)": "姬野",
    "niijima_makoto": "新岛真",
    "amagi_yukiko": "天城雪子",
    "aigis_(persona)": "埃癸斯",
    "emilia_(re:zero)": "爱蜜莉雅",
    "rem_(re:zero)": "雷姆",
    "ram_(re:zero)": "拉姆",
    "ayanami_rei": "绫波丽",
    "souryuu_asuka_langley": "惣流·明日香·兰格雷",
    "makinami_mari_illustrious": "真希波·玛丽·伊兰崔亚斯",
    "katsuragi_misato": "葛城美里",
    "nishikigi_chisato": "锦木千束",
    "inoue_takina": "井之上泷奈",
    "suzuhara_sakura": "铃原樱",
    "kurumi_(lycoris_recoil)": "胡桃",
    "jill_valentine": "吉尔·瓦伦丁",
    "claire_redfield": "克莱尔·雷德菲尔德",
    "ada_wong": "艾达·王",
    "eve_(stellar_blade)": "EVE",
    "raven_(stellar_blade)": "渡鸦",
    "lily_artemis_ii_(stellar_blade)": "莉莉·阿耳忒弥斯",
}


def to_simplified(s):
    """繁体中文名 → 简体。空串/None 原样返回。"""
    s = str(s or "")
    if not s:
        return s
    if _zhconv_convert is not None:
        return _zhconv_convert(s, "zh-cn")
    return "".join(ZH_FALLBACK.get(ch, ch) for ch in s)

# ── 作品中文名表（其余显示英文原名）──────────────────────────────
WORK_ZH = {
    "zenless zone zero": "绝区零",
    "honkai: star rail": "崩坏：星穹铁道",
    "goddess of victory: nikke": "胜利女神：妮姬",
    "genshin impact": "原神",
    "honkai (series)": "崩坏系列",
    "honkai impact": "崩坏3",
    "blue archive": "蔚蓝档案",
    "arknights": "明日方舟",
    "azur lane": "碧蓝航线",
    "girls' frontline": "少女前线",
    "fate (series)": "Fate 系列",
    "fate/grand order": "Fate/Grand Order",
    "kantai collection": "舰队Collection",
    "touhou": "东方Project",
    "idolmaster": "偶像大师",
    "umamusume": "赛马娘",
    "hololive": "hololive",
    "nijisanji": "彩虹社",
    "vocaloid": "VOCALOID",
    "love live!": "LoveLive!",
    "bang dream!": "BanG Dream!",
    "girls und panzer": "少女与战车",
    "lyrical nanoha": "魔法少女奈叶",
    "precure": "光之美少女",
    "fire emblem": "火焰纹章",
    "final fantasy": "最终幻想",
    "granblue fantasy": "碧蓝幻想",
    "league of legends": "英雄联盟",
    "overwatch": "守望先锋",
    "nier (series)": "尼尔系列",
    "nier: automata": "尼尔：机械纪元",
    "persona (series)": "女神异闻录系列",
    "persona 5": "女神异闻录5",
    "street fighter": "街霸",
    "tekken": "铁拳",
    "dead or alive": "死或生",
    "king of fighters": "拳皇",
    "guilty gear": "罪恶装备",
    "blazblue": "苍翼默示录",
    "genshin impact (series)": "原神",
    "wuthering waves": "鸣潮",
    "punishing: gray raven": "战双帕弥什",
    "nikke": "胜利女神：妮姬",
    "reverse: 1999": "重返未来：1999",
    "path to nowhere": "无期迷途",
    "arknights: endfield": "明日方舟：终末地",
    "snowbreak: containment zone": "尘白禁区",
    "tower of fantasy": "幻塔",
    "honkai: star rail (series)": "崩坏：星穹铁道",
    "the legend of zelda": "塞尔达传说",
    "danganronpa (series)": "弹丸论破",
    "kill la kill": "斩服少女",
    "re:zero": "Re:从零开始的异世界生活",
    "kono subarashii sekai ni shukufuku wo!": "为美好的世界献上祝福！",
    "mahou shoujo madoka magica": "魔法少女小圆",
    "neon genesis evangelion": "新世纪福音战士",
    "spy x family": "间谍过家家",
    "chainsaw man": "电锯人",
    "jujutsu kaisen": "咒术回战",
    "kimetsu no yaiba": "鬼灭之刃",
    "bocchi the rock!": "孤独摇滚！",
    "lycoris recoil": "莉可丽丝",
    "oshi no ko": "【我推的孩子】",
    "sono bisque doll wa koi wo suru": "更衣人偶坠入爱河",
    "dungeon ni deai wo motomeru no wa machigatteiru darou ka": "在地下城寻求邂逅是否搞错了什么",
    "kaguya-sama wa kokurasetai ~tensai-tachi no renai zunousen~": "辉夜大小姐想让我告白",
    "seishun buta yarou wa bunny girl senpai no yume wo minai": "青春猪头少年不会梦到兔女郎学姐",
    "yahari ore no seishun love come wa machigatteiru.": "我的青春恋爱物语果然有问题",
    "go-toubun no hanayome": "五等分的新娘",
    "sword art online": "刀剑神域",
    "tokyo ghoul": "东京喰种",
    "attack on titan": "进击的巨人",
    "bleach": "死神",
    "naruto": "火影忍者",
    "one piece": "海贼王",
    "my hero academia": "我的英雄学院",
    "boku no hero academia": "我的英雄学院",
    "genshin": "原神",
    "kemono friends": "兽娘动物园",
    "original": "原创角色",
    "ragnarok online": "仙境传说",
    "gundam": "高达",
    "my little pony": "小马宝莉",
    "mario (series)": "马里奥系列",
    "touhou project": "东方Project",
    "project sekai": "世界计划",
    "hypnosis mic": "催眠麦克风",
    "ensemble stars!": "偶像梦幻祭",
    "twisted wonderland": "迪士尼扭曲仙境",
    "granblue fantasy (series)": "碧蓝幻想",
    "destiny child": "命运之子",
    "azur lane (series)": "碧蓝航线",
    "counter:side": "未来战",
    "epic seven": "第七史诗",
    "honkai gakuen": "崩坏学园",
    "valkyrie connect": "女武神连接",
    "pretty series": "美妙系列",
    "aikatsu!": "偶像活动",
    "pripara": "美妙天堂",
    "d4dj": "D4DJ",
    "revue starlight": "少女☆歌剧",
    "zombieland saga": "佐贺偶像是传奇",
    "project diva": "初音未来 -歌姬计划-",
    "touken ranbu": "刀剑乱舞",
    "pokemon": "宝可梦",
}

# ⚠️ 反直觉但实测如此：safebooru 的 WAF **专门拦浏览器 UA**。
#    同一个 URL：curl 默认 UA → 200，Python 默认 UA → 200，
#    Chrome UA → **403 Forbidden**。所以这里刻意用 curl 的 UA。
UA = "curl/8.4.0"

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_net_lock = threading.Semaphore(10)     # 最多 10 路并发
_last = [0.0]


def http_json(url, tries=4, timeout=45):
    """带退避的 GET。网络不可达时抛异常，由调用方决定是否降级。"""
    for i in range(tries):
        with _net_lock:
            # 礼貌间隔：safebooru 是志愿者镜像，别把它打挂
            gap = 0.12 - (time.time() - _last[0])
            if gap > 0:
                time.sleep(gap)
            _last[0] = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with _opener.open(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception as exc:
                if i == tries - 1:
                    raise
                time.sleep(1.5 * (i + 1))
    return None


# ============================================================================
# ① 造型台基线
# ============================================================================

def load_wardrobe():
    with open(WARDROBE_POOL, "r", encoding="utf-8") as fh:
        d = json.load(fh)
    girls, skipped_male, skipped_work = [], 0, 0
    for c in d["characters"]:
        if c.get("g") != "1girl":
            skipped_male += 1
            continue
        work = (c.get("c") or "").strip()
        if work in EXCLUDED_WORKS:
            skipped_work += 1
            continue
        girls.append({
            "name": c["n"],
            "work": work,
            "work_tag": "",
            "trigger": c.get("t") or "",
            "pop": int(c.get("p") or 0),
            "hair": c.get("h") or "",
            "eyes": c.get("e") or "",
            "tags": list(c.get("f") or []),
            "src": "wardrobe",
        })
    return girls, skipped_male, skipped_work


def load_gender_map():
    """造型台**全量** 7999 条的性别表：{名字key: '1girl'|'1boy'|'other'|''}。

    load_wardrobe() 已经把非女性筛掉了，所以它给不出"这个角色是男的"这种
    负面信息 —— 而 safebooru 枚举出来的新角色恰好需要这条负面信息。
    实测踩过：`wise_(zenless_zone_zero)`（绝区零男主角）不在女性子集里，
    于是走 safebooru 那条路进来，只能靠 wiki 代词判性别，结果被判成女性。
    拿全量表当权威就没这个问题。
    """
    if not os.path.exists(WARDROBE_POOL):
        return {}
    try:
        with open(WARDROBE_POOL, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return {}
    out = {}
    for c in d.get("characters", []):
        for key in (str(c.get("n", "")).replace(" ", "_").lower(),
                    re.sub(r"[^a-z0-9]", "",
                           f"{c.get('n','')}||{c.get('c','')}".lower())):
            if key:
                out.setdefault(key, c.get("g") or "")
    return out


def load_official():
    """Anima-Tools 的官方特征表：key = `name||work`。"""
    if not os.path.exists(WARDROBE_OFFICIAL):
        return {}
    with open(WARDROBE_OFFICIAL, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_source_html_roles():
    """源 HTML 的 222 条（中文名 + 完整 trigger）。"""
    with open(POOLS_JSON, "r", encoding="utf-8") as fh:
        pools = json.load(fh)
    sec = next(s for s in pools["sections"] if s["id"] == "count")
    fld = next(f for f in sec["fields"] if f["key"] == "role")
    out = []
    for zh, en in fld["opts"]:
        en = (en or "").strip()
        if not en:
            continue
        parts = [p.strip() for p in en.split(",") if p.strip()]
        out.append({"zh": zh.strip(), "trigger": en,
                    "name": parts[0], "work_tags": parts[1:]})
    return out


# ============================================================================
# ② safebooru：枚举作品下的真实角色 tag
# ============================================================================

def canonical_of(tag, work_slug):
    """判断是不是该作品的**基础**角色 tag（而不是换装/同人变体）。

    danbooru 的命名约定：
        jane_doe_(zenless_zone_zero)                   ← 基础形式
        jane_doe_(zenless_zone_zero)_(swimsuit)        ← 变体
        jane_doe_(zenless_zone_zero)_(cosplay)         ← 同人 cosplay
    所以「基础形式」= 结尾恰好是 `_(<work>)`，且前面再没有别的括号组。
    """
    tail = f"_({work_slug})"
    if not tag.endswith(tail):
        return False
    head = tag[: -len(tail)]
    if not head:
        return False
    return "(" not in head and ")" not in head


def fetch_tag_meta(tags):
    """按 tag 名查投稿数（逐个查 + 磁盘缓存 + 并发）。

    ⚠️⚠️ **不能一次塞多个 `search[name]=`** —— 实测 safebooru 只认**最后一个**：
        `?search[name]=ju_fufu&search[name]=hoshimi_miyabi` 只返回后者，
        前者被静默丢掉（拿到 0）。300+ 条白名单会因此全部变成"零人气"，
        再在零人气过滤里被剔掉 —— 症状就是「白名单里的角色收不进来」。
        这个坑很隐蔽：不报错，数据只是悄悄变少。
    """
    def one(t):
        def _get():
            try:
                data = http_json(f"{MIRROR}/tags.json?search%5Bname%5D="
                                 + urllib.parse.quote(t) + "&limit=5")
            except Exception:
                return None
            for x in data or []:
                if x.get("name") == t:
                    return int(x.get("post_count") or 0)
            return None
        return int(cached_json("count", t, _get) or 0)

    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(tags, ex.map(one, tags)))


def fetch_work_tags(work, work_slug, off_works):
    """枚举一个作品下的角色 tag，带投稿数。"""
    url = (f"{MIRROR}/tags.json?search%5Bcategory%5D=4"
           f"&search%5Bname_matches%5D="
           + urllib.parse.quote(f"*({work_slug})") + "&limit=1000")
    try:
        data = http_json(url)
    except Exception as exc:
        print(f"    [WARN] {work}: 拉取失败 {exc}")
        data = []
    out = []
    for t in data or []:
        if t.get("category") != 4:
            continue
        name = t["name"]
        # v3.12.0：基础 tag 照收；带括号的**形态/皮肤变体**只放行人工白名单
        #（`canonical_of` 会把它们全滤掉，见 FORM_VARIANTS 的说明）
        if not canonical_of(name, work_slug) and name not in FORM_VARIANTS:
            continue
        out.append({"tag": name, "count": int(t.get("post_count") or 0)})

    # ── v3.13.0：白名单里的 tag **直接拉取** ─────────────────────────────
    # 三保底作品的角色在 danbooru 上**大多不带作品后缀**
    #（`ju_fufu` / `hoshimi_miyabi` / `claret_flint`），
    # 靠上面那条 `*(作品slug)` 枚举**永远拿不到** —— 枚举出来的反而是
    # `ellen_(zenless_zone_zero)` 这类 NPC 空壳。所以名单里的 tag 要单独补。
    allow = PLAYABLE_ROLES.get(work)
    if allow:
        have = {x["tag"] for x in out}
        need = sorted(t for t in allow if t not in have)
        if need:
            meta = fetch_tag_meta(need)
            for t in need:
                out.append({"tag": t, "count": meta.get(t, 0)})
            print(f"      （白名单补充 {len(need)} 条无后缀/未枚举到的 tag）")
    return out


# 目标作品（英文名 → safebooru 里的 copyright slug）
TARGET_SLUGS = {
    "zenless zone zero": "zenless_zone_zero",
    "honkai: star rail": "honkai:_star_rail",
    "goddess of victory: nikke": "nikke",
    "wuthering waves": "wuthering_waves",
}


# ============================================================================
# ③ wiki：中文名 + 性别
# ============================================================================

ZH_RE = re.compile(r"[\u4e00-\u9fff]")
JA_RE = re.compile(r"[\u3040-\u30ff]")
KO_RE = re.compile(r"[\uac00-\ud7af]")


def cache_path(kind, key):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
    return os.path.join(CACHE_DIR, kind, f"{safe}.{h}.json")


def cached_json(kind, key, fetcher, allow_net=True):
    """带磁盘缓存的 JSON 拉取。

    ⚠️ **失败也要缓存**（写一个 `null` 占位）。不缓存失败的话，
       没有 wiki 页的角色（404）每次重跑都会重新发请求 ——
       实测 828 条里有约 20% 是 404，会被反复拉，白等十几分钟。
    """
    p = cache_path(kind, key)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    if not allow_net:
        return None
    try:
        v = fetcher()
    except Exception:
        v = None                      # 404 / 超时：记成"确实没有"，不再重试
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(v, fh, ensure_ascii=False)
    return v


# 繁体专用字（简体里不会出现这些字形）。
# 用「扣分」而不是「字形转换」：转换表写错会把名字改烂，扣分最多是选到次优候选，
# 安全得多。实测踩过：`raiden_shogun` 的别名里同时有 `雷电将军`（简体）
# 与 `雷電将軍`（繁体），不扣分就会随机选中后者。
TRAD_ONLY = set(
    "電靈麗夢櫻劍戰實龍戀變闇貓兒內冊寫準麼麵黃點齊齒龜來個們為這說對時會與後東風飛馬鳥魚車"
    "門開關長陽陰雲霧顯願頭顏髮體樂樣業樓樹橋機檢權歡歲歷歸殺氣決沒溝滿澀澤濱瀨灣災烏無煙營爾獸現環畫當發盜監盤眾禦祿禍離種稱穩積窮竊筆節範築簡類紀純紙級紅約紋納紛紫細終組結絕統絲經綠維綱網緊線練編緩緣縮總織繞繪續纏罰罷罵義習聯聲職聽肅膚臉臨舉舊華萬葉蓋慮蟲衝補裝裡褲襪見觀規視覺覽訂計討記訊訓訪設許訴診詐評詞試詩話該詳認語誠誤課誰調談請論諜諷諸諾謀講謝證識譯議護讀讚豐貝貞負財貢貨販貪貫責貴買費貼賀資賈賓賣質賬賭購賽贈贊贏贓贖贛趙跡踐蹤軌軍軒軟較載輔輕輛輝輩輪輸轉辦辭農迴過達違遠適選遺邁還邊邏郵鄉鄭鄰釋釋針釘釣鈴銀銅銘銷鋒鋼錄錢錦鍵鍾鎖鏈鏡鐘鐵鑄鑑閉閒間閱闆闊闡陣陳陸隊階隨險隱雖雙雜雞難靜韻響頁頂項順須預頑頓頒領頸頻顆題顧飯飲飾飽餅養館駐騎驚驗鬥鮮鳳鳴麥齋"
)

# 这些是作品里的「称号」不是名字，中译名里最忌讳把称号当名字
TITLE_WORDS = ("骑士王", "王", "帝", "将军", "魔王", "恶魔", "公主", "女王",
               "大小姐", "会长", "社长", "老师", "博士", "舰长", "指挥官")


def pick_zh(other_names):
    """从 other_names 里挑最合适的中文名。挑不出来就返回空（宁缺毋滥）。

    评分而不是取最短 —— 取最短会把 `霊夢`（日文）选成 `博丽灵梦` 的中文名。
    规则：
      · 含假名的直接淘汰（那是日文）
      · 含繁体专用字的扣 4 分（简体优先）
      · 带中文括号后缀的加 3 分（`胡桃(原神)` 这种是中文社区条目，最可信）
      · 是称号词的扣 3 分
      · 名字越长越可信（中译名通常比日文缩写长）
    """
    cands = []
    for raw in (other_names or []):
        x = str(raw).strip()
        if not x or not ZH_RE.search(x):
            continue
        if JA_RE.search(x) or KO_RE.search(x):
            continue
        base = re.sub(r"[（(].*?[)）]", "", x).strip()
        if not base or not ZH_RE.search(base):
            continue
        score = len(base)
        if re.search(r"[（(][^)）]*[\u4e00-\u9fff][^)）]*[)）]", x):
            score += 3
        if any(ch in TRAD_ONLY for ch in base):
            score -= 4
        # ⚠️ 必须是「完全等于」称号才扣分。用 in 会把 `雷电将军`（官方中文名，
        #    正好含「将军」二字）也扣掉 —— 实测被误伤过一次。
        if base in TITLE_WORDS:
            score -= 3
        cands.append((score, base))
    if not cands:
        return ""
    cands.sort(key=lambda t: (-t[0], len(t[1])))
    return cands[0][1]


def guess_gender(body):
    """从 wiki 正文判性别。返回 'f' / 'm' / ''（不确定）。

    ⚠️ 判 'm' 的门槛刻意抬得很高 —— 误判成女性只是多收一个角色，
       误判成男性会**凭空丢掉**一个真角色。实测 `makima_(chainsaw_man)`
       的正文里男性代词更多（页面在讲电锯恶魔），按词频比大小会判成男性。
       所以：男性代词 ≥2 次、且是女性代词的 2 倍以上，才敢判 'm'。
    """
    if not body:
        return ""
    low = body.lower()
    f = len(re.findall(r"\b(she|her|hers|herself|girl|woman|women|female|"
                       r"sister|sisters|daughter|mother|lady|queen|princess|"
                       r"witch|maiden|goddess|idol|wife)\b", low))
    m = len(re.findall(r"\b(he|him|his|himself|boy|man|men|male|brother|"
                       r"brothers|son|father|king|prince|husband|gentleman)\b", low))
    if m >= 2 and m > f * 2:
        return "m"
    if f > 0:
        return "f"
    return ""


def fetch_wiki(tag, allow_net=True):
    def _get():
        return http_json(f"{MIRROR}/wiki_pages/{urllib.parse.quote(tag)}.json")
    d = cached_json("wiki", tag, _get, allow_net=allow_net)
    if not d:
        return {"zh": "", "gender": "", "other": []}
    body = d.get("body") or ""
    other = d.get("other_names") or []
    return {"zh": pick_zh(other), "gender": guess_gender(body), "other": other}


# ============================================================================
# ④ 合并 / 排序 / 截取
# ============================================================================

# 人气名额：保底作品**不占**这个数，所以总数会略超 2000
POP_SLOTS = 2000


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def slug_of(tag):
    """角色 tag → 缩略图文件名（不含扩展名）。"""
    s = re.sub(r"[^a-z0-9]+", "_", str(tag).lower()).strip("_")
    return s or "x"


def build(allow_net=True, verbose=True):
    t0 = time.time()
    print("① 造型台基线 …")
    girls, sk_male, sk_work = load_wardrobe()
    official = load_official()
    print(f"   女性 {len(girls)}（跳过男/其他 {sk_male} · 排除作品 {sk_work}）")

    src_roles = load_source_html_roles()
    print(f"   源 HTML 角色 {len(src_roles)}")

    # 造型台角色的 wiki 查询键：`n` 里的空格换成下划线就是 danbooru tag
    by_key = {}
    for c in girls:
        c["tag"] = c["name"].replace(" ", "_")
        # ⚠️ 作品名的取舍（有讲究，别想当然）：
        #
        #   括号里的那段，**有时是作品名、有时只是消歧义**：
        #       trailblazer_(honkai:_star_rail)  ← 作品名，且比造型台的 c 更准
        #       konpaku_youmu_(ghost)            ← 消歧义（幽灵半身），不是作品
        #       hakurei_reimu_(pc-98)            ← 消歧义（PC-98 时期版本）
        #   造型台的 c 字段反过来：对 `touhou` 这类是对的，但把星穹铁道的
        #   84 个角色全塞进了 `honkai (series)` 这个大桶。
        #
        #   所以规则是：**只有**当造型台给的是 `xxx (series)` 这种粗分类时，
        #   才用括号里的作品名覆盖它；否则以造型台为准。
        m = re.search(r"\(([^()]+)\)$", c["tag"])
        c_work = (c["work"] or "").strip()
        if m and ("(series)" in c_work or not c_work):
            c["work_tag"] = m.group(1).replace("_", " ").strip()
        else:
            c["work_tag"] = c_work
        by_key.setdefault(norm_key(c["name"]), c)
        by_key.setdefault(
            re.sub(r"[^a-z0-9]", "", f"{c['name']}||{c['work']}".lower()), c)

    # 作品 slug（用于拼 danbooru 角色 tag 的括号部分）
    work_slug = {}
    for c in girls:
        wk = c["work"]
        if wk:
            work_slug.setdefault(wk, wk.replace(" ", "_").replace("'", ""))

    print("\n② safebooru 补全目标作品 …")
    target_chars = {}
    for work, slug in TARGET_SLUGS.items():
        tags = fetch_work_tags(work, slug, official) if allow_net else []
        if not tags and not allow_net:
            tags = []
        print(f"   {work:28s} 枚举到基础角色 tag {len(tags)}")
        for t in tags:
            target_chars[t["tag"]] = {"work": work, "count": t["count"]}

    return {
        "girls": girls, "by_key": by_key, "official": official,
        "src_roles": src_roles, "target_chars": target_chars,
        "work_slug": work_slug, "skipped": (sk_male, sk_work),
        "elapsed": time.time() - t0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-net", action="store_true")
    ap.add_argument("--pop-slots", type=int, default=POP_SLOTS)
    args = ap.parse_args()

    data = build(allow_net=not args.no_net)
    girls = data["girls"]
    official = data["official"]
    target_chars = data["target_chars"]
    src_roles = data["src_roles"]

    print(f"\n③ 合并来源 …")
    print(f"   造型台女性 {len(girls)} · 目标作品 tag {len(target_chars)}"
          f" · 源 HTML {len(src_roles)}")

    # 目标作品 tag → 若是新角色，补一条记录
    by_tag = {}
    for c in girls:
        by_tag.setdefault(c["name"].lower().replace(" ", "_"), c)

    new_from_safebooru = 0
    for tag, meta in target_chars.items():
        if tag in by_tag:
            # 同时存在于造型台基线与 safebooru 的角色 —— 这是**唯一**能算出
            # 两边人气量纲换算系数的样本，必须把 safebooru 投稿数记下来。
            by_tag[tag]["_in_target"] = True
            by_tag[tag]["_count"] = meta["count"]
            continue
        base = tag.rsplit("_(", 1)[0]
        # 官方特征表里可能有（key = `name||work`）
        off_key = f"{base.replace('_', ' ')}||{meta['work']}"
        off = official.get(off_key) or {}
        by_tag[tag] = {
            "tag": tag,                     # ⚠️ 别删：后面全靠它
            "name": base.replace("_", " "),
            "work": meta["work"],
            "work_tag": meta["work"],
            "trigger": (off.get("trigger") or "").strip(),
            "pop": 0,
            "hair": "", "eyes": "",
            "tags": list(off.get("tags") or []),
            "src": "safebooru",
            "_in_target": True,
            "_count": meta["count"],
        }
        new_from_safebooru += 1
    print(f"   safebooru 新增 {new_from_safebooru} 条")

    # 源 HTML 的 222 条：只用来补中文名与 APPEAR，不新增条目
    zh_from_html = {}
    pools = json.load(open(POOLS_JSON, encoding="utf-8"))
    appear = pools.get("appear", {})
    for r in src_roles:
        head = r["trigger"].split(",")[0].strip().lower().replace(" ", "_")
        zh_from_html[head] = r["zh"]

    print(f"\n④ 判定性别（只对 safebooru 补进来的新角色拉 wiki）…")
    # 造型台的 g 字段已经保证是女性，不必再查；
    # 只有 safebooru 枚举出来的新角色需要判性别。
    need_gender = [t for t, c in by_tag.items() if c.get("_in_target")]
    print(f"   待判 {len(need_gender)} 条")

    lock = threading.Lock()
    done = [0]

    def _w(tag):
        r = fetch_wiki(tag, allow_net=not args.no_net)
        with lock:
            done[0] += 1
            if done[0] % 200 == 0:
                print(f"      … {done[0]}/{len(need_gender)}")
        return r

    if need_gender:
        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(_w, need_gender))

    gender_map = load_gender_map()
    print(f"   造型台全量性别表 {len(gender_map)} 条")

    dropped_male = 0
    for tag in list(by_tag):
        c = by_tag[tag]
        ftags = [t.lower() for t in c.get("tags") or []]
        # 优先级（高 → 低）：
        #   ① 造型台全量性别表    —— 人工标注过，最权威，且能给出"是男性"
        #   ② 官方特征 tags       —— 含 1girl / 1boy，机器可验证
        #   ③ wiki 正文代词       —— 兜底，只对 safebooru 新角色可用
        #   ④ 默认女性            —— 造型台女性子集里的就是女性
        gm = gender_map.get(tag) or gender_map.get(
            re.sub(r"[^a-z0-9]", "", tag.replace("_", " ") + "||"
                   + (c.get("work") or "")))
        if gm == "1boy":
            g = "m"
        elif gm == "1girl":
            g = "f"
        elif "1girl" in ftags or "female" in ftags:
            g = "f"
        elif "1boy" in ftags or "male" in ftags:
            g = "m"
        elif c.get("src") == "wardrobe":
            g = "f"
        elif c.get("_in_target"):
            g = (fetch_wiki(tag, allow_net=False) or {}).get("gender") or ""
        else:
            g = "f"
        if g == "m":
            dropped_male += 1
            del by_tag[tag]
            continue
        c["_gender"] = g or "?"

    # ── 去重：裸名 vs 规范 tag ──────────────────────────────────
    # 造型台用裸名（`ellen_joe`），danbooru 的正式 tag 是
    # `ellen_joe_(zenless_zone_zero)` —— 同一个角色会进两条。
    # 规则：同作品下若存在规范形式，丢弃裸名那条（规范 tag 带作品信息，
    # 且是模型训练时见过的写法）。
    canon_forms = {t for t in by_tag if "(" in t}
    dropped_dup = []
    for t in list(by_tag):
        if "(" in t:
            continue
        # ⚠️⚠️ v3.13.0：**白名单里的裸名优先保留**。
        #   绝区零 / 崩铁 / 妮姬的角色在 danbooru 上正牌写法**就是裸名**
        #   （`ju_fufu` / `hoshimi_miyabi`），而同作品的
        #   `ju_fufu_(zenless_zone_zero)` 只是个 NPC 空壳。
        #   没有这条豁免的话，正牌角色会被空壳挤掉 —— 这正是 v3.12.0
        #   之前"最新角色一个都收不进来"的真因。
        allow = _allow_of(by_tag[t])
        if allow and t in allow:
            continue
        wk = (by_tag[t].get("work_tag") or by_tag[t].get("work") or "")
        slug = wk.replace(" ", "_").replace("'", "")
        if slug and f"{t}_({slug})" in canon_forms:
            dropped_dup.append(t)
            del by_tag[t]

    # ── 零人气条目必须有「是女性」的正面证据 ─────────────────────
    # 这些是 danbooru 上存在、但 safebooru（SFW 镜像）一条投稿都没有的 tag。
    # 它们多是 NPC / 冷门角色，也确实混着男性（例：ZZZ 的 victor / geppetto）。
    # 没有任何性别佐证时**宁可不要** —— 用户明确要求「不包含男性角色」，
    # 少几个 NPC 的代价远小于混进男主角。
    dropped_npc = []
    for t in list(by_tag):
        c = by_tag[t]
        if int(c.get("_pop") or 0) > 0 or int(c.get("_count") or 0) > 0:
            continue
        gm = gender_map.get(t)
        ftags = [x.lower() for x in c.get("tags") or []]
        wiki_g = (fetch_wiki(t, allow_net=False) or {}).get("gender") or ""
        if gm == "1girl" or "1girl" in ftags or "female" in ftags or wiki_g == "f":
            continue
        dropped_npc.append(t)
        del by_tag[t]

    print(f"   判为男性剔除 {dropped_male} 条")
    print(f"   裸名重复剔除 {len(dropped_dup)} 条（同角色已有规范 tag）")
    print(f"   零人气且无女性佐证剔除 {len(dropped_npc)} 条")
    print(f"   保留 {len(by_tag)} 条")

    # ── 可玩角色白名单：只对**登记过的作品**生效（v3.12.0）────────────
    # safebooru 枚举出来的 tag 里混着 NPC / 怪物 / 声骸 / 周本 BOSS，而
    # danbooru 把它们的 category 也标成 character —— 程序区分不了，只能靠名单。
    # 没登记的作品**保持原行为**，不受影响。
    dropped_nonplay = 0
    for t in list(by_tag):
        c = by_tag[t]
        allow = _allow_of(c)
        if allow is None:
            continue                     # 该作品没登记 → 不动
        if t in allow or t in FORM_VARIANTS:
            # 白名单命中的角色，作品名**以白名单为准**（修造型台的粗分类）
            w2 = _TAG_TO_WORK.get(t)
            if w2 and c.get("work") != w2:
                c["work"] = w2
                c["work_tag"] = w2
            continue                     # 可玩角色 / 已登记的形态皮肤 → 保留
        dropped_nonplay += 1
        del by_tag[t]
    if dropped_nonplay:
        print(f"   非可玩角色（NPC/怪物/声骸）剔除 {dropped_nonplay} 条")
        print(f"   保留 {len(by_tag)} 条")

    print(f"\n⑤ 过滤与选取 …")

    # 人气归一：把 safebooru 的投稿数校准到造型台的人气量纲
    ratios = []
    for tag, c in by_tag.items():
        # 造型台基线（danbooru 全站投稿数）与 safebooru 镜像投稿数都要有，
        # 才能算出两者的量纲比例
        if c.get("_count") and c.get("pop"):
            ratios.append(c["pop"] / c["_count"])
    K = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
    print(f"   人气校准系数 K = {K:.2f}（基于 {len(ratios)} 个重叠样本）")

    for c in by_tag.values():
        pop = int(c.get("pop") or 0)
        cnt = int(c.get("_count") or 0)
        c["_pop"] = max(pop, int(cnt * K)) if cnt else pop

    target_list = [c for c in by_tag.values() if c.get("_in_target")]
    others = [c for c in by_tag.values() if not c.get("_in_target")]
    target_list.sort(key=lambda x: -x["_pop"])
    others.sort(key=lambda x: -x["_pop"])
    picked = target_list + others[: max(0, args.pop_slots)]
    print(f"   保底作品 {len(target_list)} 条 + 人气名额 {min(len(others), args.pop_slots)}"
          f" 条 = 合计 {len(picked)} 条")

    print(f"\n⑥ 给入选的 {len(picked)} 位拉中文名 …")
    # 只对最终入选者查 wiki —— 全量查是 6600 次请求，这里只要 2300 次。
    # 已经在阶段④查过的（目标作品）会直接命中缓存，不重复发请求。
    zh_done = [0]
    zh_lock = threading.Lock()

    def _zh(tag):
        r = fetch_wiki(tag, allow_net=not args.no_net)
        with zh_lock:
            zh_done[0] += 1
            if zh_done[0] % 250 == 0:
                print(f"      … {zh_done[0]}/{len(picked)}")
        return r

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(_zh, [c["tag"] for c in picked]))

    # 中文名优先级：① ZH_FIX 人工校正（最高）
    #               ② FORM_VARIANTS 白名单（形态/皮肤名，人工写的）
    #               ③ 源 HTML 的 221 条（人工核准过）
    #               ④ wiki 抓取
    # 最后统一过一遍繁→简（wiki 默认变体常常是繁体，用户口径要求简体）。
    for c in picked:
        c["zh"] = to_simplified(
            ZH_FIX.get(c["tag"])
            or FORM_VARIANTS.get(c["tag"])
            or zh_from_html.get(c["tag"])
            or c.get("zh")
            or (fetch_wiki(c["tag"], allow_net=False) or {}).get("zh")
            or "")
        c["work_tag"] = c.get("work_tag") or c.get("work") or ""
        c["trigger"] = build_trigger(c)

    out = render(picked, by_tag)
    print(f"\n⑦ 结果：{out['_meta']['counters']}")

    if args.dry:
        print("\n--dry：不写盘")
        return 0
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    print(f"\n已写出 {OUT_JSON}（{os.path.getsize(OUT_JSON)/1024:.0f} KB）")
    return 0


def build_trigger(c):
    """角色 tag + 作品 → danbooru 标准 trigger 串。

    ⚠️ 作品名一律取 **tag 括号里的那段**，不用造型台的 c 字段。
       实测造型台把星穹铁道的 84 个角色标成 `honkai (series)`，
       而正确的作品 tag 是 `honkai: star rail` —— 用错了作品标签，
       模型就认不出角色。
    """
    tag = c["tag"]
    name = re.sub(r"_\([^()]+\)$", "", tag).replace("_", " ").strip()
    wk = (c.get("work_tag") or "").strip()
    if wk and wk.lower() not in name.lower():
        return f"{name}, {wk}"
    return name


def render(picked, all_chars):
    """把选中的角色排成最终 JSON。"""
    used_slugs = {}
    chars = []
    for c in picked:
        base = slug_of(c["tag"])
        n = used_slugs.get(base, 0)
        used_slugs[base] = n + 1
        slug = base if n == 0 else f"{base}_{n}"
        chars.append({
            "tag": c["tag"],
            "name": c["name"],
            "zh": c.get("zh") or "",
            # 分组也用修正后的作品名：`honkai (series)` 这种大桶会把星穹铁道
            # 和崩坏3混成一个分类，浏览器里点「崩坏：星穹铁道」就筛不全。
            "work": (c.get("work_tag") or c["work"] or "").strip() or c["work"],
            # ⚠️ trigger 必须落盘：规则层拿它当 role 字段的实际取值。
            #    danbooru 的标准写法是 `jane doe, zenless zone zero`
            #    （角色名 + 作品名，空格分隔），不是 `jane_doe_(zenless_zone_zero)`。
            #    少了这一项，抽出来的是带下划线的 tag —— 模型也认，
            #    但与本生态（源 HTML / 造型台）的写法不一致。
            "trigger": c.get("trigger") or c["tag"],
            "pop": int(c["_pop"]),
            "hair": c.get("hair") or "",
            "eyes": c.get("eyes") or "",
            "tags": list(c.get("tags") or [])[:14],
            "src": c.get("src") or "",
            "thumb": slug,
        })
    chars.sort(key=lambda x: -x["pop"])

    # 作品聚合
    works = {}
    for c in chars:
        w = works.setdefault(c["work"], {
            "id": c["work"], "en": c["work"],
            "zh": WORK_ZH.get(c["work"], ""),
            "count": 0, "pop": 0,
            "target": c["work"] in TARGET_WORKS,
        })
        w["count"] += 1
        w["pop"] += c["pop"]
    work_list = sorted(works.values(), key=lambda w: (-w["count"], -w["pop"]))
    for w in work_list:
        w["id"] = slug_of(w["en"])

    return {
        "_meta": {
            "schema": "anima-wardrobe-v4/characters@1",
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sources": {
                "wardrobe_pool": "Comfyui-Anima-Wardrobe/presets/character_pool.json",
                "official_tags": "Comfyui-Anima-Tools-main/js/character_official_data.json",
                "tag_verifier": "safebooru.donmai.us（danbooru 的 SFW 镜像）",
                "source_html": "ANIMA提示词生成器.html",
            },
            "filters": {
                "gender": "仅女性（wiki 代词判定 + 官方特征 tags 双重确认）",
                "excluded_works": sorted(EXCLUDED_WORKS),
                "variant_tags": "已剔除换装/同人变体，只留基础角色 tag",
            },
            "target_works": TARGET_WORKS,
            "coverage": "至少覆盖到 2026-07（含该时点之前登场的全部角色）",
            "counters": {
                "total": len(chars),
                "works": len(work_list),
                "with_zh": sum(1 for c in chars if c["zh"]),
                "with_features": sum(1 for c in chars if c["tags"]),
            },
        },
        "works": work_list,
        "characters": chars,
    }


if __name__ == "__main__":
    sys.exit(main())
