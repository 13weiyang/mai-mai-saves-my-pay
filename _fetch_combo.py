# -*- coding: utf-8 -*-
"""给 demo_stores.json 的每款餐品补「套餐可选结构」(rounds)。

为什么单独跑这个、而不是重跑 _gen_demo.py：
  重跑会把价格/活动**全量刷新**，容易把已经验过的演示数据改掉。
  这里只**新增**一个 combo 字段，不动任何已有数据。

数据源：MCP 的 query-meal-detail（餐品详情）。
  返回的 rounds[] = 一轮一轮的"必须从这几款里选 N 件"。
  例：堡堡随心拼 = 主食选2件 + 小食选3件 + 饮料选2件 = 7件。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcd_client import McdClient          # noqa: E402
from mai_mai import load_token            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "demo_stores.json")

with open(PATH, encoding="utf-8") as f:
    data = json.load(f)

client = McdClient(load_token()).connect()

hit = 0
total = 0
for scode, st in data.items():
    store_hit = 0
    for m in st["meals"]:
        total += 1
        try:
            r = client.call("query-meal-detail", {
                "storeCode": scode, "orderType": 1, "beType": 1, "code": m["code"],
            })
        except Exception:
            continue
        d = (r.get("data") or {}) if isinstance(r, dict) else {}
        rounds = d.get("rounds") or []
        if not rounds:
            continue

        combo = []
        for rd in rounds:
            opts = []
            for ch in (rd.get("choices") or []):
                raw = str(ch.get("diffPrice") or "").replace("+", "").replace("¥", "").strip()
                try:
                    diff = float(raw) if raw else 0.0
                except ValueError:
                    diff = 0.0
                opts.append({
                    "code": ch.get("code"),
                    "name": ch.get("name"),
                    "diff": diff,
                    "def": int(ch.get("quantity") or 0),
                })
            combo.append({
                "id": rd.get("id"),
                "name": rd.get("name"),
                "min": int(rd.get("minQuantity") or 0),
                "max": int(rd.get("maxQuantity") or 0),
                "choices": opts,
            })
        m["combo"] = combo
        hit += 1
        store_hit += 1
    print(f"{scode}: 补了 {store_hit} 款")

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

size = os.path.getsize(PATH)
print(f"共查 {total} 款，其中 {hit} 款有可选结构；已写回（{size} 字节）")
