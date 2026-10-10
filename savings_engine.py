# -*- coding: utf-8 -*-
"""
savings_engine.py — 省钱引擎

输入：门店 + 想吃的餐品 + 数量
输出：怎么点最省（叠加可领券、门店促销规则、算实付、算省了多少）

设计原则（关键）：
  不依赖用户账号里已有的券。
  只用到「人人可领的券」+「门店公开促销规则」+「价格试算」，
  这样任何人跑都能出结果，演示不会是空壳。
"""


def yen(v):
    """把金额统一成两位小数的数字。"""
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


class SavingsResult:
    """一次算账的完整结果。"""

    def __init__(self):
        self.original_total = 0.0      # 原价合计
        self.final_total = 0.0         # 实付合计
        self.saved = 0.0               # 省了多少
        self.items = []                # 逐项明细
        self.coupons_used = []         # 用上的券
        self.promotions_used = []      # 用上的促销规则
        self.notes = []                # 给用户的说明

    def as_dict(self):
        return {
            "original_total": self.original_total,
            "final_total": self.final_total,
            "saved": self.saved,
            "items": self.items,
            "coupons_used": self.coupons_used,
            "promotions_used": self.promotions_used,
            "notes": self.notes,
        }


# ---------- 餐品分类 ----------
#
# 麦当劳 query-meals 的返回里带官方 categories（15 个），
# 分类名是「鸡肉汉堡/卷」「小食甜品/其他」「饮品」这种。
# 用它来区分"主食"和"配菜"，比按菜名猜关键词靠谱得多。

# 算主餐的分类（能当"这一顿"的）
MAIN_CATEGORIES = [
    "人气热卖", "精选单人餐", "鸡肉汉堡", "巨无霸", "牛鱼肉堡",
    "安格斯", "炸鸡", "小食拼盘", "多人餐", "蘸酱炸鸡", "随心配",
    "大堡口福", "开心乐园", "500大卡", "麦咖啡",
]

# 只能算配菜/加料的分类（凑单不靠它撑数）
SIDE_CATEGORIES = ["小食甜品", "饮品"]

# 儿童餐分类（麦当劳官方的「开心乐园」）
# 为什么单拎出来：纯大人局点儿童餐很怪——那是给小孩的，还带玩具。
KIDS_CATEGORY = "开心乐园"

# 「开心乐园」分类里，名字带这些的才是"真·儿童套餐"——
# 有吃的、有玩具，小孩能顶一顿。
# 反例：「如意百宝袋」也在开心乐园分类下，但那是个袋子/周边，不是餐。
KIDS_MEAL_KEYWORDS = ["乐园餐", "开心乐园餐", "儿童餐"]

# ⭐ 官方「亲子套餐」——一个套餐里含"大人主餐 + 带玩具的儿童餐"，
#    官方定位就是「1 大 1 小」（中国内地归在金拱门桶类）。
#    例：「开心亲子双人餐」（¥59.5）＝ 麦辣鸡腿堡×1
#        + 麦乐鸡开心乐园餐(含玩具)×1 + 薯条 + 可乐。
#    为什么单列一类：它跟"给一个孩子吃的单人乐园餐"不是一回事，
#    它是**成套卖给家庭**的，亲子场景应该优先推它。
FAMILY_MEAL_KEYWORDS = ["亲子双人餐", "亲子餐", "亲子欢乐", "大朋友小朋友"]

# 明显不是吃的东西（周边）
NON_FOOD_KEYWORDS = ["按摩捶", "棒球帽", "玩具", "公仔", "联名", "周边", "袋子", "杯子"]

# ⭐ 「成套/分享」类主餐的关键词——双人餐、多人餐、分享餐、桶、四宫格…
#    为什么单拎出来：这是「亲子餐」和「成人+亲子」两条路的分野——
#      亲子餐 = 成套/分享为主（一家人吃，摆一桌）
#      成人+亲子 = 单品自由（大人可以自己挑一个汉堡）
SHARE_KEYWORDS = ["双人", "多人", "分享", "四宫格", "家庭", "桶", "任选", "拼盘"]


def is_share_style(name):
    """这道主餐是不是"成套/分享"型（双人餐、多人餐、拼盘…）。"""
    return any(kw in name for kw in SHARE_KEYWORDS)


def classify(name, cat_name=""):
    """判一道餐品属于哪一类。

    返回 "main" / "side" / "kids" / "family" / "other"
      kids   = 给一个孩子吃的儿童套餐（含玩具）
      family = 大人+小孩的成套亲子套餐（官方「亲子双人餐」这类）
    """
    for kw in NON_FOOD_KEYWORDS:
        if kw in name:
            return "other"

    cat = (cat_name or "").replace("\n", "").replace(" ", "")
    if not cat:
        return "other"

    # 儿童餐优先认（官方的「开心乐园」分类）
    if KIDS_CATEGORY in cat:
        # 「开心乐园」分类里既有真儿童餐，也有周边袋子。
        # 只有名字像"餐"的才算 kids；纯袋子归 other。
        #
        # ⚠️ 先判 family：亲子双人餐名字里也有"双人餐"这种字眼，
        #    必须排在 kids 前面，否则会被当成单人儿童餐。
        if any(kw in name for kw in FAMILY_MEAL_KEYWORDS):
            return "family"        # 大人+小孩的成套亲子餐
        if any(kw in name for kw in KIDS_MEAL_KEYWORDS):
            return "kids"
        return "other"             # 开心乐园里的周边（如意百宝袋）

    # 其他分类里，名字带"亲子"的分享餐也算 family
    if any(kw in name for kw in FAMILY_MEAL_KEYWORDS):
        return "family"

    for kw in SIDE_CATEGORIES:
        if kw in cat:
            return "side"
    for kw in MAIN_CATEGORIES:
        if kw.replace(" ", "") in cat or kw in cat:
            return "main"
    return "other"


def parse_meals(raw):
    """把 query-meals 的返回解析成 {code: 餐品信息} 字典。

    同时把官方分类归属塞进每道餐品的 category / kind 字段。
    """
    data = raw.get("data", {}) if isinstance(raw, dict) else {}
    meals = data.get("meals", {}) or {}

    # 先建「餐品编码 -> 分类名」的索引
    cat_of = {}
    for cat in data.get("categories", []) or []:
        if not isinstance(cat, dict):
            continue
        cname = (cat.get("name") or "").replace("\n", "/")
        for item in cat.get("meals", []) or []:
            c = str(item.get("code", ""))
            if c and c not in cat_of:
                cat_of[c] = cname

    out = {}
    for code, m in meals.items():
        if not isinstance(m, dict):
            continue
        name = m.get("name", "")
        cname = cat_of.get(str(code), "")
        out[code] = {
            "code": code,
            "name": name,
            "current_price": yen(m.get("currentPrice")),
            "original_price": yen(m.get("originalPrice")),
            "discount_type": m.get("discountType"),
            "tags": m.get("tags", []),
            "img": m.get("image", ""),
            "category": cname,
            "kind": classify(name, cname),
        }
    return out


def parse_promotions(raw):
    """把 query-promotions 的返回解析成促销规则列表。"""
    if not isinstance(raw, dict):
        return []
    rules = raw.get("data", []) or []
    out = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        detail = r.get("ruleDetail", {}) or {}
        reduce_info = (detail.get("orderReduce", {}) or {}).get("reduceInfo", []) or []
        discount = detail.get("orderDiscount", {}) or {}
        out.append({
            "id": r.get("promotionId"),
            "type": r.get("promotionType"),          # 31-满额减 33-订单折扣
            "start": r.get("startTime", ""),
            "end": r.get("endTime", ""),
            "reduce_steps": [
                {"threshold": yen(s.get("startDiscountPoint")),
                 "reduce": yen(s.get("reduceAmount"))}
                for s in reduce_info
            ],
            "discount": {
                "rate": discount.get("discount"),
                "threshold": yen(discount.get("startDiscountPoint")),
            } if discount else None,
        })
    return out


def best_fulfillment(order_total, promotions):
    """在多个促销规则里，找出对当前订单最划算的一档。

    实测：query-promotions 返回的规则形如
      orderDiscount: {"discount": "22", "startDiscountPoint": "300"}
      => 满 300 元，减 22%（即打 78 折）
      orderReduce.reduceInfo: [{"startDiscountPoint","reduceAmount"}]
      => 满额直接减固定金额
    """
    best = None

    for p in promotions:
        pid = p.get("id")

        # ---- 满减：选够得着的、减得最多的那一档 ----
        for step in p.get("reduce_steps", []):
            if order_total >= step["threshold"] and step["reduce"] > 0:
                if best is None or step["reduce"] > best["amount"]:
                    best = {
                        "promotion_id": pid,
                        "kind": "满减",
                        "threshold": step["threshold"],
                        "amount": round(step["reduce"], 2),
                        "desc": f"满 {step['threshold']:.0f} 减 {step['reduce']:.0f}",
                    }

        # ---- 满折：discount 是"减免百分比"，22 => 减 22% ----
        d = p.get("discount")
        if d and d.get("rate") and order_total >= d.get("threshold", 0):
            try:
                pct = float(d["rate"])
            except (TypeError, ValueError):
                continue
            if not (0 < pct < 100):
                continue
            cut = round(order_total * pct / 100.0, 2)
            # 折后价不能低于 0
            cut = min(cut, order_total)
            if best is None or cut > best["amount"]:
                best = {
                    "promotion_id": pid,
                    "kind": "满折",
                    "threshold": d.get("threshold", 0),
                    "rate": pct,
                    "amount": cut,
                    "desc": f"满 {d.get('threshold', 0):.0f} 减 {pct:.0f}%",
                }

    return best


def savings_hint(order_total, promotions, max_gap=1200):
    """给一句「怎么点更省」的建议。

    逻辑：看所有活动的门槛，找出比当前金额高、但"凑上去更划算"的那一档。
    返回一句人话；没有更好的档就返回 None。
    """
    tips = []

    for p in promotions:
        # 满折档
        d = p.get("discount")
        if d and d.get("rate"):
            try:
                pct = float(d["rate"])
            except (TypeError, ValueError):
                continue
            th = float(d.get("threshold", 0))
            if th > order_total and 0 < pct < 100:
                need = th - order_total
                gain = round(th * pct / 100.0, 2)
                if need <= max_gap:
                    # 评分：净赚 = 省的钱 - 多花的钱；越大越值得
                    net = gain - need
                    tips.append((net, need, gain, th, pct))

    if not tips:
        return None

    # 挑"净赚最多"的那档
    tips.sort(key=lambda x: -x[0])
    net, need, gain, th, pct = tips[0]
    if net <= 0:
        return f"当前金额离最近的活动门槛（¥{th:.0f}）还差 ¥{need:.2f}，凑单才划算。"
    return (
        f"再点 ¥{need:.2f}（凑到 ¥{th:.0f}）可省 ¥{gain:.2f}"
        f"（满 {th:.0f} 减 {pct:.0f}%），净赚 ¥{net:.2f}。"
    )


def _unit_price(m):
    return m["original_price"] or m["current_price"]


# ⭐ 单款份数上限：同一个 SKU，一单里最多点几份。
#
# 为什么必须有它（2026-10-09 报的 bug 9）：
#   "会出现某一款被默认点了 5 份。这搁谁能乐意啊。"
#   实测最离谱的是 ¥2000 亲子局 → 「BFF四宫格小食盘双人餐 ×13」，
#   还有「灰焰圆筒 ×3」「韩式烟熏芝士风味酱 ×5」这种配菜堆量。
#
# ⚠️ 关键认识：这不是"上限设小了"，而是**第二轮在无脑填满**。
#    旧版第二轮的 while 会逮住池子里最贵那款一路加到把 target 填满，
#    中途完全不问"这单品种够不够多"，于是同一款能堆到十几份。
#
# ⚠️ 第二层认识（改到第二轮才想明白）：
#    上限不能只跟"预算"走。**同样 5 份，含义完全不同**：
#      · 5 份汉堡  → 可以接受（团餐、一家人各一个）
#      · 5 包 ¥3 蘸酱 / 5 个 ¥5 圆筒 → 荒谬（谁点五包酱？）
#    所以上限还要看**这一款多少钱**——便宜货是"加料"，贵货才是"一份饭"。
#
# 三个维度定上限：
#   ① 件数上限（预算越大件数越多）—— 大单本来就该多铺品种
#   ② 单价高低（便宜货上限更紧）    —— 防止"五包酱"这种观感事故
#   ③ 绝对封顶                     —— 再大的单也不许一款吃掉整单
MAX_PER_SKU_RATIO = 1.0 / 3.0    # 单款最多占「件数上限」的三分之一
MAX_PER_SKU_MIN = 2              # 至少允许 2 份（一个人也可能来俩）
MAX_PER_SKU_CAP = 8              # 绝对封顶

# "加料/配角"类（蘸酱、圆筒、苹果片、单杯饮料、小份小食…）的上限。
# 为什么单独管：它们单价低、存在感弱，凑金额时最容易被拿来填零头，
# 一填就是好几份，观感最差（"我点了一单，里面五包蘸酱"）。
#
# ⚠️ 阈值只按"单价"划，不按 kind：¥14.5 的"心形薯饼5块"在分类上算
#    side、在主餐池里，但它本质就是一份小食 —— 点 4 份一样荒谬。
#    ¥15 这条线覆盖了蘸酱/圆筒/派/苹果片/薯饼/单杯饮料这一整类。
CHEAP_ITEM_PRICE = 15.0          # 单价 ≤ ¥15 视为"加料/配角"
CHEAP_ITEM_CAP = 2               # 配角最多 2 份


def max_per_sku(max_items, unit_price=None):
    """单款最多几份。

    参数：
      max_items   件数上限（定上限的量级）
      unit_price  这一款的单价（定上限的松紧）—— None 时按"贵货"算

    例：max_items=24, 一款 ¥66 汉堡  → 6 份
        max_items=24, 一款 ¥3 蘸酱   → 2 份
    """
    import math
    cap = max(MAX_PER_SKU_MIN,
              min(MAX_PER_SKU_CAP, int(math.ceil(max_items * MAX_PER_SKU_RATIO))))
    # 便宜货收紧（"加料"不该出现 3 份以上）
    if unit_price is not None and unit_price <= CHEAP_ITEM_PRICE:
        cap = min(cap, CHEAP_ITEM_CAP)
    return cap


def _sku_cap_for(picked, candidates, max_items, per_sku_cap, code):
    """某一款此刻的上限：全局上限，若该款是便宜货则取更紧的那个。"""
    if per_sku_cap is not None:
        base = per_sku_cap
    else:
        base = max_per_sku(max_items)
    price = _unit_price_by_code(candidates, code)
    if price and price <= CHEAP_ITEM_PRICE:
        return min(base, CHEAP_ITEM_CAP)
    return base


def _fill_to_target(candidates, target, max_items, allow_repeat=True, variant=0,
                    per_sku_cap=None):
    """用一组候选餐品，凑到尽量接近 target（不超过）。

    这是修掉"一单几十个圆筒冰淇淋"那个坑的关键：
      - 尽量把品种铺开（每人吃到不一样的），而不是猛怼最贵那一个 SKU
      - 件数封顶，避免堆一堆 ¥5 的东西
      - **单款份数封顶**，避免同一款被堆十几份（bug 9）

    做法：
      1. 从贵到便宜，每个 SKU 先各来 1 份（铺品种）
      2. 还差得多（> 最贵的单品），再给主菜加份数——
         ⚠️ 但每一款都受 per_sku_cap 约束；到顶就换下一款，
         绝不死磕同一款（这正是 bug 9 的病根）
      3. 最后拿便宜的单品补零头（零头补丁不受份数限，因为它是"补差"）

    参数 per_sku_cap：
      单款份数上限。None → 按 max_items 自适应（见 max_per_sku()）。

    参数 variant（"再来一套"的开关）：
      同一组候选、同样的 target，**排序偏好不同**就会铺出不同的组合。
      variant=0 是原始口径（同价位里靠前的先上）；
      variant>0 时，把「价格相近的款」在排序里换一批上来 ——
      结果依然凑到同样的金额、套同样的优惠，但**品种不一样**。
      用途：用户觉得"可选种类太少"，就给他几套等价的方案挑。
      不是随机数（那会不可复现），而是**按 variant 做确定性轮转**。

    返回 (picked, total)，picked 是 [{"code","count"}]
    """
    if per_sku_cap is None:
        per_sku_cap = max_per_sku(max_items)
    pool = sorted(candidates, key=_unit_price, reverse=True)

    # 按 variant 把「价格相同/相近的相邻款」轮转一下顺序。
    # 只动**同价位段内**的先后，不动整体"从贵到便宜"的骨架，
    # 所以凑出来的金额不变，变的只是"这个价位段里用哪一款"。
    if variant:
        groups, cur, last = [], [], None
        for m in pool:
            p = _unit_price(m)
            if last is not None and abs(p - last) > 1e-9:
                groups.append(cur)
                cur = []
            cur.append(m)
            last = p
        if cur:
            groups.append(cur)
        pool = []
        for i, g in enumerate(groups):
            if len(g) > 1:
                k = (variant * (i + 1)) % len(g)      # 确定性轮转
                g = g[k:] + g[:k]
            pool.extend(g)

    picked = []
    total = 0.0
    count = 0

    def _count_of(code):
        for p in picked:
            if p["code"] == code:
                return p["count"]
        return 0

    def add(m, k=1):
        nonlocal total, count
        for p in picked:
            if p["code"] == m["code"]:
                p["count"] += k
                break
        else:
            picked.append({"code": m["code"], "count": k})
        total = round(total + _unit_price(m) * k, 2)
        count += k

    # ---- 第一轮：铺品种，每个 SKU 各来 1 份（从贵到便宜）----
    for m in pool:
        if count >= max_items:
            break
        price = _unit_price(m)
        if price <= 0 or price > target - total:
            continue
        add(m, 1)

    # ---- 第二轮：还差得远，就给主菜加份数 ----
    #
    # ⚠️ bug 9 的病根就在这一轮：旧版是 `while ...: add(m,1)` ——
    #    逮住池子里最贵那款，一路加到把 target 填满为止。
    #    池子窄的时候（kids 分享池只有 5 款）后果极难看：
    #    ¥2000 亲子局能堆出「BFF四宫格小食盘双人餐 ×13」。
    #
    #    修法：每款加份数时**先看它到没到上限**，到顶立刻换下一款。
    #    这样"凑够金额"的目标不变，但份数会被摊到多款上。
    if allow_repeat:
        for m in pool:
            if count >= max_items:
                break
            price = _unit_price(m)
            if price <= 0:
                continue
            cap = _sku_cap_for(picked, candidates, max_items, per_sku_cap, m["code"])
            while (count < max_items and total + price <= target
                   and _count_of(m["code"]) < cap):
                add(m, 1)

    # ---- 第三轮：补零头 ----
    #
    # ⚠️ 这一轮也受份数约束。旧版没有约束，于是配菜会被堆成
    #    「冰糖葫芦酸奶风味派 ×6」「【美汁源】黄金橙橙 ×8」。
    #    零头往往只差几块钱，给到 2×cap 的余量足够，
    #    再多就说明"这单本来就不该凑到这么满"。
    #
    # ⚠️ 实测修正（2026-10-09）：这里一度给到 per_sku_cap*2，
    #    结果 ¥3 蘸酱照样堆到 5 份（cap=8 → 16 的上限形同虚设）。
    #    结论：**上限就是上限**，不分轮次。要凑金额就换别的款，
    #    凑不出来就说明这单不该凑这么满 —— 那是更诚实的答案。
    if count < max_items:
        for m in sorted(candidates, key=_unit_price):
            price = _unit_price(m)
            if price <= 0:
                continue
            cap = _sku_cap_for(picked, candidates, max_items, per_sku_cap, m["code"])
            while (count < max_items and total + price <= target
                   and _count_of_code(picked, m["code"]) < cap):
                add(m, 1)

    # ---- 第四轮：还差零头，且单件补不上 → 拿"最便宜的两件组合"再试 ----
    # 为什么需要：可能差 ¥0.4 这种单件补不上的零头（所有单品都比缺口贵），
    # 但"拿掉一件 + 换两件更便宜的"正好能落进 target。
    # 不做全量搜索（组合爆炸），只做「替掉最后加的那件小的」这一种局部调整。
    #
    # ⚠️ bug 9 的最后一层（2026-10-09）：
    #    这一轮也**会堆量**——补零头时"两件组合"里塞的是同一款最便宜的
    #    （¥3 蘸酱、¥5 圆筒），于是凑出「韩式烟熏芝士风味酱 ×5」。
    #    用户看到的是"我点了一单，里面五包蘸酱"——照样要骂。
    #    所以：组合里的每一件也要过 per_sku_cap。
    if count < max_items and target - total > 0:
        # 这一轮是"拿掉一件换进两件"，件数净增 1；先确认还有位置
        gap = round(target - total, 2)
        # 从最便宜的开始，试着"换掉一件、换进两件"，看能不能更接近 target
        for old in sorted(picked, key=lambda p: _unit_price_by_code(candidates, p["code"])):
            old_price = _unit_price_by_code(candidates, old["code"])
            rest = round(total - old_price, 2)
            # 组合两件小事去填（含同一件买两份）
            #
            # ⚠️ 注意此处件数账：拿掉 old（-old["count"]）再加两件，
            #    所以组合里每件的"可用余量"要按**去掉 old 之后**的份数算。
            light = [dict(p) for p in picked if p["code"] != old["code"]]
            cheap = sorted(candidates, key=_unit_price)
            hit = None
            for i, a in enumerate(cheap):
                pa = _unit_price(a)
                if pa <= 0:
                    continue
                cap_a = _sku_cap_for(light, candidates, max_items, per_sku_cap,
                                     a["code"])
                if _count_of_code(light, a["code"]) >= cap_a:
                    continue
                for b in cheap:
                    pb = _unit_price(b)
                    if pb <= 0:
                        continue
                    cap_b = _sku_cap_for(light, candidates, max_items, per_sku_cap,
                                         b["code"])
                    # b 若是与 a 同款，要算上 a 已经占的名额
                    extra_b = 1 if a["code"] == b["code"] else 0
                    if _count_of_code(light, b["code"]) + extra_b >= cap_b:
                        continue
                    nt = round(rest + pa + pb, 2)
                    if nt > target:
                        continue
                    # 只要比现在更接近 target 就收
                    if target - nt < target - total - 1e-9:
                        hit = (a, b, nt)
                        break
                if hit:
                    break
            if hit:
                a, b, nt = hit
                # 重写 picked
                picked = [dict(p) for p in picked if p["code"] != old["code"]]
                for mm in (a, b):
                    for p in picked:
                        if p["code"] == mm["code"]:
                            p["count"] += 1
                            break
                    else:
                        picked.append({"code": mm["code"], "count": 1})
                total = nt
                count = sum(p["count"] for p in picked)
                if total >= target:
                    break

    return picked, total


def _top_up_to(candidates, picked, total, count, floor, ceiling, max_items,
               exclude_codes=None, protect_codes=None, per_sku_cap=None):
    """在「不超过 ceiling」的前提下，把金额补到 floor 之上。

    为什么需要它：凑单最怕差一点点。
    比如门槛是 ¥300，结果凑到 ¥298 —— 券用不上，白凑。

    两级策略：
      A. 先试「再加一件」——找一件加进去后恰好跨过 floor 的
      B. 加不进去（找不着合适小件）→ 试「换一件」——
         从已选里拿掉一件，换成一件更贵的，使总价跨过 floor

    参数 per_sku_cap：
      单款份数上限（同 bug 9）。策略 A「再加一件」时也受限，
      免得为了跨线把某一款堆上去；到顶就换别的款试。
      None → 从 max_items 自适应。

    参数 protect_codes：
      不能被动到的餐品编码（比如已经按人数备好的儿童餐）。
      策略 B「换一件」时跳过它们 —— 儿童玩具不能靠凑单凑没了。

    返回 (picked, total, count)
    """
    if total >= floor:
        return picked, total, count

    if per_sku_cap is None:
        per_sku_cap = max_per_sku(max_items)

    exclude = set(exclude_codes or [])
    protect = set(protect_codes or [])
    pool = sorted(candidates, key=_unit_price)

    def recount(pl):
        return round(sum(_unit_price_by_code(candidates, p["code"]) * p["count"]
                         for p in pl), 2), sum(p["count"] for p in pl)

    def _count_of(pl, code):
        for p in pl:
            if p["code"] == code:
                return p["count"]
        return 0

    # ---------- 策略 A：直接加一件跨线 ----------
    guard = 0
    while total < floor and count < max_items and guard < 40:
        guard += 1
        best = None
        for m in pool:
            price = _unit_price(m)
            if price <= 0 or total + price > ceiling:
                continue
            # ⚠️ 到顶的款不许再加（否则又变成"堆同一款跨线"）
            cap = _sku_cap_for(picked, candidates, max_items, per_sku_cap, m["code"])
            if _count_of(picked, m["code"]) >= cap:
                continue
            new_total = round(total + price, 2)
            if new_total >= floor and (best is None or price < best[1]):
                best = (m, price)
        if best is None:
            break
        # 加上去
        hit = next((p for p in picked if p["code"] == best[0]["code"]), None)
        if hit:
            hit["count"] += 1
        else:
            picked.append({"code": best[0]["code"], "count": 1})
        total = round(total + best[1], 2)
        count += 1
    if total >= floor:
        return picked, total, count

    # ---------- 策略 B：加一件 / 换一件 ----------
    # ⚠️ 旧版只试「换成更贵的、且份数不少于原来」，凑零头时常常无解：
    #    单子里全是 ¥123 的大件，差 ¥2，唯一出路是"再加一件最便宜的小菜"，
    #    而旧版不允许 k < old["count"]，就找不到解 → 整单判"够不着门槛"。
    #    所以先试「加一件」（ceiling 内跨线），再试「换一件」。
    for m in pool:
        price = _unit_price(m)
        if price <= 0:
            continue
        # ⚠️ 加份数也要过单款上限，别为了跨线把同一款堆上去
        already = _count_of(picked, m["code"])
        cap = _sku_cap_for(picked, candidates, max_items, per_sku_cap, m["code"])
        room = cap - already
        if room <= 0:
            continue
        for k in range(1, min(max_items - count, room) + 1):
            new_total = round(total + price * k, 2)
            if new_total < floor or new_total > ceiling:
                continue
            new_picked = [dict(p) for p in picked]
            hit = next((p for p in new_picked if p["code"] == m["code"]), None)
            if hit:
                hit["count"] += k
            else:
                new_picked.append({"code": m["code"], "count": k})
            return new_picked, new_total, count + k

    for i, old in enumerate(list(picked)):
        if old["code"] in protect:
            continue          # 受保护的餐品（儿童餐）不许换掉
        old_price = _unit_price_by_code(candidates, old["code"])
        rest_total = round(total - old_price * old["count"], 2)
        rest_count = count - old["count"]
        # 在候选里找一件替换品，使 rest_total + new_price*k 跨过 floor
        for m in sorted(candidates, key=_unit_price):
            new_price = _unit_price(m)
            if new_price <= 0 or m["code"] == old["code"]:
                continue
            # ⚠️ 换进来的款也受单款上限约束（免得"换一件"变成"换进五件酱"）
            cap = _sku_cap_for(picked, candidates, max_items, per_sku_cap, m["code"])
            for k in range(1, min(max_items - rest_count, cap) + 1):
                new_total = round(rest_total + new_price * k, 2)
                if new_total < floor or new_total > ceiling:
                    continue
                # 换掉
                new_picked = [dict(p) for p in picked if p["code"] != old["code"]]
                # ⚠️ 换进来的款可能**已经在单子里了**（只是不是被换掉的 old 那条）。
                #    旧版直接 append，于是同一条 code 出现两次 ——
                #    界面上渲染成两张一模一样的卡，用户看到的是
                #    「同一款怎么出现两次」（2026-10-09 报的 bug 10）。
                _hit = next((p for p in new_picked if p["code"] == m["code"]), None)
                if _hit:
                    _hit["count"] += k
                else:
                    new_picked.append({"code": m["code"], "count": k})
                new_count = sum(p["count"] for p in new_picked)
                return new_picked, new_total, new_count

    # ---------- 策略 C：拿掉一件 + 换进 2~3 件（小组合搜索）----------
    # 为什么还需要这一级：缺口可能是 ¥0.5 这种**单件补不上**的零头
    # （所有单品都比缺口贵，随便加一件就超 ceiling），
    # 但"替掉一件、换进两三件小的"正好能落进 [floor, ceiling]。
    # 例：¥300 亲子餐（2 娃）凑到 ¥299.5 差 ¥0.5，任何单件都补不上；
    #     但把 ¥180.5 那对拆成 ¥115.5+¥54.5+¥11 就恰好 ¥300。
    _cheap = sorted(candidates, key=_unit_price)

    def _pairs_or_triples(need):
        """在候选里找 2~3 件，合计恰好 need（允许同款多份）。"""
        # 两件
        for a in _cheap:
            pa = _unit_price(a)
            if pa <= 0 or pa > need:
                continue
            for b in _cheap:
                pb = _unit_price(b)
                if pb <= 0:
                    continue
                if abs(pa + pb - need) < 1e-9:
                    return [(a, 1), (b, 1)]
        # 三件
        for a in _cheap:
            pa = _unit_price(a)
            if pa <= 0 or pa > need:
                continue
            for b in _cheap:
                pb = _unit_price(b)
                if pb <= 0 or pa + pb > need:
                    continue
                for c in _cheap:
                    pc = _unit_price(c)
                    if pc <= 0 or pc > need:
                        continue
                    if abs(pa + pb + pc - need) < 1e-9:
                        return [(a, 1), (b, 1), (c, 1)]
        return None

    for old in list(picked):
        if old["code"] in protect:
            continue
        old_price = _unit_price_by_code(candidates, old["code"])
        rest_total = round(total - old_price * old["count"], 2)
        rest_count = count - old["count"]
        # 拿掉 old 后，还需要的金额；必须是"换进的东西"的价格和
        # 试 old 的每一份：去掉 1 份，看看剩余 monies 是否能被 2~3 件补齐
        for drop in range(1, old["count"] + 1):
            rest_total_k = round(total - old_price * drop, 2)
            rest_count_k = count - drop
            need = round(floor - rest_total_k, 2)
            if need <= 0 or need > ceiling - rest_total_k:
                continue
            combo = _pairs_or_triples(need)
            if not combo:
                continue
            if rest_count_k + len(combo) > max_items:
                continue
            new_picked = [dict(p) for p in picked]
            if old["count"] - drop > 0:
                for p in new_picked:
                    if p["code"] == old["code"]:
                        p["count"] -= drop
            else:
                new_picked = [p for p in new_picked if p["code"] != old["code"]]
            for mm, kk in combo:
                hit = next((p for p in new_picked if p["code"] == mm["code"]), None)
                if hit:
                    hit["count"] += kk
                else:
                    new_picked.append({"code": mm["code"], "count": kk})
            new_total = round(rest_total_k + need, 2)
            new_count = sum(p["count"] for p in new_picked)
            return new_picked, new_total, new_count

    return picked, total, count


def _unit_price_by_code(candidates, code):
    for m in candidates:
        if m["code"] == code:
            return _unit_price(m)
    return 0.0


def _count_of_code(picked, code):
    """picked 里某个 code 已经点了几份（没有就是 0）。"""
    for p in picked:
        if p["code"] == code:
            return p["count"]
    return 0


def merge_same_code(items):
    """同一款出现多条 → 合并成一条（份数相加）。

    ⚠️ 为什么必须有这个兜底（2026-10-09 · bug 10）：
       凑单流程里有好几处「换一件」，换进来的款**可能已经在单子里了**。
       只要有一处忘了合并，同一条 code 就会出现两次 ——
       界面上渲染成两张一模一样的卡，用户看到的是
       「同一款怎么出现两次？」，而且件数统计也跟着错。

       ——这类"数据不变式"的破坏，不该靠"每一处都记得写对"来保证。
       出口处合并一次，是**不管上游哪一步漏了都能兜住**的底线。

       原话：「默认的是三款，最后一款默认的是N=2……直到我把
       最后默认显示为数量2的减成1，才出现四款」——
       她看到的就是这个：两张卡其实是同一款。
    """
    out = []
    idx = {}
    for it in items:
        code = it["code"]
        if code in idx:
            out[idx[code]]["count"] += it["count"]
        else:
            idx[code] = len(out)
            out.append({"code": code, "count": it["count"]})
    return out


def diversify_plan(items, meals_map, protect_codes=None):
    """把"同款多份"拆成"同价位的不同款" —— **金额一分不变，品种更多**。

    ⚠️ 为什么需要它（bug 10 的另一半 · 2026-10-09 报）：
      原话「300元档，默认的是三款」——其实只看到**两种**东西，
      其中一款堆了 3 份（鱼牛汉堡四件套随心选 ×3）。
      算法把金额凑够了，却没把品种铺开：
      ¥59 这一档明明有 5 款可选（鱼牛 / 巨无霸 / 不素之霸 /
      培根蔬萃 / 双层深海鳕鱼），凭什么只给一款？

      这正是上一轮"铺品种"那个目标没做到的地方——
      修了"堆 13 份"的极端情况，却漏了"堆 3 份"的常见情况。

    做法：只做「**同价位互换**」——
      找**价格完全相同**、**同 kind**、**还没在单子里**的款，
      把多余份数分配过去。价格一样 → **总价一分不变**，
      优惠档位绝不会掉（不像"换一换"那样得重新校验门槛）。

    不动的两类：
      · 用户点名的款（那是他的自由，算法不许自作主张改）
      · 儿童餐 / 亲子套餐（份数按人头锁死，玩具不能凑）
    """
    protect = set(protect_codes or [])
    out = [dict(it) for it in items]
    used = {it["code"] for it in out}

    for it in out:
        if it["count"] <= 1 or it["code"] in protect:
            continue
        base = meals_map.get(it["code"])
        if not base:
            continue
        base_kind = base.get("kind")
        if base_kind in ("kids", "family"):
            continue                       # 带玩具的按人头锁死
        base_price = _unit_price(base)
        if base_price <= 0:
            continue

        # 同价位、同品类、还没用过的替代款（保持菜单顺序，可复现）
        same = [
            m for m in meals_map.values()
            if m["code"] != it["code"]
            and m["code"] not in used
            and m.get("kind") == base_kind
            and abs(_unit_price(m) - base_price) < 1e-9
        ]
        if not same:
            continue
        # 原来的留 1 份，其余分给不同的款
        share = min(it["count"] - 1, len(same))
        for m in same[:share]:
            out.append({"code": m["code"], "count": 1})
            used.add(m["code"])
        it["count"] -= share

    return out


# ═══════════════════════════════════════════════════════════════
#  同档替换：让用户"有得选"
# ---------------------------------------------------------------
#  问题：_fill_to_target 是确定性的，从最贵往下铺、铺够就停，
#        所以同价位永远只出排最前那款 —— 用户感觉"可选种类太少"。
#
#  解决：**不动"最省"结论，只在它旁边加一层"可替换"。**
#        方案里每个位置，都能换成价格相近的另一款，
#        换完总价几乎不变、优惠门槛照样够。
# ═══════════════════════════════════════════════════════════════

# 替代款的价格宽容度：以该款原价为基准，上下各 20% 内算"同档"
ALT_TOLERANCE = 0.20

# 高价区款少，±20% 常常捞不到同款 → 再放宽一轮。
# ⚠️ 但不能无节制放：实测曾把 ¥103 的套餐推成 ¥59 的四件套，
#    差价 -44 元，那是"降级"不是"替换"，用户会觉得系统在糊弄他。
#    所以第二轮的差价有**双重上限**：既看百分比，也看绝对金额。
ALT_TOLERANCE_WIDE = 0.30      # 第二轮百分比上限
ALT_MAX_DIFF_ABS = 30.0        # 第二轮差价绝对上限（元）


def _alt_kind_ok(base_kind, cand_kind):
    """判断两款能不能互换（对用户来说"是不是同一类东西"）。

    先用严格同 kind；高价套餐区款少，允许 main 与 family 互认
    （BFF四宫格、全明星双人餐、亲子双人餐，对用户都是"一份大套餐"）。
    """
    if base_kind == cand_kind:
        return True
    big = {"main", "family"}
    if base_kind in big and cand_kind in big:
        return True
    return False


def alternatives_for(meals_map, plan, tolerance=ALT_TOLERANCE, max_alt=6,
                     diners="adult"):
    """给方案里每个位置，找出"价格相近、可替换"的其它款。

    参数：
      meals_map  全部餐品（parse_meals 的输出）
      plan       plan_cheapest 返回的方案
      tolerance  价格宽容度（0.2 = ±20%）
      max_alt    每个位置最多列几款替代（按价格接近程度排）
      diners     用餐人构成，决定哪些款能进候选（纯大人局不给儿童餐）

    返回：[{
        "code": 原款 code, "name": 原名, "count": 份数, "price": 原价,
        "alts": [{"code","name","price","diff","img"}, ...]
      }, ...]
      —— alts 里 **不含原款本身**；差价为「替代款 - 原款」（正=更贵）。

    两段搜索：
      1. 先在 ±20% 内找同 kind 的；
      2. 若不够，放宽到 ±45% 再找一轮（高价套餐区款少，只能这样）。
    每款 alt 带 `loose` 标记，前端可以标注"价格差得多"。
    """
    if not plan or not plan.get("items"):
        return []

    # 允许出现的池子（跟 plan_cheapest 的口径保持一致）
    def allowed(m):
        k = m.get("kind")
        if k == "other":
            return False
        if _unit_price(m) <= 0:
            return False
        if diners == "adult" and k in ("kids", "family"):
            return False
        return True

    pool = [m for m in meals_map.values() if allowed(m)]
    plan_codes = {p["code"] for p in plan["items"]}

    out = []
    for pos in plan["items"]:
        code = pos["code"]
        base = meals_map.get(code)
        if not base:
            continue
        base_price = _unit_price(base)
        if base_price <= 0:
            continue

        found = {}
        # ---- 第一轮：±20% 内、同品类 ----
        for m in pool:
            if m["code"] == code or m["code"] in plan_codes:
                continue
            if not _alt_kind_ok(base.get("kind"), m.get("kind")):
                continue
            p = _unit_price(m)
            if base_price * (1 - tolerance) <= p <= base_price * (1 + tolerance):
                found[m["code"]] = {
                    "code": m["code"], "name": m["name"], "price": p,
                    "diff": round(p - base_price, 2), "img": m.get("img", ""),
                    "category": m.get("category", ""), "loose": False,
                }

        # ---- 第二轮：还不够就放宽价格（仍同品类），但差价双重封顶 ----
        if len(found) < 3:
            for m in pool:
                if m["code"] == code or m["code"] in plan_codes:
                    continue
                if m["code"] in found:
                    continue
                if not _alt_kind_ok(base.get("kind"), m.get("kind")):
                    continue
                p = _unit_price(m)
                diff = p - base_price
                # 百分比与绝对金额**都要**在限内，避免"降级"被当"替换"
                if abs(diff) > ALT_MAX_DIFF_ABS:
                    continue
                if not (base_price * (1 - ALT_TOLERANCE_WIDE) <= p
                        <= base_price * (1 + ALT_TOLERANCE_WIDE)):
                    continue
                found[m["code"]] = {
                    "code": m["code"], "name": m["name"], "price": p,
                    "diff": round(diff, 2), "img": m.get("img", ""),
                    "category": m.get("category", ""), "loose": True,
                }

        cands = sorted(found.values(),
                       key=lambda x: (x["loose"], abs(x["diff"]), x["price"]))
        out.append({
            "code": code,
            "name": base["name"],
            "count": pos.get("count", 1),
            "price": base_price,
            "img": base.get("img", ""),
            "category": base.get("category", ""),
            "alts": cands[:max_alt],
            "alt_total": len(cands),
        })
    return out


def apply_swap(meals_map, promotions, plan, from_code, to_code,
               budget=None, max_items=None):
    """把方案里的某一款换成另一款，并重新校验优惠是否还成立。

    这是「换一换」真正落地的地方 —— 换完要回答两个问题：
      1. 总价还够不够原来的门槛？（不够就掉档，省的钱会变少）
      2. 有没有超预算？

    返回 {ok, plan, delta, note}
      delta > 0 表示更贵（多花钱），< 0 表示更便宜
    """
    if not plan:
        return {"ok": False, "note": "没有可换的方案。"}

    old = meals_map.get(from_code)
    new = meals_map.get(to_code)
    if not old or not new:
        return {"ok": False, "note": "要换的餐品不存在。"}

    old_price = _unit_price(old)
    new_price = _unit_price(new)
    delta = round(new_price - old_price, 2)

    # 重建 items
    items = []
    hit = False
    for it in plan["items"]:
        if it["code"] == from_code:
            items.append({"code": to_code, "count": it.get("count", 1)})
            hit = True
        else:
            items.append(dict(it))
    if not hit:
        return {"ok": False, "note": "方案里没有这一款，换不了。"}

    original_total = round(plan["original_total"] + delta, 2)

    # 超预算？
    if budget and original_total > budget + 1e-9:
        return {
            "ok": False,
            "note": f"换完会到 ¥{original_total:.2f}，超预算 ¥{budget} 了。",
        }

    # 重新挑促销档：门槛够不着就自动降档（省的钱会少），而不是假装没变
    rate = plan.get("rate", 0) or 0
    threshold = plan.get("threshold", 0) or 0
    best = None
    for p in promotions or []:
        d = p.get("discount") or {}
        th = float(d.get("threshold", 0) or 0)
        pc = float(d.get("rate", 0) or 0)
        if th <= original_total + 1e-9:
            cut = round(original_total * pc / 100.0, 2)
            if best is None or cut > best["cut"]:
                best = {"threshold": th, "rate": pc, "cut": cut}
    if best is None:
        return {
            "ok": False,
            "note": f"换完 ¥{original_total:.2f} 够不着任何活动门槛了，这单省不动。",
        }

    final_total = round(original_total - best["cut"], 2)
    new_plan = dict(plan)
    new_plan.update({
        "items": items,
        "original_total": original_total,
        "threshold": best["threshold"],
        "rate": best["rate"],
        "final_total": final_total,
        "saved": best["cut"],
    })

    note = ""
    if best["threshold"] < threshold:
        note = (f"换成「{new['name']}」后总价变了，"
                f"活动降档到满 {best['threshold']:.0f} 减 {best['rate']:.0f}%，"
                f"省额会跟着变。")
    elif delta > 0:
        note = f"换成「{new['name']}」多花 ¥{delta:.2f}，优惠档不变。"
    elif delta < 0:
        note = f"换成「{new['name']}」少花 ¥{-delta:.2f}，优惠档不变。"
    else:
        note = f"换成「{new['name']}」，总价一分不差。"

    return {"ok": True, "plan": new_plan, "delta": delta, "note": note}


def plan_cheapest(meals_map, promotions, budget, max_items=None,
                  diners="adult", kids=0, kid_picks=None, variant=0,
                  must_items=None, exclude_items=None):
    """给定预算，算「怎么点最省」。

    做法：
      1. 找出所有够得着的门槛（预算 >= 门槛）
      2. 对每个门槛，用「主餐优先 + 件数封顶」的方式凑到门槛附近
      3. 比较各方案的实际省额，选出最省的

    参数 max_items：
      一单最多几件。默认按预算自适应（约 ¥50/件，上下限 8~40 件），
      避免出现"凑单凑出 30 个冰淇淋"这种现实里没人点的方案。

    参数 diners / kids（用餐人构成 · 人情世故不是数学）：
      diners = "adult"  仅成人   -> 儿童餐、亲子套餐【全排除】
      diners = "kids"   仅亲子   -> ⭐ 官方亲子套餐打底；大人侧**成套/分享**为主
      diners = "mixed"  成人+亲子 -> ⭐ 官方亲子套餐打底；大人侧**单品自由**
      kids   = 儿童人数，决定要几份带玩具的餐（儿童餐 + 亲子套餐合计）

    参数 kid_picks（每个娃想吃哪款儿童餐 · 该问的一句不能省）：
      长度为 kids 的列表，每项是儿童餐的 code，或 "any"（不挑 = 省着点）。
      例：["9900016057", "any"] 表示老大要汉堡乐园餐、老二不挑。
      为什么需要它：一家店有**三款**儿童餐（汉堡/鱼排堡/麦乐鸡），
      引擎若一律挑最便宜那款，另外两款永远不出现——娃想吃麦乐鸡就配不上。
      所以"挑哪款"这个决定**交给用户**，引擎只负责省钱：
        · 指定了款 → 就点那款（哪怕贵一点）；
        · "any"   → 引擎挑最便宜的（默认省）。

    为什么要有这个参数：
      纯大人局点「开心乐园餐」很怪——那是给小孩的，还带玩具。
      反过来，带孩子却漏了儿童餐，玩具不够分，孩子要闹。

    「亲子餐」和「成人+亲子」的区别：
      **两者都优先用官方亲子套餐**——那是商家设计的官方产品，
      带娃场景就该先用上，不然这个产品设计就成了摆设。
      分野在"大人那半边怎么点"：
        kids  = 一家人摆一桌，优先成套/分享餐（双人餐、多人餐、拼盘）
        mixed = 单品自由，大人想点啥点啥（单只汉堡也行）

    参数 variant（"再来一套"用）:
      同一个预算、同一堆候选，用不同的排序偏好再算一遍。
      **省钱结论完全一样**（同样凑到门槛、同样档位、同样省额），
      但**品种组合不同** —— 用户觉得"可选种类太少"时，给他几套挑。
      实现见 _fill_to_target 的 variant 说明（确定性轮转，非随机）。
      默认 0 = 原始口径。

    参数 must_items（"这个我要 N 份" · 用户的选择自由）：
      [{code, count}, ...] —— 用户点名的款与份数。
      2026-10-09 原话：「如果某一个套餐我比较喜欢，我想要点N份，
      这个没有选择自由。」

      ⭐ 关键区分（上一版修 bug 9 时踩出来的边界）：
        · **引擎自己凑单** → 受单款份数上限约束（防"算法瞎堆 13 份"）
        · **用户明确指定** → **不受任何上限约束**（那是用户自决，算法无权干涉）
      同一条上限，管的是前者，不是后者。别把用户的手也一起绑住。

      must 款的行为：
        · 份数按用户说的来（**覆盖**引擎原本的安排，不是叠加）
        · 不受单款上限、不受 kids_needed 名额、不被"换一件"换掉
        · 金额从预算里先扣，剩下的额度才交给引擎去凑
        · 超预算也照点（用户说了算），由调用方决定要不要提示

    参数 exclude_items（"这个我不要"）：
      [code, ...] —— 引擎凑单时**永不选**这些款。
      跟 must_items 是一对：一个"我就要"，一个"我不要"。

    返回 dict：{items, threshold, rate, original_total, final_total, saved, note}
    """
    if not meals_map or budget <= 0:
        return None

    # 只保留能吃的东西（排除周边）
    eatable = [
        m for m in meals_map.values()
        if _unit_price(m) > 0 and m.get("kind") != "other"
    ]
    if not eatable:
        return None

    # ── 用户点名的款（"这个我要 N 份"）与排除的款（"这个不要"）──
    #
    # ⭐ 这一路专门为"用户的选择自由"开（2026-10-09）。
    #    上一版为了修 bug 9 加了单款份数上限，防住了"算法瞎堆"，
    #    却顺手把**用户自己的手**也绑住了——
    #    "我想要点 3 份"会被上限拦下。那是把两件事混成一件事了。
    #
    #    分界：引擎的上限只管引擎自己；用户明确点名，算法无权干涉。
    must_spec = []
    for mi in (must_items or []):
        code = str(mi.get("code"))
        cnt = int(mi.get("count", 1) or 0)
        if cnt > 0 and code in meals_map:
            must_spec.append((code, cnt))
    must_codes = {c for c, _ in must_spec}
    excl_codes = {str(c) for c in (exclude_items or [])}

    def _inject_must(picked, total, count):
        """把用户点名的款按指定份数放进去（不受任何上限约束）。

        ⚠️ 是**覆盖**不是叠加：用户说"这个我要 3 份"，就是 3 份，
           不管引擎原本在这款上安排了几个（比如按人头种的儿童餐）。
        """
        for code, cnt in must_spec:
            hit = next((p for p in picked if p["code"] == code), None)
            if hit:
                hit["count"] = cnt
            else:
                picked.append({"code": code, "count": cnt})
        # 份数被用户改过 → 金额不可信，整单重算
        total = round(sum(_unit_price(meals_map[p["code"]]) * p["count"]
                          for p in picked), 2)
        count = sum(p["count"] for p in picked)
        return picked, total, count

    def _engine_pool(items):
        """引擎可以自由支配的池子：排掉「用户点名的」和「用户排除的」。

        ⚠️ 用户点名的款必须从池子里拿掉——不然引擎凑单时会在这款上
           **再加份数**，把用户说的"3 份"变成"4 份"。
           用户定了数，引擎就不该再动它。
        """
        return [m for m in items
                if m["code"] not in must_codes and m["code"] not in excl_codes]

    # 按用餐人构成筛选
    #
    # ⚠️ family（官方「亲子双人餐」这类）单列一池，不能混进 kids 或 main：
    #    - 混进 kids 会把它当成"一份儿童餐"，人数口径就错了；
    #    - 混进 main 会被当普通主餐随便加，亲子场景反而推不出官方套餐。
    kid_pool = [m for m in eatable if m.get("kind") == "kids"]
    family_pool = [m for m in eatable if m.get("kind") == "family"]
    adult_pool = [m for m in eatable
                  if m.get("kind") not in ("kids", "family")]

    if diners == "adult":
        # 纯大人：不碰儿童餐，也不碰亲子套餐（那是卖给带娃家庭的）
        allowed_kids = []
        allowed_family = []
        allowed_adult = adult_pool
    elif diners == "kids":
        # 纯亲子：官方產品形态——⭐ 优先用官方亲子套餐（1 大 1 小成套）
        allowed_kids = kid_pool
        allowed_family = family_pool
        allowed_adult = adult_pool
    else:  # mixed 成人+亲子：官方套餐【照样用】，额外保留散点自由
        #
        # ⭐ 商家设计了「开心亲子双人餐」这个官方产品，所有带娃场景都该优先用它，
        #    不然官方套餐就成了摆设、丢了它本来的产品功能。
        #    区别只在"允不允许散点补足"：
        #      kids  = 纯官方形态（官方套餐打底，不散点大人主餐）
        #      mixed = 官方套餐打底 + 剩下预算散点自由组合
        allowed_kids = kid_pool
        allowed_family = family_pool
        allowed_adult = adult_pool

    # 主餐（汉堡/套餐/炸鸡）与配菜（饮品/小食甜品）分开
    #
    # ⚠️ 注意 kids 也算"主食"——儿童餐是给小孩顶一顿的，
    #    不是配菜。早先只认 main/side，kids 两头都不沾，
    #    结果 kid_mains 恒为空，儿童餐永远种不进单子。
    def split(items):
        mains = [m for m in items if m.get("kind") in ("main", "kids")]
        sides = [m for m in items if m.get("kind") == "side"]
        return mains, sides

    adult_mains, adult_sides = split(allowed_adult)
    kid_mains, kid_sides = split(allowed_kids)
    family_mains = list(allowed_family)      # 亲子套餐本身就是"一顿"，算主餐

    # 主餐填充池
    #
    # ⚠️「可用」≠「随便加」——儿童餐的份数由「几名儿童」**锁定**，
    #    多一份就是多花一份钱 + 多一个重复玩具。
    #    所以儿童餐只由 _seed_kids() 按人数精确投放，
    #    凑单的填充池 mains【一律不含】单份儿童餐（那是按人头锁死的）。
    #
    # ⭐ 两条带娃路的分野（都优先官方套餐，区别在"大人那半边怎么点"）：
    #    - 亲子餐（kids）：一家人吃，**成套/分享为主** ——
    #      大人侧优先用双人餐/多人餐/分享餐，不散点单只汉堡。
    #      官方亲子套餐是骨架，撑不起预算时用分享餐补。
    #    - 成人+亲子（mixed）：**单品自由** ——
    #      大人侧想点啥点啥（单只汉堡也行），官方套餐照样优先打底。
    #
    # ⚠️ bug 9 的第二层原因（2026-10-09）：
    #    分享池（双人餐/四宫格/拼盘…）**只有 5~6 款**，
    #    而 ¥1000 门槛要 9 件、¥2000 门槛要 16 件才凑得满。
    #    款数不够 → 算法只能逮着最贵那款猛堆 → 「BFF四宫格双人餐 ×13」。
    #
    #    ⚠️ 试过一版"把整个大人主餐池接进来兜底"，结果**踩了回归**：
    #       池子一放宽，kids 与 mixed 两条路算出**完全一样**的方案
    #       （回归里 11 条"亲子餐与成人+亲子结果相同"），
    #       等于把"成套为主 vs 单品自由"这个产品区分给抹了。
    #       ⇒ 池子不能动。**修堆量只该修份数上限，不该改变"能点什么"。**
    #
    #    所以这里保持原口径：分享款优先；分享款确实不够时，
    #    由单款份数上限（max_per_sku）来管住"堆同一款"，
    #    而不是靠"多给几款"来稀释——那是治错了地方。
    if diners == "kids":
        share_mains = [m for m in adult_mains if is_share_style(m["name"])]
        mains = share_mains or adult_mains          # 没分享餐就退回全部
    else:
        mains = adult_mains

    if not mains:
        mains = adult_mains or kid_mains or eatable

    sides = adult_sides + kid_sides

    # 要凑几份儿童餐（每名儿童一份带玩具的）
    kids_needed = 0
    if diners in ("kids", "mixed") and kids > 0:
        kids_needed = kids
    elif diners == "kids" and kids == 0:
        kids_needed = 1  # 说"亲子"至少一个娃

    # ⭐ 亲子套餐要几份（按"1 大 1 小"组合数）
    #    官方「开心亲子双人餐」一份就含 1 份大人主餐 + 1 份带玩具的儿童餐，
    #    所以 n 个孩子最多配 n 份亲子套餐（1:1），剩下的散件补。
    #    ⚠️ 两个带娃模式都用（商家设计要落地）；纯大人局不用。
    #
    #    ⚠️ 但用户逐娃指定了儿童餐口味时，官方套餐就不合适了——
    #       官方套餐里的儿童餐款固定，满足不了"老二想吃麦乐鸡"。
    #       所以：**只要有人指定了口味 → 跳过官方套餐，按人配单款儿童餐**。
    kid_picks_padded = list(kid_picks) if kid_picks else []
    # 补齐到 kids_needed 长度（没填的当 "any"）
    while len(kid_picks_padded) < kids_needed:
        kid_picks_padded.append("any")
    has_specific_pick = any(p and p != "any" for p in kid_picks_padded)

    family_needed = 0
    if (diners in ("kids", "mixed") and family_pool and kids_needed > 0
            and not has_specific_pick):
        family_needed = kids_needed

    # 兜底闸门：任何人任何路径，都不许让"儿童餐 + 亲子套餐"总数超过 kids_needed；
    # 纯大人局则一律剔除儿童餐和亲子套餐。
    #
    # ⚠️ 亲子套餐要按"份数"占一个孩子名额（一份套餐只带一个玩具），
    #    不然会出现"2 个娃点了 3 份套餐"——玩具多了，钱也多了。
    kid_codes = {m["code"] for m in kid_mains}
    family_codes = {m["code"] for m in family_mains}

    def clamp_kids(picked):
        # ⚠️ 用户点名的款：原样保留，且**不占** kids_needed 名额。
        #    用户既然明确说了"要几份"，这款就完全归他管，
        #    引擎的人头规则不再对它生效——
        #    否则"我要 3 份亲子套餐"会被砍回 1 份，又变成没有选择自由。
        if diners == "adult":
            return [dict(p) for p in picked
                    if (p["code"] not in kid_codes and p["code"] not in family_codes)
                    or p["code"] in must_codes]
        used = 0
        out = []
        for p in picked:
            if p["code"] in must_codes:
                out.append(dict(p))
                continue
            is_kid_like = p["code"] in kid_codes or p["code"] in family_codes
            if not is_kid_like:
                out.append(dict(p))
                continue
            room = kids_needed - used
            if room <= 0:
                continue                      # 超标 → 整条剔掉
            q = min(p["count"], room)
            out.append({"code": p["code"], "count": q})
            used += q
        return out

    # 件数上限
    #
    # ⚠️ 旧口径 `min(40, budget/50)` 是"按钱估件数"，会失控：
    #    ¥2000 → 40 件，可这单可能只有 2 个人（1 大 1 小）。
    #    40 件里塞 8 份同样的分享餐 —— 这就是 bug 9 最难看的那批。
    #
    # 新口径：**先看人数，再看预算**。
    #   一件东西 ≈ 一个人一顿的量，所以：
    #     基准件数 = (大人数 + 小孩数) × 每人件数
    #   预算只用来**放宽**（大单可以多铺点品种），但有硬上限。
    #
    # ⚠️ 人数从哪来：
    #   adult   → 没给人数，按 2 人估（最常见的"两个人吃"）
    #   kids    → 至少 1 大 1 小；再加 kids 个孩子
    #   mixed   → 同 kids
    #   宁松勿紧：宁可让用户自己调，也别把方案憋死。
    if max_items is None:
        if diners == "adult":
            heads = 2
        else:
            heads = 1 + max(1, kids)      # 1 个大人 + 孩子们
        base = heads * 3                  # 每人 3 件（主餐+配菜+饮料）
        # 预算只做温和放宽：每多 ¥200 多给 2 件，最多 3 倍
        bonus = int(budget / 200) * 2
        max_items = max(8, min(base * 3, base + bonus))

    # 收集所有满折门槛
    thresholds = set()
    for p in promotions:
        d = p.get("discount")
        if d and d.get("rate") and float(d.get("threshold", 0)) <= budget:
            thresholds.add((float(d["threshold"]), float(d["rate"])))
    if not thresholds:
        return None

    # ------------------------------------------------------------
    # 关键：预算是「上限」，不是「门槛」
    #
    # 旧写法只挑 threshold <= budget 的档，然后把金额凑到那个门槛上，
    # 于是填 400 会按 300 算、填 777 会按 500 算 —— 用户填的数字白填。
    #
    # 新写法：预算是「这一顿最多花多少」。
    #   1. 尽量把金额花到接近预算（但不超）
    #   2. 在这个金额下，看能套上哪一档活动
    #   3. 每一档门槛都要「凑够」，别差一点点够不着
    # ------------------------------------------------------------
    sorted_tiers = sorted(thresholds)

    def best_promo_for(amount):
        pick = None
        for th, pct in sorted_tiers:
            if th > amount:
                continue
            cut = round(amount * pct / 100.0, 2)
            if pick is None or cut > pick["cut"]:
                pick = {"threshold": th, "rate": pct, "cut": cut}
        return pick

    # 为「某一档门槛」造一单：必须凑够门槛，且不超预算
    def build_for_threshold(th):
        # 先按人头把儿童餐/亲子套餐备足（有娃就必须有玩具，这不能靠凑）
        picked, total, count = _seed_kids(kid_mains)
        # 再把用户点名的款按指定份数放进去（份数锁定，引擎不许再动）
        picked, total, count = _inject_must(picked, total, count)
        # 儿童餐 / 亲子套餐 / 用户点名款：后面的"换一件"都不许动它们
        seed_codes = {p["code"] for p in picked}
        room = max(0, th - total)
        # ⚠️ 主餐与配菜**一起**喂给 _fill_to_target（不再"先主餐后配菜"）。
        #
        #    旧写法分两步：先拿主餐池去填满 room，主餐被 cap 卡住之后，
        #    才轮到配菜补残额。结果主餐池被"一个人扛"——
        #    kids 池只有 5 款分享餐，扛 ¥1500 就必然堆量。
        #
        #    合池之后：_fill_to_target 第一轮"每款各来 1 份"会把
        #    主餐和配菜一起铺开，金额分摊到 20+ 款上，
        #    自然就不需要任何一款堆到上限以上。
        #    这也顺带修好了「¥3 蘸酱 ×5」这类观感事故——
        #    配菜是"参与者"，不再只是"填残料的"。
        #
        #    ⚠️ 顺序仍有讲究：合池时**主餐在前**（从贵到便宜本来就在前），
        #       所以"套餐打底"的产品意图还在。
        fill_pool = _engine_pool(mains + sides)
        p3, t3 = _fill_to_target(fill_pool, room, max_items - count, variant=variant)
        for e in p3:
            hit = next((p for p in picked if p["code"] == e["code"]), None)
            if hit:
                hit["count"] += e["count"]
            else:
                picked.append(dict(e))
        total = round(total + t3, 2)
        count = sum(p["count"] for p in picked)

        # 差一点点 → 补单跨线
        if total < th:
            picked, total, count = _top_up_to(
                _engine_pool(mains + sides), picked, total, count, th, budget,
                max_items, protect_codes=seed_codes,
            )
        return picked, total

    # 为「把预算花满」造一单
    def build_for_budget():
        picked, total, count = _seed_kids(kid_mains)
        # ⚠️ 同 build_for_threshold：主餐与配菜合池，别让主餐一个人扛
        picked, total, count = _inject_must(picked, total, count)
        fill_pool = _engine_pool(mains + sides)
        p3, t3 = _fill_to_target(fill_pool, budget - total, max_items - count,
                                 variant=variant)
        for e in p3:
            hit = next((p for p in picked if p["code"] == e["code"]), None)
            if hit:
                hit["count"] += e["count"]
            else:
                picked.append(dict(e))
        total = round(total + t3, 2)
        count = sum(p["count"] for p in picked)
        return picked, total

    def _seed_kids(pool):
        """先把"带玩具的餐"按人数放进单子。返回 (picked, total, count)。

        ⭐ 两个带娃模式（kids / mixed）都**优先用官方亲子套餐**
           （「开心亲子双人餐」＝ 1 大 1 小成套卖）——商家设计的官方产品，
           带娃场景就该优先用，不然它就成了摆设。
           剩下的孩子再补单人儿童餐。

        ⚠️ 那「亲子餐」和「成人+亲子」还差在哪？
           - 亲子餐（kids）：官方套餐是**骨架**，被 protect 保护、不许换掉；
             大人侧也以"成套/分享"为主，不散点单件。
           - 成人+亲子（mixed）：官方套餐照样打底，但**散点自由度更高**——
             大人可以自己挑单品，官方套餐不是唯一路径。
           一句话：**都优先官方套餐，亲子更"成套"，混合更"自由"。**
        """
        if kids_needed <= 0:
            return [], 0.0, 0

        picked = []
        total = 0.0
        count = 0

        # ---- 第一优先：官方亲子套餐（带娃模式，且店里有）----
        #
        # ⚠️ 用户给每个娃指定了儿童餐款时，官方套餐就不能硬塞了——
        #    官方套餐里的儿童餐款是固定的，满足不了"老二想吃麦乐鸡"。
        #    所以：**只要有人指定了口味，就跳过官方套餐、按人配单款儿童餐**。
        fam_n = 0
        if family_needed > 0 and family_mains and not has_specific_pick:
            chosen_fam = sorted(family_mains, key=_unit_price)[0]
            fam_n = min(family_needed, kids_needed)
            picked.append({"code": chosen_fam["code"], "count": fam_n})
            total = round(_unit_price(chosen_fam) * fam_n, 2)
            count = fam_n

        # ---- 第二优先：剩下的孩子补单人儿童餐 ----
        #
        # ⭐ 逐娃配餐：每个娃要么点他指定的那款，要么（"any"）点最便宜的。
        #    最后按 code 归并计数，给出 {code: 份数}。
        rest = kids_needed - fam_n
        if rest > 0 and pool:
            # 把"指定的款"和"剩下的不挑的娃"分开
            by_code = {m["code"]: m for m in pool}
            want = []                       # 每个待配的娃要哪款（code）
            for i in range(rest):
                pick = kid_picks_padded[fam_n + i] if kid_picks_padded else "any"
                if pick != "any" and pick in by_code:
                    want.append(pick)       # 指名要这款
                else:
                    want.append(None)       # 不挑 → 待会补最便宜的
            # 不挑的娃统一给最便宜那款
            cheap = sorted(pool, key=_unit_price)[0]["code"]
            want = [c if c else cheap for c in want]

            # 归并计数
            tally = {}
            for c in want:
                tally[c] = tally.get(c, 0) + 1
            for c, n in tally.items():
                hit = next((p for p in picked if p["code"] == c), None)
                if hit:
                    hit["count"] += n
                else:
                    picked.append({"code": c, "count": n})
                total = round(total + _unit_price(by_code[c]) * n, 2)
                count += n

        return picked, total, count

    candidates_plans = []

    # 方案 A：把预算尽量花满
    picked, total = build_for_budget()
    if picked:
        candidates_plans.append((picked, total))

    # 方案 B：各档门槛都凑够（可能比花满更划算）
    for th, _pct in sorted_tiers:
        picked, total = build_for_threshold(th)
        if picked:
            candidates_plans.append((picked, total))

    best_plan = None
    for picked, total in candidates_plans:
        # 总闸门：只留 kids_needed 份儿童餐；顺便按夹取后的实际件数重算金额
        picked = clamp_kids(picked)
        # ⚠️ 出口兜底：不管上游哪一步漏了，这里把同 code 的条目并成一条。
        #    见 merge_same_code 的说明（bug 10 · 同一款出现两次）。
        picked = merge_same_code(picked)
        # ⚠️ 再把"同款多份"拆成"同价位的不同款"（金额一分不变，见 diversify_plan）。
        #    这一步把"凑够金额"和"铺开品种"两件事都做到了。
        picked = diversify_plan(picked, meals_map, protect_codes=must_codes)
        if not picked:
            continue
        # ⚠️ 重算要按**整个菜单**查价：用户点名的款可能不在引擎池里
        #    （甚至可能点了周边），只查 mains+sides 会把它算成 ¥0。
        total = round(sum(_unit_price(meals_map[p["code"]]) * p["count"]
                          for p in picked if p["code"] in meals_map), 2)
        promo = best_promo_for(total)
        if promo is None or not picked:
            continue
        # 必须真的够门槛（不再放宽到 90%）
        if total + 1e-9 < promo["threshold"]:
            continue

        saved = promo["cut"]
        final = round(total - saved, 2)
        # 择优：省得多优先；省得一样时，花得少优先
        if (best_plan is None
                or saved > best_plan["saved"] + 1e-9
                or (abs(saved - best_plan["saved"]) < 1e-9
                    and total < best_plan["original_total"])):
            best_plan = {
                "items": picked,
                "threshold": promo["threshold"],
                "rate": promo["rate"],
                "original_total": total,
                "final_total": final,
                "saved": saved,
            }

    if best_plan:
        best_plan["note"] = "预算内花到最省，主餐优先"
    return best_plan


def build_result(meals_map, items, promotions, available_coupons=None):
    """算出这次点单的真实省钱账。

    items: [{"code": "xxx", "count": 2}, ...]
    """
    res = SavingsResult()
    available_coupons = available_coupons or []

    for it in items:
        code = str(it.get("code"))
        count = int(it.get("count", 1))
        m = meals_map.get(code)
        if not m:
            res.notes.append(f"菜单里没找到餐品编码 {code}，已跳过。")
            continue
        unit_orig = m["original_price"] or m["current_price"]
        subtotal = round(unit_orig * count, 2)
        res.original_total = round(res.original_total + subtotal, 2)
        res.items.append({
            "code": code,
            "name": m["name"],
            "count": count,
            "unit_price": unit_orig,
            "subtotal": subtotal,
        })

    # 先按"原价合计"套促销规则（促销是门店级的，人人可用）
    promo = best_fulfillment(res.original_total, promotions)
    running = res.original_total
    if promo and promo.get("amount"):
        running = round(max(running - promo["amount"], 0), 2)
        res.promotions_used.append(promo)
        res.notes.append(f"门店活动：{promo.get('desc')}，已按最优档套用。")
    elif promo:
        res.promotions_used.append(promo)
        res.notes.append("发现活动规则，但当前金额未够门槛或力度无法自动核算。")
    else:
        res.notes.append("当前金额未达到任何门店活动门槛，可考虑凑单再省。")

    # 备注券 —— ⚠️ 2026-10-10 改：**产品替用户领**，不再只是"提示他去领"。
    #   （审阅建议 + 原话：「我平时都不吃麦当劳，我不知道优惠券都有啥。」）
    #   ⚠️ 目前 mai_mai.py **不再往这里传 available_coupons**（领券已改在 CLI 里做，
    #      见 `mai_mai.claim_coupons` / `attach_coupons`）⇒ 这段实际不可达；
    #      留着是给将来要复用手臂的人看的。
    if available_coupons:
        res.notes.append(
            f"另有 {len(available_coupons)} 张券可领 —— 本工具会替用户领上，不用他操心。")

    res.final_total = running
    res.saved = round(res.original_total - res.final_total, 2)
    return res
