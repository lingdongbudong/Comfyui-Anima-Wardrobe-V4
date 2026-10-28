# -*- coding: utf-8 -*-
"""重生成 `tools/playable_roles.json` —— 三保底作品的「女性可玩角色」名单。

## 这是什么

`build_characters.py` 对**登记过的作品**只保留白名单里的角色，用来把
safebooru 枚举出来的一大堆 NPC / 怪物 / 邦布 / 声骸挡在外面。鸣潮那份名单
只有 46 条，直接写在代码里；绝区零 / 崩铁 / 妮姬三家合计 300+ 条，放本文件
旁边的 `playable_roles.json`。

## 名单从哪来

**danbooru 官方「角色列表」wiki 页**的 *Playable characters* 区块：

    list_of_zenless_zone_zero_characters
    list_of_honkai:_star_rail_characters
    list_of_goddess_of_victory:_nikke_characters

好处是它自带可玩性标注（页面里另分了 Non-playable / Enemies 区块），
而且游戏出新角色时社区会把它补进去 —— 比手工维护的名单跟得紧。

## 过滤口径（用户 2026-10-15 拍板）

    · 只收**女性** —— wiki 代词 + `1girl`/`1boy` 共现**双判据**
    · 剔**非人类单位** —— 邦布 / 宠物 / 召唤物 / 武器 / 机械（人工名单，见下）
    · **收**联动角色（妮姬 × PERSONA / Nier / 电锯人 / Re:Zero / EVA 等）

⚠️ 为什么非人类要**人工列**而不是关键词匹配：
   wiki 正文里「her companion」/「her weapon」之类太常见，实测拿关键词筛
   会把 133 个真角色误伤（星见雅的 wiki 里就有 katana / tail）。
   数量只有二十来个，人工列反而准。

⚠️ 为什么性别要**两个判据**：
   wiki 代词单独用会漏 —— 男主 `wise` 的正文里写着「Wise, along with his
   sister ...」，`sister` 让女性词频追平男性词频，判据就不敢判男了。
   所以 `1boy` 显著占优（`boy >= 10 and girl < boy*0.85`）直接判男，优先于代词。
   ⚠️ 门槛 0.85 是调出来的：崩铁 Tribios 的三分身 `trianne`/`trinnon`
   女孩图少、男孩图接近（61/65、48/55），门槛放到 1.0 会把她们误杀。

## 用法

    python tools/build_playable_roles.py            # 重生成
    python tools/build_playable_roles.py --check    # 只对拍，不写盘
    python tools/build_playable_roles.py --list     # 打印当前名单

⚠️ 需要联网（safebooru）。缓存落在 `.cache_roles/`，第二次跑快很多。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "playable_roles.json")
CACHE_DIR = os.path.join(HERE, ".cache_roles")
MIRROR = "https://safebooru.donmai.us"
UA = "curl/8.4.0"

PAGES = {
    "zenless zone zero": "list_of_zenless_zone_zero_characters",
    "honkai: star rail": "list_of_honkai:_star_rail_characters",
    "goddess of victory: nikke": "list_of_goddess_of_victory:_nikke_characters",
}

# ── 人工剔除①：非人类单位 ────────────────────────────────────────────
# danbooru 的列表页把这些也算成 "playable"（它们确实能出战），但用户口径是
# **只要女性角色** —— 邦布 / 宠物 / 召唤物 / 武器写进角色库，随机角色会抽到
# 非人形，语义混乱。
NON_HUMAN = {
    # 绝区零
    "eous_(zenless_zone_zero)",          # 邦布（主角的）
    "pyrois_(zenless_zone_zero)",        # 主角的载具 / 邦布
    "bubblegum_(zenless_zone_zero)",     # Sunna 的虚拟宠物
    "tailless_(zenless_zone_zero)",      # 星见雅刀里的妖气
    "magus_(zenless_zone_zero)",         # 奥菲丝的机械尾
    "chalky_(zenless_zone_zero)",        # 希希芙的白蛇伙伴
    "lucy's_crew_(zenless_zone_zero)",   # 露西的三只野猪
    "anastella_(zenless_zone_zero)",     # 亚历山德丽娜的邦布
    "drusilla_(zenless_zone_zero)",      # 同上
    "kamanosuke_(zenless_zone_zero)",    # 浮波柚叶的狸猫
    "hu_wei_(zenless_zone_zero)",        # 橘福福的武器
    "qingming_bird_(zenless_zone_zero)",  # 仪玄的青鸟
    "seed_sr.",                          # 老席德（NPC 机械）
    # 崩坏：星穹铁道
    "svarog_(honkai:_star_rail)",        # 克拉拉的机器人
    "peppy_(honkai:_star_rail)",         # 艾丝妲的机器狗
    "numby_(honkai:_star_rail)",         # 托帕的宠物猪
    "lightning-lord_(honkai:_star_rail)",  # 景元的召唤物
    "fuyuan_(honkai:_star_rail)",        # 灵砂的香兽
    "ecliptic_inner_beast_(honkai:_star_rail)",  # 飞霄的召唤兽
    # 胜利女神：妮姬
    "anis_(star)_(nikke)",               # 武器（不是角色本体）
    "pascal_(nier:automata)",            # 联动里的机器人
    "andersen_(nikke)",                  # 列表页误列的 NPC
}

# ── 人工剔除②：男性（判据漏掉的）────────────────────────────────────
# ⚠️ 这几条的 `1girl`/`1boy` 共现**不够显著**（同人图里常和别的角色一起出现，
#    拉高了 `1girl` 计数），wiki 代词又判不出 —— 只能人工钉死。
MALE_MANUAL = {
    "wise_(zenless_zone_zero)",                       # 男主（wiki 正文的 "his sister" 让代词表追平）
    "pan_yinhu",                                      # 潘引壶（云岿山，男）
    "archer_(honkai:_star_rail)_(fate)",              # 联动 FATE（男）
    "gilgamesh_(honkai:_star_rail)_(fate)",           # 联动 FATE（男）
    "yingxing_(honkai:_star_rail)",                   # 应星（刃的前身，男）
    "aventurine_(waveflair)_(honkai:_star_rail)",     # 砂金·戏浪（男形态）
}

# ── 解析 ─────────────────────────────────────────────────────────────

LINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
# 标题形如 `h4. Playable characters` 或 `h4#playable-characters. Playable Characters`
HEAD = re.compile(r"^h([1-6])(?:#[a-z0-9_-]+)?\.\s*(.+?)\s*$")


def parse_playable(body: str):
    """取**第一个** playable 区块里的链接名。

    规则：遇到以 "playable" 开头的标题开始收集，再遇到**同级或更高级**标题结束。
    HSR 页面顺序是 Playable → Upcoming Playable → Non-playable，「同级即停」
    正好把 Upcoming 里那批**跨作品**联动预告（Astra Yao / Ellen Joe）挡在外面。
    """
    out, in_block, start_lvl = [], False, None
    for ln in body.replace("\r", "").split("\n"):
        m = HEAD.match(ln.strip())
        if m:
            lvl, title = int(m.group(1)), m.group(2)
            if not in_block:
                if title.lower().startswith("playable"):
                    in_block, start_lvl = True, lvl
            elif lvl <= start_lvl:
                break
            continue
        if in_block:
            for name in LINK.findall(ln):
                name = name.strip()
                if name and not name.startswith(("!post", "!asset", "#")):
                    out.append(name)
    return out


def to_tag(name: str) -> str:
    """danbooru wiki 链接名 → tag 名（小写、空白转下划线）。"""
    return re.sub(r"\s+", "_", name.strip().lower())


# ── HTTP（带磁盘缓存）─────────────────────────────────────────────────

def _cache_path(kind, key):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:80]
    return os.path.join(CACHE_DIR, kind, safe + ".json")


def _cached(kind, key, fetcher):
    p = _cache_path(kind, key)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    try:
        v = fetcher()
    except Exception:
        v = None                      # 404 / 超时 → 记成"没有"，别每次都重试
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(v, fh, ensure_ascii=False)
    return v


def _http(url, timeout=30):
    for _ in range(3):
        try:
            r = subprocess.run(["curl", "-s", "-A", UA, "--noproxy", "*",
                                "-m", str(timeout), url],
                               capture_output=True, text=True, timeout=timeout + 10)
            if r.stdout.strip():
                return r.stdout
        except Exception:
            pass
    return ""


def fetch_wiki(tag):
    """返回 {"body":..., "other":[...]}；失败返回空 body。"""
    def _get():
        txt = _http(f"{MIRROR}/wiki_pages/{urllib.parse.quote(tag)}.json")
        if not txt:
            return None
        try:
            d = json.loads(txt)
        except Exception:
            return None
        return {"body": (d.get("body") or "").replace("\r", " ").replace("\n", " "),
                "other": d.get("other_names") or []}
    return _cached("wiki", tag, _get) or {"body": "", "other": []}


def fetch_page(page):
    def _get():
        txt = _http(f"{MIRROR}/wiki_pages/{urllib.parse.quote(page)}.json", timeout=40)
        if not txt:
            return None
        try:
            d = json.loads(txt)
        except Exception:
            return None
        return {"body": d.get("body") or ""}
    return _cached("page", page, _get) or {"body": ""}


def fetch_counts(tags):
    """按 tag 批量拿 (总投稿, 1girl, 1boy)。"""
    def one(t):
        def c(q):
            txt = _http(f"{MIRROR}/counts/posts.json?tags={urllib.parse.quote(q)}", timeout=25)
            try:
                return int(json.loads(txt).get("counts", {}).get("posts") or 0)
            except Exception:
                return -1
        return {"tot": c(t), "g": c(t + " 1girl"), "b": c(t + " 1boy")}
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(zip(tags, ex.map(one, tags)))


# ── 性别判据 ─────────────────────────────────────────────────────────

def gender_by_wiki(body: str) -> str:
    """从 wiki 正文的代词/称谓频次判性别。'f' / 'm' / ''。

    ⚠️ 判 'm' 门槛刻意抬高 —— 误判成男性会**凭空丢掉**一个真角色。"""
    if not body:
        return ""
    low = body.lower()
    f = len(re.findall(r"\b(she|her|hers|herself|girl|woman|women|female|sister|"
                       r"sisters|daughter|mother|lady|queen|princess|witch|maiden|"
                       r"goddess|idol|wife)\b", low))
    m = len(re.findall(r"\b(he|him|his|himself|boy|man|men|male|brother|brothers|"
                       r"son|father|king|prince|husband|gentleman)\b", low))
    if m >= 2 and m > f * 2:
        return "m"
    if f > 0:
        return "f"
    return ""


def decide(work, tag, wcache, gcache):
    """综合判据 → (保留?, 理由)。"""
    if tag in NON_HUMAN:
        return False, "非人类单位"
    if tag in MALE_MANUAL:
        return False, "人工判男性"
    g = gender_by_wiki((wcache.get(tag) or {}).get("body", ""))
    if g == "m":
        return False, "wiki 判男性"
    # ⭐ 1boy 共现是**主判据**（比 wiki 代词可靠，见模块头注释）
    d = gcache.get(tag) or {}
    gg, bb = d.get("g", -1), d.get("b", -1)
    if gg >= 0 and bb >= 10 and gg < bb * 0.85:
        return False, f"1boy 显著占优({gg}/{bb})"
    if g == "f":
        return True, "wiki 女性"
    return True, "存疑保留"


# ── 主流程 ───────────────────────────────────────────────────────────

def build(verbose=True):
    """抓页面 + 判定，返回 ({"work": [tag, ...]}, 剔除明细)。"""
    pages = {}
    for work, page in PAGES.items():
        pages[work] = fetch_page(page).get("body") or ""
        if verbose:
            print(f"  页面 {page}: {len(pages[work])} 字符")

    all_tags, work_of = [], {}
    for work, body in pages.items():
        for n in parse_playable(body):
            t = to_tag(n)
            if t in work_of:
                continue
            work_of[t] = work
            all_tags.append(t)
    if verbose:
        print(f"  白名单候选合计 {len(all_tags)} 条，拉 wiki + 共现统计 …")

    wcache = {t: fetch_wiki(t) for t in all_tags}
    gcache = fetch_counts(all_tags)

    roles, dropped = {}, []
    for t in all_tags:
        ok, why = decide(work_of[t], t, wcache, gcache)
        if ok:
            roles.setdefault(work_of[t], []).append(t)
        else:
            dropped.append((work_of[t], t, why))
    if verbose:
        print(f"  剔除 {len(dropped)} 条：")
        for w, t, why in dropped:
            print(f"     [{w[:14]:14s}] {t:46s} {why}")
    return roles, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只对拍，不写盘")
    ap.add_argument("--list", action="store_true", help="打印当前名单")
    args = ap.parse_args()

    if args.list:
        cur = json.load(open(OUT_JSON, encoding="utf-8"))
        for w, v in (cur.get("roles") or {}).items():
            print(f"== {w} ({len(v)}) ==")
            for t in v:
                print("   ", t)
        return 0

    print("从 danbooru 角色列表页重生成白名单 …")
    roles, dropped = build()
    new = {
        "_meta": {
            "schema": "anima-wardrobe-v4/playable-roles@1",
            "source": "danbooru 官方角色列表页的 Playable characters 区块",
            "filter": ("只收女性（wiki 代词 + 1girl/1boy 共现双判据）；"
                       "剔非人类单位（邦布/宠物/召唤物/武器/机械）；收联动角色"),
            "regen": "python tools/build_playable_roles.py  （--check 对拍）",
            "counts": {k: len(v) for k, v in roles.items()},
        },
        "roles": roles,
    }

    if args.check:
        try:
            cur = json.load(open(OUT_JSON, encoding="utf-8"))
        except Exception:
            print("!! 现有 playable_roles.json 读不到")
            return 1
        a = {k: set(v) for k, v in (cur.get("roles") or {}).items()}
        b = {k: set(v) for k, v in roles.items()}
        ok = True
        for k in sorted(set(a) | set(b)):
            add, rem = b.get(k, set()) - a.get(k, set()), a.get(k, set()) - b.get(k, set())
            if add or rem:
                ok = False
                print(f"!! {k}: 新增 {sorted(add)}  消失 {sorted(rem)}")
        print("对拍通过 ✓" if ok else "对拍**不一致**（上游列表页动过了？）")
        return 0 if ok else 1

    json.dump(new, open(OUT_JSON, "w", encoding="utf-8", newline="\n"),
              ensure_ascii=False, indent=1)
    print(f"\n已写 {OUT_JSON}")
    for k, v in roles.items():
        print(f"   {k}: {len(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
