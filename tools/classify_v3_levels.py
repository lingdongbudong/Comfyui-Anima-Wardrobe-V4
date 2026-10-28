# -*- coding: utf-8 -*-
"""给词库里每一条选项算 NSFW 档位，产出 presets/anima_v4_levels.json。

为什么单独成一个文件而不是塞进 pools.json：
    pools.json 是「零漂移导出物」，必须与源 HTML 逐字节对应；
    档位是本插件的**派生数据**，随时可能因为判定表升级而重算。
    两者混在一起，重算档位就会破坏零漂移对拍。

判定口径：一条选项可能带多个标签（`1girl, solo, mature female`），
        取所有标签里**最高的档位** —— 与 grade_nsfw 的并集语义一致。

用法：
    python tools/classify_v3_levels.py [--quiet]
"""
import hashlib
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PLUGIN_ROOT)

from anima_v4_nsfw import NSFW_KEY_OF_NUM, NSFW_LABEL, NSFW_MAX, grade_nsfw  # noqa: E402
from anima_v4_overrides import LEVEL_DEMOTE, LEVEL_RAISE, apply_floor, calibrate, floor_of  # noqa: E402

POOLS = os.path.join(PLUGIN_ROOT, "presets", "anima_v4_pools.json")
LEVELS = os.path.join(PLUGIN_ROOT, "presets", "anima_v4_levels.json")

# 段落级兜底：某段完全没有可选标签（纯文本字段）时用这个默认档。
# 只影响「段级开关」的初值，不影响逐选项判定。
SECTION_FALLBACK = {
    "count": 0, "hair": 0, "face": 0, "body": 0, "makeup": 0,
    "cloth_sfw": 0, "pose_sfw": 0, "camera": 0, "scene": 0, "lighting": 0,
    "cloth_nsfw": 2, "pose_nsfw": 3, "special_nsfw": 3, "canon": 2,
    "nl_block": 0,
}


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def option_num(en):
    """一条选项（可能是逗号串）→ 档位数字。空串按 0 处理。"""
    tags = [t.strip() for t in str(en or "").split(",") if t.strip()]
    if not tags:
        return 0
    # grade_nsfw 一次吃整串，内部就是逐标签并集 —— 不用自己循环取 max，
    # 免得两边语义分家（历史教训：两套标度各判各的）
    return int(grade_nsfw(tags)["num"])


def canon_num(preset):
    """法典场景预设的档位：把它要写进 state 的所有标签拼起来判一次。

    为什么不按 `c1/c2/...` 的字面值判：段里存的是预设 id，不是英文标签，
    直接判会一条不落地全算 0 档 —— 那样「法典场景」就成了绕过档位闸门的后门。
    """
    bag = []
    for _k, v in (preset or {}).items():
        if isinstance(v, str) and v.strip():
            bag.extend(t.strip() for t in v.split(",") if t.strip())
    if not bag:
        return floor_of("canon")
    return apply_floor("canon", int(grade_nsfw(bag)["num"]))


def main():
    quiet = "--quiet" in sys.argv
    with open(POOLS, "r", encoding="utf-8") as fh:
        pools = json.load(fh)

    tag_levels = {}
    option_levels = {}
    section_max = {}
    section_hist = {}
    raw_options = 0
    demoted = []
    raised = []

    # 法典场景要先算好档位：它的「选项」存的是 c1..c14 预设 id，
    # 不是英文标签，直接判会全算 0 档 —— 那等于给档位闸门开了个后门。
    canon_levels = {
        k: canon_num(v) for k, v in sorted(pools.get("canon", {}).items())
    }

    for sec in pools["sections"]:
        hist = Counter()
        smax = 0
        for fld in sec["fields"]:
            if fld.get("type") in ("text",):
                continue
            per_field = {}
            for zh, en in fld.get("opts", []):
                raw_options += 1
                if fld["key"] == "n_canon":
                    n0 = canon_levels.get(en, 0)
                else:
                    n0 = option_num(en)
                # 先上段下限，再走人工校准链（先补盲区上抬、再纠正上下文下调）。
                # 顺序不能反：反了的话「头发段人工降级」会被段下限抬回去
                # （虽然头发段没下限，但顺序写对才经得起以后加段）。
                n0 = apply_floor(sec["id"], n0)
                n, changes = calibrate(fld["key"], en, n0)
                for direction, src, dst, why in changes:
                    if direction == "demote":
                        demoted.append((fld["key"], en, src, dst, why))
                    else:
                        raised.append((fld["key"], en, src, dst, why))
                per_field[en] = n
                hist[n] += 1
                smax = max(smax, n)
                for t in [x.strip() for x in str(en).split(",") if x.strip()]:
                    tag_levels[t] = max(tag_levels.get(t, 0), n)
            if per_field:
                option_levels[fld["key"]] = per_field
        section_max[sec["id"]] = smax if smax else SECTION_FALLBACK.get(sec["id"], 0)
        section_hist[sec["id"]] = dict(sorted(hist.items()))

    payload = {
        "_meta": {
            "schema": "anima-wardrobe-v4/levels@1",
            "pools_sha256": sha256_file(POOLS),
            "nsfw_module": "anima_v4_nsfw.py",
            "generated_by": "tools/classify_v3_levels.py",
            "counters": {
                "tags": len(tag_levels),
                "fields": len(option_levels),
                "options_raw": raw_options,
                # option_levels 是 dict，同一字段里重复的英文选项会被折叠 ——
                # 源脚本 face/eyes_color 里「异色瞳 heterochromia」就写了两遍。
                "options_unique": sum(len(v) for v in option_levels.values()),
                "demoted": len(demoted),
                "raised": len(raised),
                "max": NSFW_MAX,
            },
        },
        "section_max": section_max,
        "section_floor": {sid: floor_of(sid) for sid in section_max},
        "canon_levels": canon_levels,
        "tag_levels": dict(sorted(tag_levels.items())),
        "option_levels": option_levels,
    }

    with open(LEVELS, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    if not quiet:
        print(f"[classify_v3_levels] 已写出 {LEVELS}")
        print(f"  标签 {len(tag_levels)} · 字段 {len(option_levels)}"
              f" · 选项 {raw_options}（去重 {payload['_meta']['counters']['options_unique']}）"
              f" · 人工校准 降{len(demoted)}/升{len(raised)}")
        print("\n  段落  最高档  各档选项数（0/1/2/3/4）")
        for sid, smax in section_max.items():
            h = section_hist.get(sid, {})
            bars = " ".join(f"{k}:{h.get(k, 0)}" for k in range(NSFW_MAX + 1))
            print(f"  {sid:12s} {smax}   {bars}")
        print("\n  各档标签总数：")
        th = Counter(tag_levels.values())
        for n in range(NSFW_MAX + 1):
            print(f"    {n} {NSFW_LABEL[NSFW_KEY_OF_NUM[n]]:4s}  {th.get(n, 0)}")
        print("\n  法典场景档位：", " ".join(
            f"{k}={v}" for k, v in canon_levels.items()))
        if demoted:
            print("\n  人工校准（只降不升）：")
            for fld, en, n0, n, why in demoted:
                print(f"    [{fld}] {en!r}  {n0} → {n}")
        if raised:
            print("\n  人工校准（只升不降）：")
            for fld, en, n0, n, why in raised:
                print(f"    [{fld}] {en!r}  {n0} → {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
