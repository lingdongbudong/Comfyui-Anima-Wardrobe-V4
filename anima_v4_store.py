# -*- coding: utf-8 -*-
"""用户数据的持久化：命名预设 与 角色收藏。

两个文件都放在插件目录的 `presets/` 下：

    presets/user_presets.json    命名预设（一组配置快照）
    presets/user_favorites.json  收藏的角色 tag

为什么落在插件目录而不是浏览器 localStorage（2026-10-03 与用户确认）：
  · 换浏览器 / 清缓存后还在；
  · 能直接备份、能连同插件一起发给别人；
  · 与其它 presets 数据同源，好管理。

⚠️⚠️ 写盘一律**原子替换**（先写同目录 .tmp，再 os.replace 顶掉目标）。
    直接 `open(path, "w")` 是"先截断、后写"，中途任何异常都会留下一个
    0 字节文件 —— 用户的预设和收藏就全没了。
    这个坑我在本项目的工具脚本里踩过一次（见 ARCHIVE 坑⑥：
    `newline` 参数非法 → ValueError → 文件已被截断成空），存储层必须
    从一开始就防住。

⚠️ 所有读操作都**容错**：文件不存在 → 返回空结构；JSON 损坏 → 把坏文件
    另存为 `.broken` 后重新开始，绝不抛异常把面板带崩。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
PRESET_DIR = os.path.join(_HERE, "presets")

PRESETS_FILE = os.path.join(PRESET_DIR, "user_presets.json")
FAVORITES_FILE = os.path.join(PRESET_DIR, "user_favorites.json")

PRESET_SCHEMA = "anima-wardrobe-v4/presets@1"
FAVORITE_SCHEMA = "anima-wardrobe-v4/favorites@1"

MAX_PRESETS = 60            # 预设条数上限，防止无限增长
MAX_NAME_LEN = 40
MAX_FAVORITES = 3000

# 所有写操作串行化。文件都很小，一把锁足够，不需要更细的粒度。
_lock = threading.Lock()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write(path, data):
    """原子写：先写同目录的 .tmp，再 os.replace 顶掉目标。

    ⚠️ 不要改成 `open(path, "w")` —— 那是先截断后写，写一半崩了就是
       0 字节文件。`.tmp` + `os.replace` 在 Windows 上同样是原子的。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())      # 真正落盘，而不是停在 OS 缓存里
        except OSError:
            pass
    os.replace(tmp, path)


def _read(path):
    """读 JSON。任何异常都降级成空 dict，坏文件另存 `.broken`。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            raise ValueError("顶层不是对象")
        return d
    except Exception:
        # 宁可丢这一份坏文件，也不能让它把面板读崩 ——
        # 另存一份便于事后排查，而不是直接删掉。
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
        return {}


def _clean_name(name):
    return " ".join(str(name or "").split())[:MAX_NAME_LEN].strip()


def _summary(p):
    """一行摘要，给下拉列表显示用。"""
    lv = str(p.get("level") or "").strip()
    n = len([t for t in str(p.get("selected_roles") or "").split("|") if t.strip()])
    w = p.get("weights") if isinstance(p.get("weights"), dict) else {}
    wn = (len(w.get("sections") or {}) + len(w.get("fields") or {})
          + sum(len(v or {}) for v in (w.get("options") or {}).values()))
    bits = [lv or "—"]
    if n:
        bits.append(f"{n} 位角色")
    if wn:
        bits.append(f"权重 {wn} 项")
    if str(p.get("force_role") or "").strip():
        bits.append("手填角色")
    return " · ".join(bits)


# ============================================================================
# 预设
# ============================================================================

def list_presets():
    """全部预设（含完整内容，前端一次拿全，点加载零额外请求）。"""
    doc = _read(PRESETS_FILE)
    presets = doc.get("presets")
    if not isinstance(presets, dict):
        return []
    out = []
    for name, p in presets.items():
        if not isinstance(p, dict):
            continue
        out.append({
            "name": name,
            "saved_at": str(p.get("saved_at") or ""),
            "summary": _summary(p),
            # saved_at 是元信息，不属于"配置"，不往回传
            "data": {k: v for k, v in p.items() if k != "saved_at"},
        })
    out.sort(key=lambda x: x["saved_at"], reverse=True)
    return out


def save_preset(name, data):
    """保存（同名即覆盖）。返回最新列表。"""
    name = _clean_name(name)
    if not name:
        raise ValueError("预设名不能为空")
    if not isinstance(data, dict):
        raise ValueError("预设内容必须是一个对象")
    with _lock:
        doc = _read(PRESETS_FILE)
        presets = doc.get("presets")
        if not isinstance(presets, dict):
            presets = {}
        if name not in presets and len(presets) >= MAX_PRESETS:
            raise ValueError(f"预设数量已达上限 {MAX_PRESETS}，请先删掉几个")
        entry = dict(data)
        entry["saved_at"] = _now()
        presets[name] = entry
        _atomic_write(PRESETS_FILE, {
            "_meta": {"schema": PRESET_SCHEMA, "updated_at": entry["saved_at"],
                      "count": len(presets)},
            "presets": presets,
        })
    return list_presets()


def delete_preset(name):
    """删除。删不存在的名字不报错（幂等），返回最新列表。"""
    name = _clean_name(name)
    with _lock:
        doc = _read(PRESETS_FILE)
        presets = doc.get("presets")
        if isinstance(presets, dict) and name in presets:
            del presets[name]
            _atomic_write(PRESETS_FILE, {
                "_meta": {"schema": PRESET_SCHEMA, "updated_at": _now(),
                          "count": len(presets)},
                "presets": presets,
            })
    return list_presets()


# ============================================================================
# 收藏
# ============================================================================

def list_favorites():
    """收藏的角色 tag 列表（按收藏先后）。"""
    doc = _read(FAVORITES_FILE)
    fav = doc.get("favorites")
    if not isinstance(fav, list):
        return []
    return [t for t in fav if isinstance(t, str) and t.strip()]


def toggle_favorite(tag, on=None):
    """收藏 / 取消收藏。`on=None` 时按当前状态取反。返回最新列表。

    ⚠️ 幂等：重复收藏同一个不会产生两条。
    """
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("角色 tag 不能为空")
    with _lock:
        cur = list_favorites()
        has = tag in cur
        want = (not has) if on is None else bool(on)
        if want and not has:
            if len(cur) >= MAX_FAVORITES:
                raise ValueError(f"收藏已达上限 {MAX_FAVORITES}")
            cur.append(tag)
        elif not want and has:
            cur.remove(tag)
        _atomic_write(FAVORITES_FILE, {
            "_meta": {"schema": FAVORITE_SCHEMA, "updated_at": _now(),
                      "count": len(cur)},
            "favorites": cur,
        })
    return cur


# ============================================================================
# 场景收藏（v3.43.0）
# ============================================================================
#
# ⚠️ **另开一个文件**，不塞进 user_favorites.json：
#   · 那份文件的 schema 是 `favorites@1`，值域是**角色 tag**。混进 `sc_xxx`
#     会让 rules.favorite_role_keys() 拿它去角色库里比对，多出一批永远命中
#     不了的脏 key（表现是「仅收藏内随机」莫名变空池），且难以回溯；
#   · 分开存，用户能单独备份 / 迁移其中一份，互不牵连。
#
# 存的是**场景 id**（`sc_xxx`），不是显示名 —— 显示名会改（v3.33 改过一次），
# 拿名字收藏一改名就全丢。id 是稳定的。
#
# 数量上限按库总量（250 条）留足余量；超过就该考虑了，不该静默丢弃。

SCENE_FAV_FILE = os.path.join(PRESET_DIR, "user_scene_favorites.json")
SCENE_FAV_SCHEMA = "anima-wardrobe-v4/scene-favorites@1"
MAX_SCENE_FAVORITES = 600


def _scene_id_ok(sid):
    """场景 id 只允许 `sc_` + 小写字母数字下划线。

    与库里 250 条 id 的形态一致（最长 28 字符，这里放宽到 83）。
    拦掉手改文件和脏请求，避免把任意字符串写进收藏文件。
    """
    return bool(re.fullmatch(r"sc_[a-z0-9_]{1,80}", str(sid or "")))


def list_scene_favorites():
    """收藏的场景 id 列表（按收藏先后）。坏条目静默滤掉，不抛异常。"""
    doc = _read(SCENE_FAV_FILE)
    fav = doc.get("favorites")
    if not isinstance(fav, list):
        return []
    out = []
    for t in fav:
        if isinstance(t, str) and _scene_id_ok(t) and t not in out:
            out.append(t)
    return out


def toggle_scene_favorite(sid, on=None):
    """收藏 / 取消收藏一个场景。`on=None` 时按当前状态取反。返回最新列表。

    ⚠️ 幂等：重复收藏同一条不会产生两条。
    ⚠️ 取消一条**本来就不在**的收藏也返回成功（不报错）——
       面板在旧快照上点两下不该弹红字。
    """
    sid = str(sid or "").strip()
    if not _scene_id_ok(sid):
        raise ValueError(f"场景 id 不合法：{sid!r}")
    with _lock:
        cur = list_scene_favorites()
        has = sid in cur
        want = (not has) if on is None else bool(on)
        if want and not has:
            if len(cur) >= MAX_SCENE_FAVORITES:
                raise ValueError(f"场景收藏已达上限 {MAX_SCENE_FAVORITES}")
            cur.append(sid)
        elif not want and has:
            cur.remove(sid)
        _atomic_write(SCENE_FAV_FILE, {
            "_meta": {"schema": SCENE_FAV_SCHEMA, "updated_at": _now(),
                      "count": len(cur)},
            "favorites": cur,
        })
    return cur


# ============================================================================
# 用户角色覆盖层（v3.4.0：角色编辑 + 自定义角色）
# ============================================================================
#
# 为什么必须另存一层，而不是直接改 presets/anima_v4_characters.json：
#   那份 2687 条的角色库是 tools/build_characters.py 的**联网重建产物**，
#   重跑一次就把手改内容全冲掉。所以用户的新增/编辑一律落在
#   presets/user_characters.json，加载时"内置 + 覆盖层"合并（见 rules._merge_overlay）。
#   顺带保住 tests/check_v3_chars.py 的合规断言不被用户数据打破。
#
# 结构：
#   {
#     "_meta":  {...},
#     "edits":  {"<内置 tag>": {"trigger"|"zh"|"work"|"thumb": "…",
#                               "tags": ["…"]}},        # 只存被改的键
#     "custom": [ {完整角色记录, "src": "user"} ]
#   }
#
# ⚠️ `tags` 是**列表**，与其余字符串键的语义不同（见 _norm_tags / _parse_tags）；
#    "空列表" 的语义 = 清除这一项覆盖、回退内置标签（与"中文名留空"一致）。
#
# ⚠️ 图片一律另放 presets/user_thumbs/，**不放进 presets/thumbs/**：
#    tools/fetch_character_thumbs.py 的 verify_existing() 会遍历 thumbs/
#    删掉它判定不合格的图，重建缩略图时也可能清目录 —— 用户上传的图
#    放在那里等于随时可能被脚本误删。

# 内置角色库（v3.18.6 起支持从面板删除单个角色）
# ⚠️ 它是 tools/build_characters.py 的产物；删除写入 tombstone，重跑脚本会重建回来。
CHARACTERS_FILE = os.path.join(PRESET_DIR, "anima_v4_characters.json")
RETIRED_DIR = os.path.join(PRESET_DIR, "_retired")
RETIRED_CHARS_FILE = os.path.join(RETIRED_DIR, "anima_v4_characters.removed.json")

USER_CHARS_FILE = os.path.join(PRESET_DIR, "user_characters.json")
USER_THUMB_DIR = os.path.join(PRESET_DIR, "user_thumbs")
USER_CHARS_SCHEMA = "anima-wardrobe-v4/user-characters@1"

EDITABLE_KEYS = ("trigger", "zh", "work", "thumb", "tags", "hair", "eyes")

MAX_USER_CHARS = 500                 # 自定义角色条数上限
MAX_TRIGGER_LEN = 120
MAX_ZH_LEN = 24
MAX_WORK_LEN = 60
MAX_TAGS = 40                        # 单个角色的特征标签条数上限
MAX_TAG_LEN = 40                     # ⚠️ 引擎侧阈值：见下方 _check_tag_item
MAX_THUMB_BYTES = 2 * 1024 * 1024    # 上传图片上限 2MB
THUMB_SIZE = 160                     # 缩略图最长边（与面板卡片一致）

# danbooru 风格：小写字母 / 数字 / 空格 / , _ - : ( ) ' .
# ⚠️ 刻意**不收大写与中文** —— 角色标签是要喂给模型的英文 tag，
#    混进大写或中文在 SD/ANIMA 上匹配不到，属于"看着能用其实没用"。
_TRIGGER_RE = re.compile(r"^[a-z0-9][a-z0-9 ,_:()'.\-]*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

# 特征标签的字符集比 trigger **宽一点**（实测内置数据里出现过 . ' - : ( ) / ! +），
# 但同样不收大写与中文；逗号在标签里是分隔符、不是内容。
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 _\-:'()\./!+]*$")


def _clean_text(v, maxlen=None):
    """折掉多余空白（可选截断）。不做字符集校验（那是 _check_trigger 的事）。

    ⚠️ trigger 一律**不截断**：静默把用户的长标签切掉，他会以为存进去了，
       实际词条已经变了 —— 这种"看着能用其实没用"最难排查。宁可报错。
    """
    s = " ".join(str(v or "").split())
    return s[:maxlen].strip() if maxlen else s.strip()


def _check_trigger(t):
    if not t:
        raise ValueError("角色标签不能为空")
    if len(t) > MAX_TRIGGER_LEN:
        raise ValueError(f"角色标签过长（上限 {MAX_TRIGGER_LEN} 字符）")
    if not _TRIGGER_RE.match(t):
        raise ValueError("角色标签只能用英文小写字母、数字，以及空格 , _ - : ( ) ' .")
    return t


# ── 特征标签（tags：列表型字段）──────────────────────────────────────

def _split_tag_source(v):
    """接受「数组」或「逗号/换行分隔的字符串」两种输入。

    前端是一行一个输入框（传数组）；但用户完全可能整串粘进来，
    所以字符串形态要能拆 —— 逗号在 danbooru 里是分隔符，不是标签内容。
    """
    if v is None:
        return []
    if isinstance(v, str):
        return re.split(r"[,\n]", v)
    if isinstance(v, (list, tuple)):
        return list(v)
    raise ValueError("特征标签必须是一组字符串")


def _norm_tags(v):
    """读盘用的**容错**归一：小写、折空白、去重、丢弃超长项、截到上限。

    ⚠️ 这里绝不抛异常 —— 用户手改坏了 JSON，代价只能是"这条标签没生效"，
       不能是"整个面板打不开"。
    """
    out, seen = [], set()
    for it in _split_tag_source(v) if v is not None else []:
        t = " ".join(str(it or "").split()).lower()
        if not t or len(t) > MAX_TAG_LEN or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= MAX_TAGS:
            break
    return out


def _check_tag_item(t):
    """单个标签的**严格**校验（保存时用）。"""
    if len(t) > MAX_TAG_LEN:
        # 这条不是拍脑袋定的：anima_v4_rules.appearance_for() 会
        # `if len(t) > 40: continue` —— 存进去也永远不会被采用。
        # 与其让用户"加了没反应"，不如直接拒并说清原因。
        raise ValueError(
            f"标签「{t[:16]}…」超过 {MAX_TAG_LEN} 字符 —— "
            f"引擎会忽略超过 {MAX_TAG_LEN} 字符的特征标签，存了也不生效")
    if not _TAG_RE.match(t):
        raise ValueError(
            f"标签「{t}」只能用小写英文、数字，以及空格 _ - : ' ( ) . / ! +")
    return t


def _parse_tags(v):
    """保存用的**严格**解析。返回小写去重后的列表。

    ⚠️ 空列表是**合法**值，语义由调用方决定（内置角色 = 回退内置标签）。
    """
    out, seen = [], set()
    for it in _split_tag_source(v):
        t = " ".join(str(it or "").split()).lower()
        if not t or t in seen:
            continue
        if len(out) >= MAX_TAGS:
            raise ValueError(f"特征标签最多 {MAX_TAGS} 条")
        seen.add(t)
        out.append(_check_tag_item(t))
    return out


def _drop_empty(patch, list_keys=("tags",)):
    """过滤覆盖项：字符串键丢空串，列表键丢空列表。

    空值的语义是"清除这一项覆盖、回退内置值"，所以**不能落进文件**
    （落进去会让新写的编辑覆盖不掉旧的）。
    """
    out = {}
    for k, v in patch.items():
        if k in list_keys:
            if v:
                out[k] = v
        elif str(v or "").strip():
            out[k] = v
    return out


def user_thumb_slug(tag):
    """角色 tag → 用户图片 slug。

    ⚠️ 内置角色的图**不能**覆盖 presets/thumbs/ 里的原件（重建会丢），
       所以一律加 `user_` 前缀；自定义角色的 tag 本身就是 `user_` 开头，
       直接用。这样两条来源永不撞名。
    """
    tag = str(tag or "").strip()
    if not tag:
        return ""
    return tag if tag.startswith("user_") else "user_" + tag


def make_user_tag(trigger, taken=None):
    """按 trigger 生成唯一的自定义角色 tag（`user_` 前缀）。

    taken 由调用方传入"当前已经存在的全部 tag"（含内置）—— 存储层
    看不到内置角色库，所以这一步只能让调用方给全。
    """
    taken = {str(t).lower() for t in (taken or ())}
    base = _SLUG_RE.sub("_", (trigger or "").split(",")[0].strip().lower()).strip("_")
    base = base or "char"
    cand = ("user_" + base)[:120].strip("_")
    if cand.lower() not in taken:
        return cand
    for i in range(2, 10000):
        alt = f"{cand}_{i}"[:120]
        if alt.lower() not in taken:
            return alt
    return cand


def _norm_overlay(doc) -> dict:
    """把任意读到的结构归一成 {"edits": {...}, "custom": [...]}。

    ⚠️ 只保留 EDITABLE_KEYS 里的键、且**丢弃空值** —— 空值语义是
       "清除这一项覆盖、回退内置值"，所以不该落进文件（落进去会让
       新写的编辑覆盖不掉旧的）。
    """
    doc = doc if isinstance(doc, dict) else {}
    edits = doc.get("edits")
    edits = edits if isinstance(edits, dict) else {}
    clean_edits = {}
    for tag, patch in edits.items():
        if not isinstance(patch, dict):
            continue
        keep = {}
        for k, v in patch.items():
            if k not in EDITABLE_KEYS:
                continue
            if k == "tags":                 # 列表型：单独归一（空列表 = 清除覆盖）
                lst = _norm_tags(v)
                if lst:
                    keep[k] = lst
                continue
            s = str(v or "").strip()
            if s:
                keep[k] = s
        if keep:
            clean_edits[str(tag)] = keep
    raw_custom = doc.get("custom")
    custom = []
    if isinstance(raw_custom, list):
        for c in raw_custom:
            if isinstance(c, dict) and str(c.get("tag") or "").strip():
                custom.append(c)
    return {"edits": clean_edits, "custom": custom}


def load_user_characters() -> dict:
    """读用户角色覆盖层。文件缺席/损坏 → 空结构（_read 会容错）。"""
    return _norm_overlay(_read(USER_CHARS_FILE))


def _save_overlay(ov):
    _atomic_write(USER_CHARS_FILE, {
        "_meta": {"schema": USER_CHARS_SCHEMA, "updated_at": _now(),
                  "edits": len(ov["edits"]), "custom": len(ov["custom"])},
        "edits": ov["edits"],
        "custom": ov["custom"],
    })


def save_user_character(mode, tag, fields, taken_tags=None):
    """新增（mode=create）或编辑（mode=edit）一个角色。

    返回 (记录, 最新覆盖层)。

    · create —— 生成 `user_` 前缀的唯一 tag，整条追加进 custom；
    · edit   —— 先找 custom（直接改记录），找不到就当内置处理，写进 edits。
                触发词是必填的；中文名/作品/特征标签**留空即"清除覆盖、回退内置值"**，
                这与 _norm_overlay 丢弃空值的语义一致。
                ⚠️ 特征标签是**列表**：非空 = 整条替换内置 tags；空 = 回退内置。
                   顺序与大小写按用户输入归一（小写去重）。
    """
    mode = str(mode or "edit").strip().lower()
    fields = fields if isinstance(fields, dict) else {}
    # trigger **不截断**（见 _clean_text）：超长直接由 _check_trigger 报错
    trigger = _check_trigger(_clean_text(fields.get("trigger")))
    zh = _clean_text(fields.get("zh"), MAX_ZH_LEN)
    work = _clean_text(fields.get("work"), MAX_WORK_LEN)
    tags = _parse_tags(fields.get("tags"))
    # v3.44.4：发色 / 瞳色也要能改（空 = 清除覆盖、回退内置值，与 zh/work/tags 同语义）。
    # ⚠️ 为什么必须补这一层：`appearance_for()` 的取值优先级是
    #    ① APPEAR 表 → ② 角色库 `hair`/`eyes` 字段 → ③ 官方特征 tags。
    #    只覆盖 tags 打不过 ② —— 内置库把 `hair` 写成 `brown` 时，
    #    就算把 tags 里的 `brown hair` 删掉，出图仍然是 `brown hair`
    #    （2026-10-27 实测：明日香 orange/brown 冲突，改完 tags 无效）。
    hair = _clean_text(fields.get("hair"), 40)
    eyes = _clean_text(fields.get("eyes"), 40)

    with _lock:
        ov = load_user_characters()

        if mode == "create":
            if len(ov["custom"]) >= MAX_USER_CHARS:
                raise ValueError(f"自定义角色已达上限 {MAX_USER_CHARS}，请先删掉几个")
            taken = set(taken_tags or ())
            taken |= {str(c.get("tag") or "").lower() for c in ov["custom"]}
            taken |= {str(t).lower() for t in ov["edits"]}
            new_tag = make_user_tag(trigger, taken)
            rec = {
                "tag": new_tag,
                "name": trigger.split(",")[0].strip(),
                "zh": zh,
                "work": work,
                "trigger": trigger,
                "pop": 0,
                "hair": hair,
                "eyes": eyes,
                # ⚠️ 自定义角色**没有内置标签**可回退 → 空列表就是"它没有特征标签"，
                #    而不是"清除覆盖"（覆盖层的空值语义只对 edits 成立）。
                "tags": tags,
                "src": "user",
                "thumb": new_tag,          # 图 slug == tag；没上传图时退化成首字母色块
            }
            ov["custom"].append(rec)
            _save_overlay(ov)
            return rec, ov

        tag = str(tag or "").strip()
        if not tag:
            raise ValueError("缺少角色 tag")

        for c in ov["custom"]:
            if c.get("tag") == tag:
                c["trigger"] = trigger
                c["name"] = trigger.split(",")[0].strip()
                c["zh"] = zh
                c["work"] = work
                c["tags"] = tags           # 自定义角色：直接改记录（空 = 真的没有标签）
                if hair:
                    c["hair"] = hair
                if eyes:
                    c["eyes"] = eyes
                if not str(c.get("thumb") or "").strip():
                    c["thumb"] = tag
                _save_overlay(ov)
                return dict(c), ov

        cur = dict(ov["edits"].get(tag) or {})
        cur["trigger"] = trigger
        cur["zh"] = zh          # "" = 清除覆盖
        cur["work"] = work
        cur["tags"] = tags      # [] = 清除覆盖、回退内置标签
        cur["hair"] = hair      # "" = 清除覆盖、回退内置发色
        cur["eyes"] = eyes      # "" = 清除覆盖、回退内置瞳色
        cur = _drop_empty(cur)
        if cur:
            ov["edits"][tag] = cur
        else:
            ov["edits"].pop(tag, None)
        _save_overlay(ov)
        return {"tag": tag, **cur}, ov


def delete_user_character(tag):
    """删除一个**自定义**角色（连带删掉它上传的图）。内置角色不在 custom 里。

    返回最新覆盖层。tag 不在 custom 里 → 抛错（内置角色该走「恢复默认」）。
    """
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("缺少角色 tag")
    with _lock:
        ov = load_user_characters()
        before = len(ov["custom"])
        ov["custom"] = [c for c in ov["custom"] if c.get("tag") != tag]
        if len(ov["custom"]) == before:
            raise ValueError("只能删除自定义角色（内置角色请用「恢复默认」）")
        _save_overlay(ov)
    _delete_user_thumb(user_thumb_slug(tag))
    return ov


def delete_character(tag):
    """删除一个角色：自定义 → 删记录；**内置 → 从角色库物理移除**（v3.18.6）。

    返回 (kind, 最新覆盖层)，kind ∈ {"custom", "builtin"}。

    ⚠️ 内置删除是**写盘操作**：先把完整记录记进 tombstone
       （`presets/_retired/anima_v4_characters.removed.json`），再原子写回
       `presets/anima_v4_characters.json`。想找回就往 tombstone 里翻。
    ⚠️ 重跑 `tools/build_characters.py` 会把内置库整体重建 → 被删的会回来。
       那是刻意的：该脚本的语义是"从上游重新拉一遍"，不该记住本地删除。
    """
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("缺少角色 tag")
    with _lock:
        ov = load_user_characters()
        before = len(ov["custom"])
        ov["custom"] = [c for c in ov["custom"] if c.get("tag") != tag]
        if len(ov["custom"]) != before:
            _save_overlay(ov)
            kind = "custom"
        else:
            kind = _delete_builtin_character(tag)
            ov["edits"].pop(tag, None)
            _save_overlay(ov)
    if kind == "custom":
        _delete_user_thumb(user_thumb_slug(tag))
    return kind, ov


def _delete_builtin_character(tag):
    """从内置角色库移除一条，并记 tombstone。返回 "builtin"。"""
    doc = _read(CHARACTERS_FILE)
    chars = doc.get("characters")
    if not isinstance(chars, list) or not chars:
        raise ValueError("角色库文件不可读，无法删除")
    idx = None
    key = tag.strip().lower()
    for i, c in enumerate(chars):
        # ⚠️ 两种都能删：面板传的是**记录 tag**（`klee_(genshin_impact)`），
        #    而 selected_roles 里存的是 **trigger**（`klee, genshin impact`）。
        #    只认其中一种就会出现"删了没反应 / 报找不到"。
        if (str(c.get("tag") or "").strip().lower() == key
                or str(c.get("trigger") or "").strip().lower() == key):
            idx = i
            break
    if idx is None:
        raise ValueError("找不到这个角色（可能已经被删掉）")
    rec = chars.pop(idx)

    ret = _read(RETIRED_CHARS_FILE)
    removed = ret.get("removed")
    if not isinstance(removed, list):
        removed = []
    removed.append({"tag": tag, "removed_at": _now(), "record": rec})
    _atomic_write(RETIRED_CHARS_FILE, {
        "_meta": {"schema": "anima-wardrobe-v4/characters-retired@1",
                  "updated_at": _now(), "removed": len(removed)},
        "removed": removed,
    })

    doc["characters"] = chars
    _atomic_write(CHARACTERS_FILE, doc)
    return "builtin"


def delete_characters(tags):
    """批量删除。逐个走 `delete_character`，返回 (成功 tags, 失败明细, 覆盖层)。"""
    ok, bad = [], []
    for t in (tags or []):
        try:
            _kind, _ov = delete_character(t)
            ok.append(str(t))
        except ValueError as exc:
            bad.append({"tag": str(t), "error": str(exc)})
    return ok, bad, load_user_characters()


def reset_user_character(tag):
    """把**内置**角色恢复到内置原值（清掉 edits 项 + 删掉用户换的图）。

    自定义角色不能走这里（它不是"覆盖"，删掉就没了）→ 抛错让调用方改用删除。
    """
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("缺少角色 tag")
    with _lock:
        ov = load_user_characters()
        if any(c.get("tag") == tag for c in ov["custom"]):
            raise ValueError("这是自定义角色，请用「删除」而不是「恢复默认」")
        ov["edits"].pop(tag, None)
        _save_overlay(ov)
    _delete_user_thumb(user_thumb_slug(tag))
    return ov


# ── 用户图片 ─────────────────────────────────────────────────────────

def _sniff_ext(raw):
    """从文件头猜图片格式。认不出返回 None。"""
    b = bytes(raw[:16])
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


def _encode_thumb(raw):
    """把上传图压成 160px 的 webp。没装 Pillow 就原样存（面板三种都认）。

    ⚠️ 没 Pillow 时必须**先嗅探格式再决定扩展名** —— 直接按 .webp 存一个
       png 字节流，浏览器可能仍能显示（靠嗅探），但 /thumb 路由返回的
       Content-Type 会说谎，某些严格环境会当成下载。
    """
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(bytes(raw)))
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        im.thumbnail((THUMB_SIZE, THUMB_SIZE))
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=90, method=4)
        return "webp", buf.getvalue()
    except Exception:
        ext = _sniff_ext(raw)
        if ext not in ("png", "jpg", "webp"):
            raise ValueError("无法识别的图片格式（只支持 PNG / JPG / WEBP）")
        return ext, bytes(raw)


def _write_thumb_file(slug, raw):
    """原子落盘 + 清掉同 slug 的其它扩展名（避免路由先命中旧图）。"""
    if not _SLUG_SAFE_RE.fullmatch(slug or ""):
        raise ValueError("角色 tag 不合法，无法生成图片名")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ValueError("图片内容为空")
    if len(raw) > MAX_THUMB_BYTES:
        raise ValueError(f"图片过大（上限 {MAX_THUMB_BYTES // 1024 // 1024}MB）")
    os.makedirs(USER_THUMB_DIR, exist_ok=True)
    fmt, data = _encode_thumb(raw)
    dst = os.path.join(USER_THUMB_DIR, f"{slug}.{fmt}")
    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, dst)
    for ext in ("webp", "jpg", "png"):
        if ext == fmt:
            continue
        p = os.path.join(USER_THUMB_DIR, f"{slug}.{ext}")
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return fmt


_SLUG_SAFE_RE = re.compile(r"[a-z0-9_]{1,120}")


def _delete_user_thumb(slug):
    for ext in ("webp", "jpg", "png"):
        p = os.path.join(USER_THUMB_DIR, f"{slug}.{ext}")
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def set_user_thumb(tag, raw):
    """保存用户上传的预览图，并把指针写进覆盖层。返回图片 slug。

    自定义角色：直接更新它记录的 `thumb`；
    内置角色：写进 edits[tag]["thumb"]（与 trigger 等覆盖项共用一条）。
    """
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("缺少角色 tag")
    slug = user_thumb_slug(tag)
    with _lock:
        _write_thumb_file(slug, raw)
        ov = load_user_characters()
        for c in ov["custom"]:
            if c.get("tag") == tag:
                c["thumb"] = slug
                _save_overlay(ov)
                return slug
        cur = dict(ov["edits"].get(tag) or {})
        cur["thumb"] = slug
        ov["edits"][tag] = cur
        _save_overlay(ov)
    return slug


def clear_user_thumb(tag):
    """清掉用户上传的图，回到内置图（内置）或首字母色块（自定义）。"""
    tag = str(tag or "").strip()
    if not tag:
        raise ValueError("缺少角色 tag")
    slug = user_thumb_slug(tag)
    with _lock:
        ov = load_user_characters()
        for c in ov["custom"]:
            if c.get("tag") == tag:
                c["thumb"] = tag
                _save_overlay(ov)
                break
        else:
            cur = dict(ov["edits"].get(tag) or {})
            cur.pop("thumb", None)
            if cur:
                ov["edits"][tag] = cur
            else:
                ov["edits"].pop(tag, None)
            _save_overlay(ov)
    _delete_user_thumb(slug)
    return slug
