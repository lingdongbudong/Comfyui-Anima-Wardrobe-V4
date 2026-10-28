# -*- coding: utf-8 -*-
"""把面板要的接口数据落成测试夹具。

为什么要有这一步：
    前端冒烟测试里的 fetch 桩**必须与后端逐字一致**，否则测的是
    一个想象出来的后端 —— 真实接口改了字段名，冒烟照样全绿，
    上线才发现面板一片空白。所以夹具从 nodes.py 的真函数里导出，
    而不是手写一份。

用法：python tools/dump_ui_fixtures.py
输出：tests/fixtures/pools.json · contract.json · characters.json

⚠️ `characters.json` 是 v3.2.0 才补上的。补它之前，冒烟里 `/characters`
   的桩是**手写**的，而我把角色记录的 `work` 写成了 slug —— 真实数据里
   它其实是**作品英文名**，于是「点 IP 作品 → 空列表」这个线上 bug
   在 66 条断言全绿的情况下溜了过去。夹具必须与真后端同源，这一条没有例外。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(PLUGIN_ROOT, "tests", "fixtures")

sys.path.insert(0, os.path.join(PLUGIN_ROOT, "tests"))

import _boot  # noqa: E402


def main():
    nodes = _boot.load("nodes")
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, fn in (("pools", nodes.pools_payload),
                     ("contract", nodes.contract_payload),
                     ("characters", nodes.characters_payload),
                     ("scenes", nodes.scenes_payload)):
        data = fn()
        path = os.path.join(OUT_DIR, f"{name}.json")
        # ⚠️ characters **不能抽样**：夹具里 works[].count 与 characters 里
        #    属于该作品的实际条数必须一致，否则「点作品 → 卡片数 == count」
        #    这条断言测的就是假数据，等于没测。所以全量导出（约 780 KB）。
        #    它也不加 indent —— 机器读的文件，紧凑格式省一半体积。
        indent = None if name == "characters" else 1
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=indent)
            fh.write("\n")
        print(f"[dump_ui_fixtures] 写出 {path}"
              f"（{os.path.getsize(path) / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
