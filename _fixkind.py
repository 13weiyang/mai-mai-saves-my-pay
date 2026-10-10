# -*- coding: utf-8 -*-
"""把 demo_stores.json 里过期的 kind 字段，按当前 classify() 重新判一遍。

为什么需要它：
  `_gen_demo.py` 要联网 + MCP Token 才能重跑；但改了 classify() 之后
  （比如新增了 "kids" 分类），demo_stores.json 里的 kind 就是陈旧值 ——
  于是「代码是对的、页面是错的」，极难排查。
  这个脚本就地重判，不联网、秒完成。

用法：
    python _fixkind.py            # 重判并写回（会打印改动统计）
    python _fixkind.py --check    # 只检查不写回

⚠️ 改完记得跑 `python _inject.py` 把数据重新内嵌进 演示.html。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import savings_engine as E  # noqa: E402

DATA = os.path.join(BASE, "demo_stores.json")


def main():
    check_only = "--check" in sys.argv
    with open(DATA, encoding="utf-8") as f:
        raw = json.load(f)

    total = 0
    for code, st in raw.items():
        print(f"{code} {st['name']}")
        for m in st["meals"]:
            new_kind = E.classify(m["name"], m.get("category", ""))
            if new_kind != m["kind"]:
                print(f"    ~ {m['name']}: {m['kind']} -> {new_kind}")
                total += 1
            m["kind"] = new_kind
        kids = [m for m in st["meals"] if m["kind"] == "kids"]
        print(f"    kids={len(kids)}: "
              + " / ".join(f"{m['name']}¥{m['price']}" for m in kids))

    if check_only:
        print(f"\n共 {total} 条需修正（--check，未写回）")
        return

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n共修正 {total} 条 kind 字段，已写回 demo_stores.json"
          f"（{os.path.getsize(DATA)} 字节）")
    print("记得再跑 python _inject.py 同步到 演示.html")


if __name__ == "__main__":
    main()
