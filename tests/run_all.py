# -*- coding: utf-8 -*-
"""一键跑全部基线。测试只增不减，任何一项非 0 都算失败。

用法：
    python tests/run_all.py            # 默认档位抽样 200 次/档
    python tests/run_all.py 500        # 更狠一点

输出一行汇总，方便贴进交付报告。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)

PY = sys.executable or "python"
NODE = shutil.which("node") or os.environ.get("AV3_NODE", "node")


def run(title, cmd, cwd=PLUGIN):
    print("=" * 72)
    print(f"· {title}")
    print(f"  {' '.join(cmd)}")
    print("-" * 72)
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    out = (r.stdout or "") + (r.stderr or "")
    print(out.rstrip())
    return r.returncode, out


def main():
    rounds = sys.argv[1] if len(sys.argv) > 1 else "200"
    results = []

    # 夹具要从真后端导，前端冒烟才有意义 —— 必须排在冒烟前面
    rc, _ = run("生成前端夹具（从真后端导出）",
                [PY, "tools/dump_ui_fixtures.py"])
    results.append(("夹具生成", rc))

    for title, cmd in [
        ("词库零漂移 + 档位表一致性", [PY, "tests/check_v3_pools.py"]),
        ("NSFW 判定表与造型台对拍", [PY, "tests/check_nsfw_parity.py"]),
        ("档位闸门 + 自检基线", [PY, "tests/check_v3_gate.py", rounds]),
        ("字段联动（体位配对 / 表情配套 / 场景倾向）",
         [PY, "tests/check_v3_link.py", rounds]),
        ("服装智配 + 颜色合成基线", [PY, "tests/check_v3_color.py", "40"]),
        ("姿势段 + 暗示姿势档位基线", [PY, "tests/check_v3_pose.py", "120"]),
        ("上肢动作单槽（互斥 / 不缺席 / F18）",
         [PY, "tests/check_v3_hands.py", rounds]),
        ("三层权重语义基线", [PY, "tests/check_v3_weights.py"]),
        ("成品检查与自动修复基线", [PY, "tests/check_v3_repair.py"]),
        ("场景搭配预设库基线", [PY, "tests/check_v3_scenes.py"]),
        ("高等级保底（到位率 / 不越档 / 人数相容）",
         [PY, "tests/check_v3_levelfloor.py", rounds]),
        ("场景档位分层（命中率 / 不越档 / 显式优先）",
         [PY, "tests/check_v3_scenelevel.py", rounds]),
        ("特写搭配基线（随机隔离 + 零影响对拍）", [PY, "tests/check_v3_near.py"]),
        ("选中角色语义基线", [PY, "tests/check_v3_roles.py"]),
        ("角色库内容基线", [PY, "tests/check_v3_chars.py"]),
        ("角色官方发型对齐基线", [PY, "tests/check_v3_charhair.py"]),
        ("角色固定特征基线（特征注入 / 零漂移）",
         [PY, "tests/check_v3_charfeat.py"]),
        ("用户数据存储基线（预设/收藏）", [PY, "tests/check_v3_store.py"]),
        ("用户角色覆盖层基线（编辑/新增/图片）", [PY, "tests/check_v3_userdata.py"]),
        ("PNG 元数据注入基线（正负提示词）", [PY, "tests/check_v3_pngmeta.py"]),
    ]:
        rc, _ = run(title, cmd)
        results.append((title, rc))

    if shutil.which("node") or os.environ.get("AV3_NODE"):
        rc, out = run("前端面板冒烟（jsdom）",
                      [NODE, "tests/av3_ui_smoke.mjs"])
        results.append(("前端面板冒烟", rc))
    else:
        print("[SKIP] 找不到 node，跳过前端冒烟")

    print("=" * 72)
    print("汇总")
    print("-" * 72)
    bad = 0
    for name, rc in results:
        print(f"  {'PASS' if rc == 0 else 'FAIL'}  {name}")
        if rc != 0:
            bad += 1
    print("-" * 72)
    if bad:
        print(f"[run_all] 失败 {bad} / {len(results)}")
        return 1
    print(f"[run_all] 全部通过（{len(results)} 项，0 失败）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
