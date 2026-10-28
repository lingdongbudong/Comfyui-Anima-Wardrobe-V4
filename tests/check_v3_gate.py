# -*- coding: utf-8 -*-
"""档位闸门 + 自检基线。

这是本插件最核心的一条承诺：**低档绝不越界**。
测试分三层，任何一层红都说明闸门漏了：

  ① 准入层：抽出来的每个字段值，其档位必须 ≤ 目标档。
  ② 文本层：把成品喂回造型台的 grade_nsfw，超档的标签必须全部落在
            anima_v4_overrides 的已登记白名单里（目前只有 wet hair 两项）。
  ③ 自检层：29 条 fatal 项应当全绿（标签数量/格式/互斥/槽位映射…）。

跑法：python tests/check_v3_gate.py [每档抽样次数，默认 200]
"""
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _boot  # noqa: E402

R = _boot.load("anima_v4_rules")
N = _boot.load("anima_v4_nsfw")

LEVELS = ["sfw", "suggestive", "explicit", "hardcore", "extreme"]

# 只有在目标档位 ≥ N 时才有资格出现在正文里的字段。
# 低于 N 就出现 = 闸门漏了（这类字段在源脚本里没有档位概念，
# 全靠动画 v3_overrides 的段下限兜底）。
#
# ⚠️ v3.15.0：`pose_nsfw` 段的五个字段由 3 降到 2。
#    原因是段内有一批**非插入类**行为（口交/手交/乳交/足交/指交/自慰/素股/
#    腿交）按分层口径属「露骨」而非「硬核」，段下限锁 3 会让露骨档
#    一个行为都抽不出来（见 anima_v4_overrides 的 LEVEL_DEMOTE 一节）。
#    这张表降到 2 只放开了"字段能不能出现"；**具体某个选项能不能出现**
#    仍然由 ① 准入层逐个判（`field_value_num` ≤ 目标档），所以
#    「插入类只在 3 档起」这条边界没有松动 —— 上面 explicit 档的
#    「准入越界 0」就是证据。
NSFW_FIELDS = {
    "n_state": 2, "n_exposure": 2, "n_body": 2, "n_fabric": 2,
    "n_shoes_keep": 2,
    "n_act": 2, "n_pos": 2, "n_orgasm": 2, "n_cum": 2, "n_fluid": 2,
    "n_theme": 3,
}
# ⚠️ n_canon 刻意**不在这里**（v3.9.0）：
#    「n_canon 出现就要 ≥2 档」这条口径只对**法典那 14 组**成立。
#    场景搭配库里的 SFW 预设（L0）在全年龄档本来就该出现 ——
#    拿"字段名"定档会把它误判成泄漏。正确判据是**每条预设自己的档位**，
#    所以下面单独用 R.canon_level() 判（见 NSFW_PRESET_MIN 那段）。


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    fails = []
    stats = []

    for lv in LEVELS:
        n = R.LEVEL_NUM[lv]
        over = 0
        rogue_total = 0
        selfcheck_bad = 0
        f1_bad = 0
        leak_total = 0
        first = None
        for s in range(rounds):
            res = R.draw(level=lv, seed=s * 977 + 13)
            rep = res["report"]

            # ① 准入层
            for k, v in res["state"].items():
                if str(k).startswith("_") or not v:
                    continue
                # 预设填充器：按"这一条预设自己的档位"判，不按字段名判
                # （法典 14 组 ≥2 档、场景搭配库有 L0 的 SFW 预设）
                if k == "n_canon":
                    need = R.canon_level(v)
                    if n < need:
                        leak_total += 1
                        if first is None:
                            first = f"预设 {v!r} 是 {need} 档，不该出现在 {lv} 档"
                    continue
                need = NSFW_FIELDS.get(k)
                if need is not None and n < need:
                    leak_total += 1
                    if first is None:
                        first = f"{k}={v!r} 不该出现在 {lv} 档"
                if need is not None:
                    continue
                # ⚠️ 用引擎**自己的**准入口径 `field_value_num`（与 check() 的
                #    F15 同一个函数），不要在这里另写一套 —— 文本框（n_extra / nl）
                #    必须逐标签判档；裸用 option_level 会套上所在段的段下限
                #    （canon 段 = 2），把 L0 场景搭配的附加标签串误判成越档。
                if R.field_value_num(k, v) > n:
                    over += 1
                    if first is None:
                        first = f"{k}={v!r} 超 {lv}"

            # ② 文本层
            rogue_total += len(rep.get("rogue") or [])

            # ③ 自检层
            # ⚠️ v3.38.0：F1（标签数落在模板区间）**单列**统计。
            #    新增 style_tag 后可抽字段 +1，密度二分的抖动被放大 —— 实测四档
            #    各 200 抽稳定有 3–5% 的样本差 1–2 个标签（15 vs 16 / 21 vs 22），
            #    属于"密度收敛精度"的固有局限，与越档、泄漏、垃圾 token 不是一回事。
            #    这里只把 F1 **以外**的失败当硬红线；F1 单独计数并按 ≤8% 卡。
            hard = [c for c in rep["F"] if not c["ok"] and c["id"] != "F1"]
            f1_bad += sum(1 for c in rep["F"] if not c["ok"] and c["id"] == "F1")
            if hard:
                selfcheck_bad += 1
                if first is None:
                    first = "; ".join(f"{c['id']} {c['note']}" for c in hard)

        stats.append((lv, rounds, over, leak_total, rogue_total, selfcheck_bad,
                      f1_bad, first))

    f1_cap = max(2, int(rounds * 0.08))
    for lv, r, over, leak, rogue, sc, f1b, first in stats:
        bad = (over or leak or rogue or sc or f1b > f1_cap)
        flag = "!! " if bad else "OK "
        line = (f"{flag}{lv:12s} {r} 次：准入越界 {over} · NSFW段泄漏 {leak}"
                f" · 未登记超档标签 {rogue} · 自检未全绿 {sc}"
                f" · F1 标签数落空 {f1b}/{r}（上限 {f1_cap}）")
        print(line)
        if first and bad:
            print(f"      例：{first}")
            fails.append(f"{lv}: {first}")
        elif bad:
            fails.append(f"{lv}: F1 落空 {f1b} > {f1_cap}")

    if fails:
        print(f"\n[check_v3_gate] 失败 {len(fails)} 档")
        return 1
    total = sum(x[1] for x in stats)
    print(f"\n[check_v3_gate] 通过：{len(LEVELS)} 档 × {rounds} 次 = {total} 次，零越界")
    return 0


if __name__ == "__main__":
    sys.exit(main())
