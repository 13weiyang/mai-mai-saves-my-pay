#!/usr/bin/env python3
"""实测每个商品在「到店自取」下的真实实付价，写进 demo_stores.json 的 pay 字段。

为什么需要它：
  菜单里的 cur（现价）不总是生效 —— 实测发现部分「多件套」的现价不生效
  （例：全明星八件套 cur=49.9，但接口实付 115.5）。
  演示页要算「省了多少」，必须用真实实付价，不能直接拿 cur 当数。

用法：
  python _fetch_realprice.py
"""
import sys, json, time
sys.path.insert(0, ".")
from mcd_client import McdClient

TOKEN_FILE = "../mcd-token.txt"
DATA = "demo_stores.json"


def main():
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip()
    c = McdClient(tok).connect()
    D = json.load(open(DATA, encoding="utf-8"))

    total = 0
    real = 0
    for sc, st in D.items():
        n = 0
        for m in st["meals"]:
            cur = m.get("cur")
            # 没折扣的，实付就是原价
            if cur is None or abs(cur - m["price"]) < 0.001:
                m["pay"] = m["price"]
                continue
            try:
                r = c.call("calculate-price", {
                    "storeCode": sc, "orderType": 1, "beType": 1,
                    "items": [{"productCode": m["code"], "quantity": 1}],
                })
                if isinstance(r, dict) and r.get("success"):
                    p = (r["data"].get("price") or 0) / 100.0
                    m["pay"] = round(p, 2)
                    n += 1
                    real += 1
                else:
                    m["pay"] = m["price"]
            except Exception:
                m["pay"] = m["price"]
            total += 1
            time.sleep(0.15)   # 温柔一点，别打太快
        print("%s: 实测 %d 款有折扣的" % (st["name"][:16], n))

    json.dump(D, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("完成：共处理 %d 款，其中 %d 款实测" % (total, real))


if __name__ == "__main__":
    main()
