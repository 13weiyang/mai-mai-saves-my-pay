# -*- coding: utf-8 -*-
"""_fetch_coupons.py — 给演示页补「券」数据（跑一次就够）。

补什么：
  · 每店 `query-store-coupons` → 「这单能用哪些券」（结构化）
  · 全局 `query-my-coupons`   → 「卡包里有什么券」（markdown，解析成结构化）

🔒 安全：**只留看得见的信息（券名 / 用券价 / 有效期 / 标签 / 适用商品名 / 券图 URL），
   一律剥离 couponId / couponCode** —— 那是可核销的码，绝不能落到可能公开的页面上。
"""
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import McdClient  # noqa: E402
from mai_mai import load_token     # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE, "demo_stores.json")
STORES = ["1950751", "1951040", "1950305"]

client = McdClient(load_token()).connect()

with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)


def usable_now(valid):
    """券的有效期是「日期区间 +（可能还有）每日时段」。

    形如：
      2026-10-10 00:00-2026-10-16 23:59                       ← 只有区间
      2026-10-05 00:00-2026-10-11 23:59 10:00-22:00           ← 区间 + 每日时段
      2026-10-11 05:00-2026-10-11 10:29 周日 05:00-10:29       ← 单日 + 时段

    ⚠️ 在**拉数时**就算好（浏览器里解析太脆）—— 这是**快照**，页面要标抓取时间。
    """
    s = valid or ""
    m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})-(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", s)
    if not m:
        return None                      # 认不出来就别乱判
    d1, t1, d2, t2 = m.groups()
    now = datetime.now()
    try:
        start = datetime.strptime(d1 + " " + t1, "%Y-%m-%d %H:%M")
        end = datetime.strptime(d2 + " " + t2, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if not (start <= now <= end):
        return False
    m2 = re.search(r"(\d{2}:\d{2})-(\d{2}:\d{2})\s*$", s)
    if m2:
        a = datetime.strptime(m2.group(1), "%H:%M").time()
        b = datetime.strptime(m2.group(2), "%H:%M").time()
        if not (a <= now.time() <= b):
            return False
    return True


def parse_mine(raw):
    """把 query-my-coupons 的 markdown 解析成 [ {title, price, valid, tag, img} ]。

    ⚠️ 券图就在 markdown 里的 `<img src="...">` —— 那是**官方 App/小程序里那张券的大图**
       （路径形如 `.../campaign-offer/coupon/<hash>/优惠券大卡片图_1035×516px_1Mb.jpg`）。
       **不要把它删掉**（第一版就是删掉了，页面上才没有图）。
    """
    text = raw.get("_text") or ""
    out = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = block.split("\n")
        title = lines[0].strip()

        def grab(label):
            m = re.search(r"\*\*%s\*\*:\s*(.+)" % label, block)
            return m.group(1).strip() if m else ""

        mi = re.search(r'<img[^>]+src="([^"]+)"', block)
        out.append({
            "title": title,
            "price": grab("优惠"),
            "valid": grab("有效期"),
            "tag": grab("标签"),
            "img": mi.group(1) if mi else "",
            "usable_now": usable_now(grab("有效期")),
        })
    return out


print("… 拉卡包券（query-my-coupons）")
mine = parse_mine(client.call("query-my-coupons", {}))
print("   卡包 %d 张" % len(mine))

# 券价（数字）—— `query-store-coupons` 只给标题（如 "9.9元中杯冰美式"），**没有结构化价格**。
# 从卡包借：卡包每张带 `price`，形如 "¥9.9 (用券价格)"，按**标题对齐**取数；取不到再从标题里抠。
# 拿不到就写 None —— 页面那边遇到 None **跳过、不编**。
def _pay_of(price_text):
    m = re.search(r"(\d+(?:\.\d+)?)", price_text or "")
    return float(m.group(1)) if m else None


MINE_PAY = {}
for _c in mine:
    _v = _pay_of(_c.get("price"))
    if _v is not None:
        MINE_PAY.setdefault(_c["title"], _v)


def title_pay(title):
    if title in MINE_PAY:
        return MINE_PAY[title]
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", title or "")   # 兜底：从标题里抠
    return float(m.group(1)) if m else None

for sc in STORES:
    print("… 拉 %s 的门店可用券" % sc)
    r = client.call("query-store-coupons", {"storeCode": sc, "orderType": 1, "beType": 1})
    store_coupons = []
    for x in (r.get("data") or []):
        store_coupons.append({
            "title": x.get("title", ""),
            "products": [
                {"code": p.get("productCode"), "name": p.get("productName")}
                for p in (x.get("products") or [])
            ],
            "tradeDateTime": x.get("tradeDateTime", ""),
            "pay": title_pay(x.get("title", "")),   # 券价（数字）；取不到 = None
        })
        # ⚠️ 不写 couponId / couponCode
    if sc in data:
        data[sc]["coupons"] = {
            "store": store_coupons,
            "mine": mine,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        print("   本店当口可用 %d 张" % len(store_coupons))

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("已写回 demo_stores.json：%d 字节" % os.path.getsize(JSON_PATH))
