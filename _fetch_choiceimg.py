# -*- coding: utf-8 -*-
"""给 demo_stores.json 的「套餐自选项」补图。

为什么单独跑这个：
  套餐自选面板（「去选 N 件」弹层）原来**全是文字、没有图**，不直观
  （2026-10-10 提："不知道文字对应的是什么餐品，官网上都有图"）。

图从哪来：
  · 大部分选项 ＝ 当店菜单里也有同款 ⇒ **直接复用 meals 的 img**（不额外调接口）
  · 剩下的（可乐／薯条／麦旋风这类"只在套餐里出现、不单卖"的配角）：
    ① query-meals **压根不返回**它们（实测抽查 10 个全不在）
    ② query-meal-detail 的 choices 里**没有 image 字段**（只有 code/name/diffPrice…）
    ③ ⇒ 唯一正路：**把 choice.code 当商品**调 query-meal-detail，取 data.image
  ⛔ **不要拼 URL**：实测图片路径混着 ProductPool / 20260701 / 20250420，
     甚至有带时间戳后缀的（MS_1705_600_0_1744868229291.png）——拼必错。

产物：每个门店下加一个 "choiceImg": {code: url}（只含该店用到的）。
  只在**门店层**加字段 ⇒ 不动顶层 key、不动任何既有字段
  ⇒ 不影响 sortedCodes() / _check_demo.js 等任何既有遍历逻辑。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcd_client import McdClient      # noqa: E402
from mai_mai import load_token        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "demo_stores.json")

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)

# ① 先从各店菜单里收图（免费的）
imgs = {}
for st in data.values():
    for m in st.get("meals", []):
        if m.get("img"):
            imgs[m["code"]] = m["img"]
print("菜单里已有的图：%d 个 code" % len(imgs))

# ② 找出还缺图的 choice
need = set()
for st in data.values():
    for m in st.get("meals", []):
        for rd in (m.get("combo") or []):
            for c in rd.get("choices", []):
                if c.get("code") and c["code"] not in imgs:
                    need.add(c["code"])
print("套餐选项里缺图的：%d 个 code —— 逐个查商品详情" % len(need))

client = McdClient(load_token()).connect()
ok = fail = 0
for code in sorted(need):
    try:
        r = client.call("query-meal-detail", {
            "storeCode": "1950751", "orderType": 1, "beType": 1, "code": code,
        })
    except Exception as e:
        print("  x %-9s 调用异常：%s" % (code, e))
        fail += 1
        continue
    d = (r.get("data") or {}) if isinstance(r, dict) else {}
    img = d.get("image")
    if img:
        imgs[code] = img
        ok += 1
        print("  v %-9s %s" % (code, str(d.get("name"))[:20]))
    else:
        fail += 1
        print("  x %-9s 详情里也没图" % code)
    time.sleep(0.12)

print("补齐 %d 个，仍缺 %d 个" % (ok, fail))

# ③ 每店写入"自己用得到的"
for scode, st in data.items():
    used = set()
    for m in st.get("meals", []):
        for rd in (m.get("combo") or []):
            for c in rd.get("choices", []):
                if c.get("code"):
                    used.add(c["code"])
    st["choiceImg"] = {c: imgs[c] for c in sorted(used) if c in imgs}
    miss = sorted(c for c in used if c not in imgs)
    print("%s: 选项 %d 个 -> 带图 %d，缺 %d" % (scode, len(used), len(st["choiceImg"]), len(miss)))
    if miss:
        print("     缺：", miss)

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("\n已写回 %s（%d 字节）" % (PATH, os.path.getsize(PATH)))
