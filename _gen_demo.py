# -*- coding: utf-8 -*-
"""生成演示页用的多店数据（带官方分类）。跑一次就行，不必提交到仓库。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcd_client import McdClient
from mai_mai import load_token
from savings_engine import parse_meals, parse_promotions

# (门店编码, 门店名, 到用户的距离(米), 地址)
# ⚠️ 距离**必须来自接口实测、且同一次搜索**（关键词 = 用户所在片区）——
#    因为 query-nearby-stores 的距离是「离你给的那个地名」的距离：
#    同一家嘉秀路，关键词给「嘉秀」是 15 米，给「嘉秀路」就变 153 米。
#    ⛔ 千万别手写（v1.20 就是手写的，编出了"18.4 公里"那种一眼假的数）。
#    下面三家 = 关键词「嘉秀」一次搜出来的前三家，可比。
STORES = [
    ("1950751", "麦当劳北京嘉秀路餐厅", 15, "通和家园7号院5号楼102号"),
    ("1951040", "麦当劳北京亦庄信万广场餐厅", 1431, "经济技术开发区经惠东路7号院6号楼"),
    ("1950305", "麦当劳北京通州次渠餐厅", 2016, "次渠大街98号百发隆商场首层"),
]

client = McdClient(load_token()).connect()
out = {}

for code, name, dist, addr in STORES:
    meals_raw = client.call("query-meals", {
        "storeCode": code, "orderType": 1, "beType": 1,
    })
    meals = parse_meals(meals_raw)
    # ⚠️ 不再调 query-promotions —— 那是**企业团餐专属**规则（beType=6 写死），
    #    到店/外送都用不上（2026-10-10 实测：三家店大额单折扣恒为 0）。留空。
    promos = []

    mlist = []
    for m in meals.values():
        price = m["original_price"] or m["current_price"]
        if price <= 0:
            continue
        mlist.append({
            "code": m["code"],
            "name": m["name"],
            "price": price,
            "cur": m["current_price"],
            "kind": m["kind"],
            "category": m["category"],
            "tags": m["tags"],
            "img": m.get("img", ""),
        })

    plist = []
    for p in promos:
        d = p.get("discount")
        if d and d.get("rate"):
            try:
                rate = float(d["rate"])
                th = float(d.get("threshold", 0))
            except (TypeError, ValueError):
                continue
            if 0 < rate < 100:
                plist.append({"id": p.get("id"), "threshold": th, "pct": rate})

    out[code] = {
        "name": name, "distance": dist, "address": addr,
        "meals": mlist, "promos": plist,
    }
    print(f"{code} {name}: {len(mlist)} 道菜 / {len(plist)} 条活动")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "demo_stores.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

size = os.path.getsize(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_stores.json")
)
print(f"已写出 demo_stores.json：{size} 字节")
