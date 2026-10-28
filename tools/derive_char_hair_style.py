# -*- coding: utf-8 -*-
"""从角色库的**官方特征 tags** 推导发型初稿 → presets/char_hair_style.json

口径（v3.45.0）：
  · 只推导 hair_len / hair_tie / hair_curl 三项 —— 它们是「认人」的主特征。
  · 一个字段只填**一个**值（字段本身是单选）；tags 里出现多个冲突值时，
    按优先级取一个并记进 `_meta.ambiguous`，留给人工校。
  · 推不出来的字段**不写键**（= 该子项继续随机，绝不猜）。

用法：
  python tools/derive_char_hair_style.py            # 写盘（先备份）
  python tools/derive_char_hair_style.py --check    # 只报告，不写盘
"""
import io, json, os, shutil, sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRESETS = os.path.join(ROOT, "presets")
OUT = os.path.join(PRESETS, "char_hair_style.json")

# 每个字段的映射表 + 冲突优先级（越靠前越具体）
LEN_MAP = [("very long hair", "very long hair"), ("long hair", "long hair"),
           ("medium hair", "medium hair"),
           ("shoulder-length hair", "shoulder-length hair"),
           ("bob cut", "bob cut"), ("short hair", "short hair"),
           ("pixie cut", "pixie cut")]
TIE_PRIORITY = ["hime cut", "low twin braids", "twin braids", "french braid",
                "braid", "twintails", "high ponytail", "low ponytail",
                "side ponytail", "half updo", "double bun", "hair bun",
                "asymmetrical hair"]
CURL_PRIORITY = ["drill hair", "curly hair", "wavy hair", "messy hair",
                 "straight hair"]


def load(name):
    return json.load(io.open(os.path.join(PRESETS, name), encoding="utf-8"))


def merged_tags(base, overlay):
    """内置库 + 用户覆盖层（edits 的 tags 是整条替换）→ {tag: [tags]}"""
    edits = overlay.get("edits") or {}
    out = {}
    for c in base.get("characters", []):
        t = str(c.get("tag") or "")
        tags = [str(x).strip().lower() for x in (c.get("tags") or [])]
        p = edits.get(t) or {}
        if isinstance(p.get("tags"), list) and p["tags"]:
            tags = [str(x).strip().lower() for x in p["tags"] if str(x).strip()]
        out[t] = tags
    for c in overlay.get("custom") or []:
        out[str(c.get("tag") or "")] = [str(x).strip().lower()
                                        for x in (c.get("tags") or [])]
    return out


def pick(tags, candidates, priority=None):
    """返回 (选中值, 该字段所有命中值)。多命中时按 priority 取第一个。"""
    hits = [c for c in candidates if c in tags]
    if not hits:
        return None, []
    order = priority or candidates
    hits.sort(key=lambda x: order.index(x) if x in order else 99)
    return hits[0], hits


def main():
    check = "--check" in sys.argv
    keep = "--keep-existing" in sys.argv
    base = load("anima_v4_characters.json")
    overlay = load("user_characters.json")
    tags_of = merged_tags(base, overlay)

    styles, ambiguous = {}, {}
    for tag, tags in tags_of.items():
        if not tag or not tags:
            continue
        rec = {}
        v, hits = pick(tags, [a for a, _ in LEN_MAP])
        if v:
            rec["hair_len"] = dict(LEN_MAP)[v]
            if len(hits) > 1:
                ambiguous.setdefault(tag, {})["hair_len"] = hits
        v, hits = pick(tags, TIE_PRIORITY, TIE_PRIORITY)
        if v:
            rec["hair_tie"] = v
            if len(hits) > 1:
                ambiguous.setdefault(tag, {})["hair_tie"] = hits
        v, hits = pick(tags, CURL_PRIORITY, CURL_PRIORITY)
        if v:
            rec["hair_curl"] = v
            if len(hits) > 1:
                ambiguous.setdefault(tag, {})["hair_curl"] = hits
        if rec:
            styles[tag] = rec

    has_len = sum(1 for r in styles.values() if r.get("hair_len"))
    has_tie = sum(1 for r in styles.values() if r.get("hair_tie"))
    has_curl = sum(1 for r in styles.values() if r.get("hair_curl"))
    print(f"角色总数 {len(tags_of)} → 推导出条目 {len(styles)}")
    print(f"  hair_len {has_len} / hair_tie {has_tie} / hair_curl {has_curl}")
    print(f"  冲突（需人工校）{len(ambiguous)} 条")

    if check:
        print("[--check] 不写盘")
        return 0

    # --keep-existing：**人工校过的值优先**，重推只补缺项。
    # 没有这个开关，重跑一次就把所有人工修正冲掉（且没有任何提示）。
    kept = 0
    if keep and os.path.exists(OUT):
        try:
            old = json.load(io.open(OUT, encoding="utf-8")).get("styles") or {}
        except Exception:
            old = {}
        for tag, rec in old.items():
            if not isinstance(rec, dict):
                continue
            merged = dict(styles.get(tag) or {})
            for k, v in rec.items():
                if v and k in ("hair_len", "hair_tie", "hair_curl"):
                    if merged.get(k) != v:
                        kept += 1
                    merged[k] = v
            if merged:
                styles[tag] = merged
        print(f"[--keep-existing] 保留人工值 {kept} 项")

    doc = {
        "_meta": {
            "schema": "anima-wardrobe-v4/char-hair@1",
            "derived_from": "角色库官方特征 tags（danbooru）",
            "generated_by": "tools/derive_char_hair_style.py",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(styles),
            "ambiguous": {k: v for k, v in list(ambiguous.items())[:500]},
        },
        "styles": styles,
    }
    if os.path.exists(OUT):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:19]
        bak = OUT + f".bak-{stamp}"
        shutil.copy2(OUT, bak)
        print("备份:", os.path.basename(bak))
    tmp = OUT + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, OUT)
    print("已写出", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
