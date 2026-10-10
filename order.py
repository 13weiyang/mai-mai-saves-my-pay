# -*- coding: utf-8 -*-
"""
order.py — 下单模块（麦当劳 MCP create-order 封装）

设计原则（三件不可退让的事）：
  1. **不代付**：create-order 返回的是订单详情 + 支付链接，
     我们把链接交给用户，让用户自己去官方渠道付。这个模块
     永远不碰钱、不存支付凭证。
  2. **必须二次确认**：create-order 是写操作（可能产生真实订单），
     调用前必须由调用方显式传入 confirm=True。默认不执行。
  3. **价格单位是「分」**：MCP 的价格字段全部以分为单位（3350 = ¥33.50）。
     这个模块负责在边界上换回「元」，对外只吐元。

官方 create-order 的入参（2026-10-09 实调 tools/list 核实）：
    storeCode      必填，门店编码
    orderType      必填，1=到店 / 2=外送
    beType         必填，1=到店取餐 / 2=麦乐送 / 5=得来速 / 6=企业团餐
    items          商品列表 [{productCode, quantity, ...}]
    takeWayCode    取餐方式，来自 calculate-price 返回的 takeWayList
                   （常见值 eat-in=堂食 / locker-in=外带）
    addressId      外送或团餐必填
    beCode         得来速/外送/团餐必传，来自门店查询结果
    reservationDate 预约单必传，格式 yyyy-MM-dd HH:mm
    remark         备注，≤50 字
"""

from mcd_client import McdError


# 取餐方式的中文名（来自 calculate-price 的 takeWayList，这里兜个底）
TAKEWAY_LABEL = {
    "eat-in": "堂食",
    "locker-in": "外带（店内取餐柜）",
}


def fen2yuan(fen):
    """分 -> 元。MCP 的价格字段单位是分。"""
    try:
        return round(float(fen) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def build_items(plan_items):
    """把引擎给出的方案（[{code, count}]）转成 create-order 要的 items。

    引擎里字段叫 code / count，官方接口要 productCode / quantity，
    这里做一次显式翻译——别指望字段名能对上。

    ⭐ 套餐子项（可选）：若该项带 `rounds`，一并转成官方要的 `roundList`。
       格式（2026-10-10 实测确认，多轮可用）：
           [{"round": "1", "comboItemList": [{"code": "...", "quantity": 2}]}]

       ⚠️ 两个实测踩到的坑，写在这儿免得再踩：
         1. 字段名是 **`round`**（字符串），**不是 `roundId`** ——
            写成 roundId 服务端直接 500（「服务器发生了未知的问题」）。
         2. 子项 `code` 必须是 **query-meal-detail 返回的真实 code**。
            手写一个错的 code（如把「可乐中杯」写成 30，真实是 3050），
            报的是「商品已售罄或不可售」—— 错 code 会伪装成"售罄"，极易查错方向。

    `rounds` 允许两种形态：
        {"rounds": [{"round": "1", "comboItemList": [...]}]}   # 已经是官方格式
        {"rounds": [("1", [{"code": "...", "quantity": 2}])]}   # 元组简写
    """
    items = []
    for it in plan_items or []:
        code = it.get("code") or it.get("productCode")
        qty = it.get("count") or it.get("quantity") or 1
        if not code:
            continue
        entry = {"productCode": str(code), "quantity": int(qty)}

        # 🧧 券（可选）：商品级指定特价。
        #    ⚠️ 上游必须保证：**只有份数 == 1 的商品才挂券** ——
        #       实测挂券会把该商品的份数吃成 1（详见 mai_mai.attach_coupons 的闸门）。
        if it.get("couponId"):
            entry["couponId"] = it["couponId"]
            entry["couponCode"] = it.get("couponCode")

        rounds = it.get("rounds")
        if rounds:
            rl = []
            for rd in rounds:
                if isinstance(rd, dict):
                    rl.append({
                        "round": str(rd.get("round") or rd.get("roundId")),
                        "comboItemList": [
                            {"code": str(c.get("code")), "quantity": int(c.get("quantity") or 1)}
                            for c in (rd.get("comboItemList") or []) if c.get("code")
                        ],
                    })
                else:
                    rid, picks = rd
                    rl.append({
                        "round": str(rid),
                        "comboItemList": [
                            {"code": str(c.get("code")), "quantity": int(c.get("quantity") or 1)}
                            for c in picks if c.get("code")
                        ],
                    })
            entry["roundList"] = rl

        items.append(entry)
    return items


def price_order(client, store_code, items, be_type=1, order_type=1,
                be_code=None, address_id=None, reservation_date=None):
    """调 calculate-price，拿官方权威价格 + 取餐方式列表。

    返回 dict：
        {ok, original_price, discount, price, saved,
         product_list, take_ways, raw, error}
    价格单位已换成「元」。
    """
    args = {
        "storeCode": str(store_code),
        "orderType": order_type,
        "beType": be_type,
        "items": items,
    }
    if be_code:
        args["beCode"] = be_code
    if address_id:
        args["addressId"] = address_id
    if reservation_date:
        args["reservationDate"] = reservation_date

    try:
        r = client.call("calculate-price", args)
    except McdError as e:
        return {"ok": False, "error": str(e)}

    if not isinstance(r, dict):
        return {"ok": False, "error": "算价返回格式异常"}
    if not r.get("success"):
        return {"ok": False, "error": r.get("message") or "算价失败", "raw": r}

    d = r.get("data", {}) or {}
    original_fen = d.get("originalPrice")
    price_fen = d.get("price")
    return {
        "ok": True,
        "original_price": fen2yuan(original_fen),
        "discount": fen2yuan(d.get("discount")),
        "price": fen2yuan(price_fen),
        "saved": fen2yuan((original_fen or 0) - (price_fen or 0)),
        # ⚠️ 外送单的 originalPrice 里**含配送费 + 打包费**（2026-10-10 实测：
        #    巨无霸 2900 + 配送 600 + 打包 110 = 3610）。所以外送要拆开给用户看，
        #    不能把"商品 + 运费 + 打包"一起当成"原价合计"，那会让人以为商品卖 36.1。
        "delivery_fee": fen2yuan(d.get("deliveryPrice")),
        "packing_fee": fen2yuan(d.get("packingPrice")),
        "product_list": d.get("productList", []),
        "take_ways": d.get("takeWayList", []),
        "raw": d,
    }


def preview_order(client, store_code, items, **kw):
    """下单前的「预演」：只算价，绝不创建订单。

    这是给用户看的那一步——门店、商品清单、官方实付，一并复述清楚，
    等用户点头。
    """
    return price_order(client, store_code, items, **kw)


def create_order(client, store_code, items, confirm=False, **kw):
    """真正创建订单。

    ⚠️ confirm=False（默认）时直接拒绝执行——写操作必须有显式确认。

    成功返回：
        {ok, order_id, pay_url, order_info, take_ways, raw, error}
    - pay_url：官方支付链接，交给用户自己去付（**我们不代付**）
    """
    if not confirm:
        return {
            "ok": False,
            "error": "没确认就不下单。create-order 会产生真实订单，"
                     "必须由用户明确同意后再调（confirm=True）。",
        }
    if not items:
        return {"ok": False, "error": "购物清单是空的，没法下单。"}

    args = {
        "storeCode": str(store_code),
        "orderType": kw.get("order_type", 1),
        "beType": kw.get("be_type", 1),
        "items": items,
    }
    for k_src, k_dst in (
        ("be_code", "beCode"),
        ("address_id", "addressId"),
        ("reservation_date", "reservationDate"),
        ("take_way_code", "takeWayCode"),
        ("remark", "remark"),
    ):
        v = kw.get(k_src)
        if v:
            args[k_dst] = v[:50] if k_dst == "remark" else v

    try:
        r = client.call("create-order", args)
    except McdError as e:
        return {"ok": False, "error": str(e)}

    if not isinstance(r, dict):
        return {"ok": False, "error": "下单返回格式异常"}
    if not r.get("success"):
        return {"ok": False, "error": r.get("message") or "下单失败", "raw": r}

    d = r.get("data", {}) or {}
    return {
        "ok": True,
        "order_id": d.get("orderId") or d.get("orderNo"),
        # ⚠️ 2026-10-10 实测更正：官方文档说 create-order「返回订单详情与支付链接」，
        #    但**堂食单实测没有 payUrl/payLink/url 这类字段**。
        #    实际拿到的是：
        #      · payId          支付 ID（不是可点的链接）
        #      · expirePayTime  支付截止时间（实测下单后约 15 分钟）
        #      · pickupCode     取餐码（堂食用；未支付/已取消时为空）
        #    原代码只找 payUrl/payLink/url ⇒ 永远是 None。这里把真实字段补上。
        "pay_id": d.get("payId"),
        "expire_pay_time": d.get("expirePayTime"),
        "pickup_code": d.get("pickupCode"),
        # ⚠️ 字段名是 payH5Url（2026-10-10 实测确认）——
        #    之前写成 payUrl/payLink/url，导致误判"没有支付链接"。
        "pay_url": d.get("payH5Url") or d.get("payUrl") or d.get("payLink") or d.get("url"),
        "order_info": d,
        "take_ways": d.get("takeWayList", []),
        "raw": d,
    }


def cancel_order(client, order_id, reason_code="1"):
    """取消订单（兜底用）。reason_code 见官方定义：
    1=改主意了 2=重复下单 3=点错了/点多了/点少了 4=地址/电话填错了
    5=送达时间选错了 -1=其它原因
    """
    if not order_id:
        return {"ok": False, "error": "没有订单号，取消不了。"}
    try:
        r = client.call("cancel-order", {
            "orderId": str(order_id),
            "cancelReasonCode": str(reason_code),
        })
    except McdError as e:
        return {"ok": False, "error": str(e)}
    if isinstance(r, dict) and r.get("success"):
        return {"ok": True, "raw": r.get("data", r)}
    return {"ok": False, "error": (r or {}).get("message") or "取消失败", "raw": r}


def format_preview(store_name, store_code, items, meals_map, price_info,
                   take_way=None, address_line=None):
    """把「预演」结果排成给人看的几行字（终端用）。

    这是二次确认里「复述」那一步——门店、取餐方式、清单、实付，一个不落。
    外送时额外把**收货地址**摆出来（地址是外送唯一"送错就回不了头"的东西）。
    """
    lines = []
    lines.append("┌" + "─" * 44)
    lines.append("│ 请核对这一单：")
    lines.append("├" + "─" * 44)
    lines.append(f"│ 🏪 门店：{store_name}（{store_code}）")
    lines.append(f"│ 🥡 取餐：{take_way or '堂食'}")
    if address_line:
        lines.append(f"│ 🛵 送到：{address_line}")
    lines.append("│ 📋 清单：")
    for it in items:
        code = it.get("productCode")
        qty = it.get("quantity", 1)
        m = meals_map.get(code, {})
        name = m.get("name") or code
        unit = m.get("price")
        sub = (unit * qty) if isinstance(unit, (int, float)) else None
        q = f" ×{qty}" if qty > 1 else ""
        tail = f"  ¥{sub:.2f}" if sub is not None else ""
        lines.append(f"│    · {name}{q}{tail}")
    if price_info.get("ok"):
        lines.append("├" + "─" * 44)
        if address_line and price_info.get("delivery_fee") is not None:
            # 外送：拆开给用户看 —— 商品 / 配送费 / 打包费 各是各的
            goods = round((price_info.get("original_price") or 0)
                          - (price_info.get("delivery_fee") or 0)
                          - (price_info.get("packing_fee") or 0), 2)
            lines.append(f"│ 商品合计：¥{goods:.2f}")
            lines.append(f"│ 配送费：¥{(price_info.get('delivery_fee') or 0):.2f}")
            if price_info.get("packing_fee"):
                lines.append(f"│ 打包费：¥{price_info['packing_fee']:.2f}")
            lines.append(f"│ ➡️ 应付合计：¥{price_info['price']:.2f}")
        else:
            lines.append(f"│ 原价合计：¥{price_info['original_price']:.2f}")
            if price_info.get("saved"):
                lines.append(f"│ 官方优惠：-¥{price_info['saved']:.2f}")
            lines.append(f"│ ➡️ 官方实付：¥{price_info['price']:.2f}")
    else:
        lines.append(f"│ ⚠️ 算价没成功：{price_info.get('error')}")
    lines.append("└" + "─" * 44)
    return "\n".join(lines)
