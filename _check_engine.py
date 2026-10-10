# -*- coding: utf-8 -*-
"""_check_engine.py — Python 侧回归断言（吃 demo_stores.json 的归一化数据）

覆盖：
  1) adult 局不出现 kids/family
  2) 带娃局儿童餐份数 = 儿童人数
  3) 带娃局必含官方亲子套餐（未点名口味时）
  4) 逐娃点名：点谁出谁
  5) kids(亲子餐) 与 mixed(成人+亲子) 同预算结果不同
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savings_engine import plan_cheapest, classify  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "demo_stores.json"), encoding="utf-8"))

fails, warns = [], []


def to_meals(lst):
    out = {}
    for m in lst:
        cat = (m.get("category") or "").replace("//", "/")
        out[m["code"]] = {
            "code": m["code"], "name": m["name"],
            # ⚠️ demo JSON：price = 原价，cur = 现价。
            #    引擎按【原价】凑门槛（促销折扣在原价上算），
            #    所以 original_price 取 price，别写成 cur（那是特价，会算错）。
            "original_price": m.get("price"),
            "current_price": m.get("cur") or m.get("price"),
            "img": m.get("image", ""), "category": cat,
            "kind": classify(m["name"], cat),
        }
    return out


def to_promos(lst):
    return [{"discount": {"threshold": p.get("threshold"), "rate": p.get("pct")}}
            for p in lst]


# ⚠️ 配餐器（plan_cheapest）现在是**企业团餐专用**能力 ——
#    普通到店/外送没有满减（2026-10-10 实测，三家店大额单折扣恒为 0），
#    所以 demo_stores.json 里的 promos 是空的。
#    这个脚本测的是**配餐算法本身**，所以喂它一组**企业团餐门槛**当夹具
#    （是测试夹具，不是她门店的真实规则）。真规则要用 fetch_group_promotions() 现拉。
GROUP_TIERS = [
    {"threshold": 300, "pct": 22},
    {"threshold": 500, "pct": 26},
    {"threshold": 1000, "pct": 30},
    {"threshold": 2000, "pct": 34},
]

stores = [(c, to_meals(s["meals"]), to_promos(GROUP_TIERS))
          for c, s in DATA.items()]
budgets = [300, 500, 800, 1200]
total = 0

for code, meals, promos in stores:
    kids_pool = sorted([m for m in meals.values() if m.get("kind") == "kids"],
                       key=lambda m: m["current_price"])
    fam_pool = [m for m in meals.values() if m.get("kind") == "family"]
    kid_codes = [m["code"] for m in kids_pool]

    # ⭐ 掉线保护：预算 300 起、任何模式都该出得来方案。
    #    修 bug 前「¥300 亲子餐」会返回 None，被静默跳过、长期没人发现。
    for diners, n in (("adult", 0), ("kids", 1), ("kids", 2), ("mixed", 2)):
        for b in budgets:
            total += 1
            if plan_cheapest(meals, promos, b, diners=diners, kids=n) is None:
                fails.append(f"[{code}] 无方案 {diners} {n}娃 ¥{b}")

    # 1) 纯大人局
    for b in budgets:
        total += 1
        pl = plan_cheapest(meals, promos, b, diners="adult", kids=0)
        if pl is None:
            continue
        bad = [i["code"] for i in pl["items"]
               if meals[i["code"]].get("kind") in ("kids", "family")]
        if bad:
            fails.append(f"[{code}] adult ¥{b} 混进带玩具餐 {bad}")

    # 2/3) 带娃局：份数锁定 + 官方套餐
    for diners in ("kids", "mixed"):
        for n in (1, 2, 3):
            for b in budgets:
                total += 1
                pl = plan_cheapest(meals, promos, b, diners=diners, kids=n)
                if pl is None:
                    continue
                toy_cnt = sum(i["count"] for i in pl["items"]
                              if meals[i["code"]].get("kind") in ("kids", "family"))
                if toy_cnt != n:
                    fails.append(f"[{code}] {diners} {n}娃 ¥{b} 带玩具餐 {toy_cnt}≠{n}")
                has_fam = any(meals[i["code"]].get("kind") == "family"
                              for i in pl["items"])
                if fam_pool and n > 0 and not has_fam:
                    warns.append(f"[{code}] {diners} {n}娃 ¥{b} 没走官方套餐")

    # 4) 逐娃点名
    if len(kid_codes) >= 2:
        for i, c1 in enumerate(kid_codes):
            for c2 in kid_codes[i:]:
                total += 1
                pl = plan_cheapest(meals, promos, 500, diners="mixed",
                                   kids=2, kid_picks=[c1, c2])
                if pl is None:
                    fails.append(f"[{code}] 点名 {c1},{c2} 无解")
                    continue
                got = {i["code"] for i in pl["items"] if meals[i["code"]].get("kind") == "kids"}
                if c1 not in got or c2 not in got:
                    fails.append(f"[{code}] 点名 {c1},{c2} 结果 {got}")

    # 5) kids vs mixed 应不同
    for b in budgets:
        total += 1
        a = plan_cheapest(meals, promos, b, diners="kids", kids=1)
        m = plan_cheapest(meals, promos, b, diners="mixed", kids=1)
        if a and m:
            ka = sorted((i["code"], i["count"]) for i in a["items"])
            km = sorted((i["code"], i["count"]) for i in m["items"])
            if ka == km:
                warns.append(f"[{code}] ¥{b} 亲子餐与成人+亲子结果相同")

# ⭐ 6) 单款份数上限（bug 9 · 2026-10-09 报）
#
# 起因：原话「会出现某一款被默认点了5份。这搁谁能乐意啊。」
# 实测最离谱的是 ¥2000 亲子局 →「BFF四宫格小食盘双人餐 ×13」。
#
# ⚠️ 为什么这条要进回归：
#    上一轮的教训是"**跳过**最危险"（¥300 亲子局静默返回 None，
#    长期没人发现）；这一轮的教训是"**堆量**最危险"。
#    两者同属一类——**用户一眼看出不对劲，代码却默默通过**。
#    所以它们都该被钉成断言，而不是等用户来报。
#
# 判据（跟引擎里的口径对齐，改引擎时这条会一起响）：
#   · 便宜货（单价 ≤ CHEAP_ITEM_PRICE）→ 单款 ≤ CHEAP_ITEM_CAP
#   · 其他                            → 单款 ≤ 8（绝对封顶）
from savings_engine import CHEAP_ITEM_PRICE, CHEAP_ITEM_CAP  # noqa: E402

SKU_HARD_CAP = 8
sweep_budgets = [300, 500, 800, 1000, 1200, 2000]
for code, meals, promos in stores:
    for diners, n in (("adult", 0), ("kids", 1), ("kids", 2), ("mixed", 2)):
        for b in sweep_budgets:
            total += 1
            pl = plan_cheapest(meals, promos, b, diners=diners, kids=n)
            if pl is None:
                continue
            for it in pl["items"]:
                m = meals.get(it["code"])
                if not m:
                    continue
                price = m["original_price"] or m["current_price"]
                cap = CHEAP_ITEM_CAP if price <= CHEAP_ITEM_PRICE else SKU_HARD_CAP
                if it["count"] > cap:
                    fails.append(
                        f"[{code}] {diners} {n}娃 ¥{b} "
                        f"「{m['name']}」×{it['count']} 超单款上限 {cap}"
                    )

# ⭐ 7) 用户点名（must_items）· 选择自由（2026-10-09 报）
#
# 起因：原话「如果某一个套餐我比较喜欢，我想要点N份，
#      这个没有选择自由」。
#
# ⚠️ 这条跟前一条（断言 6）是一对，钉的是**同一个变量的两个方向**：
#      断言 6：引擎自己凑单**不许**超上限（防算法瞎堆 13 份）
#      断言 7：用户明确指定**必须**超上限也照点（防算法绑住用户的手）
#    只做 6 不做 7，就会像上一版那样——修好了算法的病，落下了用户的自由。
#
# 判据：
#   · 用户点名 N 份 → 结果里必须原样 N 份（哪怕 N 远超单款上限）
#   · 用户点名的亲子套餐 → 不被人头规则（kids_needed）砍
#   · 用户排除的款 → 结果里**不得出现**
for code, meals, promos in stores:
    for diners, n in (("adult", 0), ("kids", 1)):
        for b in (500, 1200):
            # 挑一款"便宜货"——正是会被单款上限压到 2 份的那一类
            cheap = sorted(
                [m for m in meals.values()
                 if m.get("kind") in ("main", "side")
                 and 0 < (m["original_price"] or m["current_price"]) <= CHEAP_ITEM_PRICE],
                key=lambda m: m["original_price"] or m["current_price"],
            )
            if not cheap:
                continue
            target = cheap[0]
            want = 5
            total += 1
            pl = plan_cheapest(meals, promos, b, diners=diners, kids=n,
                               must_items=[{"code": target["code"], "count": want}])
            if pl is None:
                fails.append(f"[{code}] {diners} ¥{b} 点名「{target['name']}」×{want} 却无方案")
            else:
                got = next((i["count"] for i in pl["items"]
                            if i["code"] == target["code"]), 0)
                if got != want:
                    fails.append(
                        f"[{code}] {diners} ¥{b} 点名「{target['name']}」要 {want} 份"
                        f"却只给 {got} 份 —— 用户的手被上限绑住了"
                    )

    # 排除：用户说不要的款，结果里不许出现
    for b in (500, 1200):
        total += 1
        # 挑一款平时必被引擎选中的贵货（排除它最考验）
        dearest = sorted(
            [m for m in meals.values() if m.get("kind") == "main"],
            key=lambda m: -(m["original_price"] or m["current_price"]),
        )[:1]
        if not dearest:
            continue
        ban = dearest[0]
        pl = plan_cheapest(meals, promos, b, exclude_items=[ban["code"]])
        if pl and any(i["code"] == ban["code"] for i in pl["items"]):
            fails.append(f"[{code}] ¥{b} 排除「{ban['name']}」却还是出现了")

# ⭐ 8) 方案里不得有重复 code（bug 10 · 2026-10-09 报）
#
# 起因：原话「300元档，默认的是三款，最后一款默认的是N=2，
#      点'全部恢复'也是这样」——其实那是**同一款出现了两条**，
#      界面上渲染成两张一模一样的卡，看着像三款、实际只有两款。
#
# ⚠️ 注意这是一条"**数据不变式**"，不是某个场景的期望值：
#    凑单流程里有好几处「换一件」，只要有一处忘了合并同款就会出现重复。
#    所以要在**所有**方案上扫，而不是抽查几个 case ——
#    这条断言的价值就在于"全覆盖"，漏一个角落就等于没做。
for code, meals, promos in stores:
    for diners, n in (("adult", 0), ("kids", 1), ("kids", 2), ("mixed", 2)):
        for b in (300, 500, 800, 1000, 1200, 2000):
            total += 1
            pl = plan_cheapest(meals, promos, b, diners=diners, kids=n)
            if pl is None:
                continue
            codes = [i["code"] for i in pl["items"]]
            if len(codes) != len(set(codes)):
                dup = [c for c in set(codes) if codes.count(c) > 1]
                names = [meals[c]["name"] for c in dup if c in meals]
                fails.append(
                    f"[{code}] {diners} {n}娃 ¥{b} 方案里同一款出现多次：{names}"
                )

print(f"Python 侧：总案 {total} · 失败 {len(fails)} · 提醒 {len(warns)}")
for f in fails[:20]:
    print("  ✗", f)
for w in warns[:10]:
    print("  ⚠", w)
sys.exit(1 if fails else 0)
