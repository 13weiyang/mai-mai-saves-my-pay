# -*- coding: utf-8 -*-
"""
mai_mai.py — 麦麦真省薪 · 主程序

一句话：想吃麦麦，帮你点得又爽又省。

用法：
    # 1) 直接指定门店编码
    python mai_mai.py --store 1950751

    # 2) 按位置搜店（会列出候选，让你挑）
    python mai_mai.py --city 北京 --keyword 嘉秀

    # 3) 先看看这家店有什么（不知道吃啥时用，带官方产品图链接）
    python mai_mai.py --store 1950751 --show

    # 4) 点名要什么（主路）—— 不用报预算
    python mai_mai.py --store 1950751 --items "巨无霸,冰美式中杯"

    # 5) 算完直接下单（会有二次确认，确认后才真创建订单）
    python mai_mai.py --store 1950751 --items "巨无霸" --order

    # 6) 外送（会先逼你确认收货地址）
    python mai_mai.py --city 北京 --keyword 嘉秀 --items "巨无霸" --order --delivery
"""

import argparse
import json
import os
import re
import sys

from mcd_client import McdClient, McdError
from savings_engine import (
    parse_meals, parse_promotions, build_result, savings_hint, plan_cheapest,
)
from store_finder import (
    Store, search_stores, format_store_list,
    list_addresses, format_address_list, delivery_stores, create_address,
)
import order as order_api

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcd-token.txt")
TOKEN_ENV = "MCD_MCP_TOKEN"

SLOGAN = "我要吃麦麦，麦麦真省薪"


def load_token():
    """按优先级取 Token：环境变量 -> 上级目录 mcd-token.txt。"""
    tok = os.environ.get(TOKEN_ENV, "").strip()
    if tok:
        return tok
    path = os.path.abspath(TOKEN_FILE)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    raise McdError(
        f"没找到 MCP Token。请设置环境变量 {TOKEN_ENV}，"
        f"或把 Token 存到 {path}"
    )


# ---------- 企业团餐（beType=6）专用入口 · 先留着，别删 ----------
# ⚠️ 必读：**到店自取 / 麦乐送没有满减**（2026-10-10 实测：三家店大额单折扣恒为 0）。
#    「满 300 减 22%」那套是**企业团餐专属**规则。所以普通点餐链路**不调**这个函数。
#    保留它，是因为团餐场景将来可能用得上（她 2026-10-10 定：**先留着，万一能用上**）。
#    配套的 `savings_engine.plan_cheapest`（按门槛凑单的配餐器）也是团餐路子的，一并保留。
def fetch_group_promotions(client, store_code):
    """查某门店的**企业团餐**促销规则（beType=6 / orderType=2）。

    ⚠️ 只在做「企业团餐」时调。普通到店/外送到这里调，会拿到**用户用不上的优惠**，
       算出来的"省"是虚的 —— 这正是 2026-10-10 拆掉满减的原因。
    """
    return parse_promotions(client.call("query-promotions", {
        "storeCode": str(store_code), "orderType": 2, "beType": 6,
    }))


def pick_store(client, city, keyword, store_code=None):
    """决定用哪家门店。返回 (Store, verified)。

    这是「下单前确认地址」的第一道保险 —— **光有门店编码不够**，
    得让用户看见「店名 + 地址 + 距离」，他才认得出是不是要去的那家。

    - 给了 store_code：若同时给了片区关键词，就搜一遍把店名/地址对上；
      对不上就只拿编码，标 verified=False（下单前必须人工确认）。
    - 没给：按「城市 + 片区」搜，按距离列最近几家，**默认取最近的那家**。
    """
    if store_code:
        if keyword:
            try:
                for s in search_stores(client, city, keyword):
                    if s.code == str(store_code):
                        return s, True
            except Exception:
                pass
        # 核不到店名/地址就如实标注，别假装知道
        return Store({"storeCode": str(store_code)}), False

    stores = search_stores(client, city, keyword)
    if not stores:
        raise McdError(f"在「{city} {keyword}」附近没找到门店，换个更具体的地名试试。")

    print(f"📍 「{city} · {keyword}」附近有 {len(stores)} 家门店"
          f"（按离「{keyword}」的距离排）：\n")
    print(format_store_list(stores))
    print()
    if len(stores) > 1:
        print(f"   （默认取最近的一家：{stores[0].name}）\n")
    return stores[0], True


# 用户口语里常带、菜单名里却没有的词 —— 匹配前先拿掉
_NOISE = ["中杯", "大杯", "小杯", "超大杯", "标准", "冰", "热", "冷", "™", "®"]


def _norm_name(s):
    """规范化商品名：去掉规格词和商标符，便于模糊匹配。"""
    t = s or ""
    for w in _NOISE:
        t = t.replace(w, "")
    return t.strip()


def _name_overlap(a, b):
    """按规范化后的名字，算 a 的字符有多少出现在 b 里。"""
    def clean(s):
        return "".join(ch for ch in s
                       if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    a2, b2 = clean(_norm_name(a)), clean(_norm_name(b))
    if not a2:
        return 0.0
    hit = sum(1 for ch in set(a2) if ch in b2)
    return hit / len(set(a2))


def find_meals_by_names(meals, names):
    """按用户说的名字，在菜单里找商品（模糊匹配）。

    用户说法常和菜单名对不上——他说「冰美式中杯」，菜单里叫「麦咖啡™美式」；
    他说「全明星八件套」，菜单里叫「全明星双人分享餐八件套」。
    所以逐级放宽：
      ① 完全一样 → ② 菜单名含他说的 → ③ 去掉规格词后仍含
      → ④ 他说的含菜单名 → ⑤ 字符重合度最高（≥60% 才算）

    匹配不到的，不硬凑。

    返回 (found, missed)：
      found  = [(code, meal, 匹配方式)]
      missed = [没找到的名字]
    """
    found, missed = [], []
    for raw in names or []:
        nm = (raw or "").strip()
        if not nm:
            continue
        n1 = _norm_name(nm)
        hit = None
        for how, test in (
            ("精确", lambda m: m["name"] == nm),
            ("包含", lambda m: nm in m["name"]),
            ("去规格", lambda m: bool(n1) and n1 in _norm_name(m["name"])),
            ("部分", lambda m: m["name"] in nm),
        ):
            for m in meals.values():
                if test(m):
                    hit = (m, how)
                    break
            if hit:
                break
        if not hit:
            best, best_sc = None, 0.0
            for m in meals.values():
                sc = _name_overlap(nm, m["name"])
                if sc > best_sc:
                    best, best_sc = m, sc
            if best and best_sc >= 0.6:
                hit = (best, f"相似{best_sc:.0%}")
        if hit:
            found.append((hit[0]["code"], hit[0], hit[1]))
        else:
            missed.append(nm)
    return found, missed


# ============================================================
# 🎫 券
#   ⭐ 这一节是 2026-10-10 按审阅建议补的 —— 之前产品只"提醒用户去领券"，
#      而第一单省下的 ¥9.1，恰恰是"手工全领 + 手工挂券"那一步挣来的。
#      原话：「我平时都不吃麦当劳，**我不知道优惠券都有啥**。」
#      ⇒ 理想用户不会因为一句提示就去领券 ⇒ **产品得替她领、替她挂。**
# ============================================================

def count_coupons(client):
    """卡包里现在有多少张可用券（读 query-my-coupons 的表头）。"""
    r = client.call("query-my-coupons", {})
    t = (r.get("_text") or "") if isinstance(r, dict) else ""
    m = re.search(r"共\s*(\d+)\s*张", t)
    if m:
        return int(m.group(1))
    return len(re.findall(r"^## ", t, re.M))


def claim_coupons(client):
    """⭐ 替用户把能领的券**全领了** —— 不是"提醒他去领"。

    做法：先读卡包张数 → 调 auto-bind-coupons → 再读一次，报"新领 N 张"。
    ⚠️ 两面都要（这是定下来的一条判据）：
       · 有可领券 → 真调用，且**回读张数确实变了**；
       · 无可领券 → 出「本次无券可领」，**不是报错**。
    """
    before = count_coupons(client)
    r = client.call("auto-bind-coupons", {})
    ok = not (isinstance(r, dict) and r.get("success") is False)
    after = count_coupons(client)
    return {
        "ok": ok, "before": before, "after": after,
        "gained": max(0, after - before),
        "error": None if ok else str(r)[:140],
    }


def attach_coupons(client, store_code, items, be_type=1, order_type=1, be_code=None):
    """给这一单挑券并挂上（自动代入）。返回 (items, notes)。

    🔴 闸门：**份数 > 1 的商品一律不挂券。**
       实测（2026-10-10）：挂券时接口会把该商品的份数**吃成 1** ——
         不带券 冰美式×3 = 原价 5700；挂券 冰美式×3 = 原价 **1900**。
       ⇒ 用户想买 3 杯，挂上券只给 1 杯。**宁可不挂，不能少给。**
    ⚠️ 券是**商品级指定特价**（一个商品挂一张）；拿不到 couponId/couponCode 就不挂（不编）。
    """
    args = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
    if be_code:
        args["beCode"] = be_code
    r = client.call("query-store-coupons", args)
    cps = (r.get("data") or []) if isinstance(r, dict) else []

    by_code = {}
    for c in cps:
        if not isinstance(c, dict) or not c.get("couponId") or not c.get("couponCode"):
            continue
        for p in (c.get("products") or []):
            pc = str(p.get("productCode") or "")
            if pc:
                by_code.setdefault(pc, c)

    out, notes = [], []
    for it in items or []:
        it2 = dict(it)
        c = by_code.get(str(it.get("code") or ""))
        n = int(it.get("count") or 1)
        if c and n == 1:
            it2["couponId"] = c["couponId"]
            it2["couponCode"] = c["couponCode"]
            notes.append(f"🧧 自动挂券：「{c.get('title')}」")
        elif c and n > 1:
            notes.append(
                f"⚠️ 「{c.get('title')}」只能用在 1 份上，你点了 {n} 份 —— **没挂**"
                f"（挂券会把份数吃成 1，宁可不挂）")
        out.append(it2)
    return out, notes


def place_order(client, store, plan, meals, takeway=None,
                interactive=True, remind=None,
                be_type=1, order_type=1, be_code=None, address_id=None,
                address_label=None):
    """走完整下单流程：确认门店 → 算价 → 复述 → 二次确认 → 创建订单 → 给支付链接。

    ⚠️ 五条铁律：
      0. **先确认门店** —— 光看清单不够，得让用户核「店名 + 地址 + 距离」；
      0b. **外送必核收货地址** —— 地址是外送唯一"送错就回不了头"的东西
          （到店走错了还能走去另一家；外送送错了，菜就凉了）；
      1. 不代付 —— 只把官方支付链接交给用户；
      2. 必确认 —— 确认前绝不调 create-order；
      3. 可反悔 —— 确认阶段输入 n 直接中止，什么也不发生。
    """
    is_delivery = (be_type == 2)

    store_code, store_name = store.code, store.name
    items = order_api.build_items(plan["items"])

    # ---------- 第零步：确认门店 / 收货地址 ----------
    if interactive:
        print("=" * 46)
        print("  📍 确认门店" + ("与收货地址" if is_delivery else "（核对地址）"))
        print("=" * 46)
        print(f"   {store_name or store_code}")
        if is_delivery:
            print(f"   🛵 外送送到：{address_label or '（未提供地址）'}")
        elif store.address:
            dist = f" · 约 {store.distance} 米" if store.distance else ""
            print(f"   {store.address}{dist}")
        else:
            print("   ⚠️ 未核到地址（只给了门店编码）")
        ans = input("   确认无误？输入 y 继续，其它任意键中止：").strip().lower()
        if ans != "y":
            print("\n  ✓ 已中止，什么都没发生。")
            return
        print()

    # ---------- 第一步：官方算价（只读，安全） ----------
    print("=" * 46)
    print("  🧾 下单前核对（官方实时算价）")
    print("=" * 46)
    price = order_api.preview_order(
        client, store_code, items, be_type=be_type, order_type=order_type,
        be_code=be_code, address_id=address_id)

    # 取餐方式：外送没有"堂食/外带"，到店才有
    take_ways = price.get("take_ways") or []
    take_code = None
    if is_delivery:
        label = "外送（麦乐送）"
    else:
        if takeway:
            hit = None
            for tw in take_ways:
                if takeway in (tw.get("title") or "") or takeway == tw.get("code"):
                    hit = tw
                    break
            take_code = (hit or {}).get("code") or takeway
        elif take_ways:
            take_code = take_ways[0].get("code")
        label = order_api.TAKEWAY_LABEL.get(take_code, take_code or "堂食")

    print(order_api.format_preview(
        store_name, store_code, items, meals, price,
        take_way=label,
        address_line=(address_label if is_delivery else None)))
    print()

    # ---------- 第二步：二次确认 ----------
    if interactive:
        print("  ⚠️ 这一步会产生真实订单。付款要不要继续，你来定。")
        ans = input("  下单吗？输入 y 确认，其它任意键取消：").strip().lower()
        if ans != "y":
            print("\n  ✓ 已取消，什么都没发生。")
            return
    else:
        print("  （非交互模式，跳过确认——仅测试用）")

    # ---------- 第三步：创建订单 ----------
    print("\n… 正在下单")
    r = order_api.create_order(
        client, store_code, items, confirm=True,
        take_way_code=take_code, remark=(remind or ""),
        be_type=be_type, order_type=order_type,
        be_code=be_code, address_id=address_id,
    )
    if not r.get("ok"):
        print(f"  ✗ 下单失败：{r.get('error')}")
        return

    print("\n" + "=" * 46)
    print("  ✓ 订单已创建")
    print("=" * 46)
    oid = r.get("order_id")
    if oid:
        print(f"  订单号：{oid}")
    if price.get("ok"):
        print(f"  应付：¥{price['price']:.2f}")
    purl = r.get("pay_url")
    if purl:
        print(f"\n  💳 去这里付款（官方链接，我们不代付）：\n     {purl}")
    else:
        print("\n  ⚠️ 没拿到支付链接，请到麦当劳 App / 小程序里查看待支付订单。")
    print("\n  （如果点错了，跟我说「取消订单」，我帮你撤。）")
    print()


def _addr_from_file(client, path):
    """从 JSON 文件读地址信息，新增一条收货地址，返回 Address（失败返回 None）。

    ⚠️ 地址**走文件、不走命令行**：命令行参数会留在界面的操作记录里，
       而地址不该出现在那儿（上课要共享屏幕）。
    ⚠️ 新增是**写操作**，且官方没有删除接口 ⇒ 加之前必须二次确认。

    文件字段（2026-10-11 由 `tools/list` 核实）：
        必填 city / contactName / phone / address / addressDetail
        选填 gender
    """
    try:
        with open(path, encoding="utf-8") as f:
            info = json.load(f)
    except FileNotFoundError:
        print(f"⚠️ 找不到地址文件：{path}")
        return None
    except Exception as e:
        print(f"⚠️ 地址文件读不了：{e}")
        return None

    if not isinstance(info, dict):
        print("⚠️ 地址文件要是一个 JSON 对象（{}）")
        return None

    need = ["city", "contactName", "phone", "address", "addressDetail"]
    missing = [k for k in need if not str(info.get(k, "")).strip()]
    if missing:
        print(f"⚠️ 地址文件缺字段：{', '.join(missing)}")
        print("   需要 city / contactName / phone / address / addressDetail")
        return None

    phone = re.sub(r"\D", "", str(info["phone"]))
    if not (len(phone) == 11 and phone.startswith("1")):
        print(f"⚠️ 电话要 11 位纯数字（以 1 开头），现在拿到的是：{phone or '（空）'}")
        return None

    print("=" * 46)
    print("  📦 新增收货地址（外送）—— 请核对")
    print("=" * 46)
    print(f"   {info['contactName'].strip()} {phone}")
    print(f"   {info['city'].strip()}{info['address'].strip()}{info['addressDetail'].strip()}")
    print()
    print("   ⚠️ 这一步会**真的往账号里加一条地址**；官方没有删除接口，")
    print("      要清只能你自己到麦当劳 App／小程序里删。")
    ans = input("   新增这条地址？y 继续，其它中止：").strip().lower()
    if ans != "y":
        print("\n  ✓ 已中止，什么都没发生。")
        return None

    try:
        addr = create_address(
            client,
            city=info["city"].strip(),
            contact_name=info["contactName"].strip(),
            phone=phone,
            address=info["address"].strip(),
            address_detail=info["addressDetail"].strip(),
            gender=(info.get("gender") or "").strip() or None,
        )
    except Exception as e:
        print(f"⚠️ 新增地址失败：{e}")
        return None

    print(f"\n  ✅ 已新增收货地址（id={addr.address_id}）")
    return addr


def run(store_code=None, city=None, keyword=None,
        do_order=False, takeway=None, remind=None, items=None, show=False,
        delivery=False, address_idx=None, new_address_file=None):
    print("=" * 46)
    print(f"  {SLOGAN}")
    print("=" * 46)

    client = McdClient(load_token()).connect()
    print("✓ 已连接麦当劳 MCP\n")

    # ---------- 必答①：自取 还是 外送？ ----------
    # 外送和自取不是"送不送"的区别，是**两套门店、两套价、一步送错回不了头**。
    # 所以要下单时，没指明就先问一句。
    if not delivery and do_order and not takeway:
        print("🛵 这单怎么拿？")
        print("   [1] 到店自取（自己去拿，便宜些）")
        print("   [2] 外送 / 麦乐送（送到地址，贵一点）")
        ans = input("   输入 1 或 2（回车=1）：").strip()
        delivery = (ans == "2")
        print()

    if delivery:
        order_type, be_type = 2, 2
        # ---------- 必答②：送到哪？（外送唯一"送错就回不了头"的东西） ----------
        if new_address_file:
            addr = _addr_from_file(client, new_address_file)
            if addr is None:
                return
        else:
            addrs = list_addresses(client)
            if not addrs:
                print("⚠️ 账号里没有收货地址，没法外送。"
                      "改走「到店自取」，或先在麦当劳 App 里加个地址。")
                return
            print("=" * 46)
            print("  📦 送到哪儿？（外送地址 —— 请核对）")
            print("=" * 46)
            print(format_address_list(addrs))
            print()
            idx = 0
            if address_idx and 1 <= address_idx <= len(addrs):
                idx = address_idx - 1
            elif len(addrs) > 1:
                sel = input(f"   用哪个地址？输入编号（1-{len(addrs)}，回车=1）：").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(addrs):
                    idx = int(sel) - 1
            addr = addrs[idx]
            print(f"\n  ✅ 送到：{(addr.contact + ' ' + addr.phone).strip()}")
            print(f"     {addr.full}")
            ans = input("   这个地址对吗？y 继续，其它中止：").strip().lower()
            if ans != "y":
                print("\n  ✓ 已中止，什么都没发生。")
                return
        # 找能送到这个地址的门店（外送必须带 beCode，不是门店编码）
        ds = delivery_stores(client, addr.address_id)
        if not ds:
            print("⚠️ 这个地址附近没有可配送的门店 —— 换个地址，或改「到店自取」。")
            return
        dcode, be_code, dname = ds[0]
        store = Store({"storeCode": dcode, "storeName": dname})
        code, name = store.code, store.name
        address_id = addr.address_id
        address_label = f"{(addr.contact + ' ' + addr.phone).strip()} · {addr.full}"
        print(f"\n🏪 配送门店：{name}（{code}）\n")
    else:
        order_type, be_type = 1, 1
        be_code, address_id, address_label = None, None, None
        store, s_verified = pick_store(client, city or "北京", keyword or "", store_code)
        code, name = store.code, store.name
        # 📍 门店信息单独摆一块 —— 这是「确认门店」的依据，不是装饰
        print(f"🏪 选定门店：{name or code}")
        if store.address:
            dist = f" · 约 {store.distance} 米" if store.distance else ""
            print(f"   {store.address}{dist}")
        elif not s_verified:
            print("   ⚠️ 只给了门店编码，没核到店名和地址 —— 下单前请自己确认这家店")
        print()

    # 拉菜单（到店 / 外送是两套菜单，别混）
    print("… 正在查菜单")
    menu_args = {"storeCode": code,
                 "orderType": str(order_type), "beType": str(be_type)}
    if be_code:
        menu_args["beCode"] = be_code
    meals = parse_meals(client.call("query-meals", menu_args))
    print(f"  菜单共 {len(meals)} 道餐品\n")

    # 不查 query-promotions —— 那是**企业团餐**（beType=6）专属规则，
    # 到店自取和麦乐送都用不上，调它拿回来的优惠用户用不上、算出来的"省"是虚的。
    # 普通点餐的优惠只有两样：门店现价折扣 + 券。

    # 🎫 券：**替用户领**（不是提醒他去领）—— 这是"你不用懂，也能用上"的落点
    print("… 正在替你把能领的券领了")
    cl = claim_coupons(client)
    if not cl["ok"]:
        print(f"  ⚠️ 领券没成功（{cl['error']}）—— 不影响算价，继续\n")
    elif cl["gained"] > 0:
        print(f"  🧧 新领 {cl['gained']} 张（卡包 {cl['before']} → {cl['after']} 张）\n")
    else:
        print(f"  🧧 本次无券可领（卡包仍是 {cl['after']} 张）\n")

    # ---------- 先看看有什么（不知道吃啥时用）----------
    if show:
        groups = {}
        for m in meals.values():
            if m.get("kind") == "other":
                continue
            groups.setdefault(m.get("category") or "其它", []).append(m)
        print("=" * 46)
        print("  📖 这家店有什么")
        print("=" * 46)
        for cat, lst in groups.items():
            print(f"\n【{cat}】{len(lst)} 款")
            for m in lst:
                p = m.get("original_price") or 0
                c2 = m.get("current_price")
                tag = f"  → ¥{c2:.2f}" if c2 and p and c2 < p else ""
                print(f"   {m['name']}  ¥{p:.2f}{tag}")
                if m.get("img"):
                    print(f"      {m['img']}")
        print()
        print("   看中哪个，就这么点：")
        print('      python mai_mai.py --store <门店编码> --items "名字1,名字2"')
        print(f"\n   {SLOGAN}")
        return

    # ---------- 点名要什么：照单点（「说一句就下单」的主路）----------
    if items:
        found, missed = find_meals_by_names(meals, items)
        if missed:
            print(f"   ⚠️ 这几样菜单里没找到：{'、'.join(missed)}")
            print("      （没找到的不硬凑 —— 换个说法，或先看看菜单）\n")
        if not found:
            print("   都没找到。先看看这家店有什么：\n")
            for m in list(meals.values())[:24]:
                print(f"      {m['name']}  ¥{m['original_price']:.2f}")
            print()
            return
        print("=" * 46)
        print("  🍔 你要的：")
        print("=" * 46)
        plan_items = []
        for c, m, how in found:
            plan_items.append({"code": c, "count": 1})
            tag = "" if how == "精确" else f"   （按「{how}」匹配到）"
            print(f"   {m['name']}  ¥{m['original_price']:.2f}{tag}")
        # 🧧 自动代入：把这一单能用的券挂上（带"份数>1 不挂"的闸门）
        plan_items, cp_notes = attach_coupons(
            client, code, plan_items,
            be_type=be_type, order_type=order_type, be_code=be_code)
        for ln in cp_notes:
            print("   " + ln)
        if cp_notes:
            print()

        # ⚠️ 算价直接问官方（calculate-price）——
        #    本地引擎按原价算，会漏掉门店现价折扣，"实付"会偏高。
        oi = order_api.build_items(plan_items)
        pv = order_api.price_order(client, code, oi, be_type=be_type,
                                   order_type=order_type, be_code=be_code,
                                   address_id=address_id)
        if not pv.get("ok"):
            print(f"   ⚠️ 算价失败：{pv.get('error')}")
            return
        print("-" * 46)
        if delivery:
            # 外送：把"商品 / 配送费 / 打包费"拆开 —— 别让人以为商品卖 36 块
            goods = round((pv['original_price'] or 0)
                          - (pv.get('delivery_fee') or 0)
                          - (pv.get('packing_fee') or 0), 2)
            print(f"   商品合计：¥{goods:.2f}")
            print(f"   配送费：¥{(pv.get('delivery_fee') or 0):.2f}")
            if pv.get('packing_fee'):
                print(f"   打包费：¥{pv['packing_fee']:.2f}")
            print(f"   ➡️  应付合计：¥{pv['price']:.2f}")
        else:
            print(f"   原价合计：¥{pv['original_price']:.2f}")
            if pv.get("saved", 0) > 0:
                print(f"   🎉 省下：¥{pv['saved']:.2f}")
            print(f"   ➡️  实付：¥{pv['price']:.2f}")
        print()
        if do_order:
            place_order(client, store, {"items": plan_items}, meals,
                        takeway=takeway, remind=remind,
                        be_type=be_type, order_type=order_type,
                        be_code=be_code, address_id=address_id,
                        address_label=address_label)
        else:
            print("   （想真下单，加上 --order）")
        print(f"\n   {SLOGAN}")
        return

    # ---------- 既没点名要什么，也没说要先看看 ----------
    print("   告诉我要什么，我才好点。例如：")
    print('      python mai_mai.py --store <门店编码> --items "巨无霸,冰美式中杯"')
    print("   还不知道吃啥？先看看这家店有什么：")
    print("      python mai_mai.py --store <门店编码> --show")
    print()
    print(f"   {SLOGAN}")


def main():
    ap = argparse.ArgumentParser(description=SLOGAN)
    ap.add_argument("--store", help="门店编码（storeCode）")
    ap.add_argument("--city", help="城市名，用于搜索门店")
    ap.add_argument("--keyword", help="关键词，用于搜索门店")
    ap.add_argument("--show", action="store_true",
                    help="先看看这家店有什么（按分类列菜单，带官方产品图链接）——"
                         "不知道吃啥时用这个")
    ap.add_argument("--items", default="",
                    help="直接点名要什么（逗号分隔），例：--items 麦辣鸡腿堡套餐,可乐中杯。"
                         "这是「说一句就下单」的主路")
    ap.add_argument("--order", action="store_true",
                    help="算完直接下单（会有二次确认，确认后才真创建订单）")
    ap.add_argument("--takeway", default=None,
                    help="取餐方式：堂食 / 外带（不填默认堂食）")
    ap.add_argument("--delivery", action="store_true",
                    help="走外送（麦乐送）。会强制先确认收货地址——"
                         "地址是外送唯一送错就回不了头的东西")
    ap.add_argument("--address", type=int, default=None,
                    help="用第几个收货地址（配 --delivery 用，默认第 1 个）")
    ap.add_argument("--new-address", dest="new_address", default=None,
                    help="从 JSON 文件新增一条收货地址（配 --delivery 用）。"
                         "字段：city / contactName / phone / address / addressDetail "
                         "（选填 gender）；phone 要 11 位纯数字。"
                         "⚠️ 会真往账号加地址，加前有二次确认")
    ap.add_argument("--remind", default="",
                    help="下单备注（≤50 字），例如「不要酸瓜」")
    args = ap.parse_args()

    if not args.store and not (args.city or args.keyword):
        # 没给任何定位信息，给个提示
        print(f"  {SLOGAN}\n")
        print("请指定门店或位置，例如：")
        print("  python mai_mai.py --city 北京 --keyword 嘉秀")
        print('  python mai_mai.py --store 1950751 --items "巨无霸,冰美式中杯"')
        print("  python mai_mai.py --store 1950751 --show")
        return

    try:
        run(args.store, args.city, args.keyword,
            do_order=args.order, takeway=args.takeway, remind=args.remind,
            items=[s.strip() for s in args.items.split(",") if s.strip()],
            show=args.show, delivery=args.delivery, address_idx=args.address,
            new_address_file=args.new_address)
    except McdError as e:
        print(f"✗ 出错了：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
