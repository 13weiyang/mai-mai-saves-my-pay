# -*- coding: utf-8 -*-
"""
_check_order.py — 下单模块回归（不需要联网、不需要 token）

测的是「边界与保护」，不是「能不能下单」——
因为下单是不可逆的写操作，**离线只能测它该拦的时候拦没拦住**。

覆盖：
  1. build_items 字段翻译（code/count → productCode/quantity）
  2. create_order 无确认必须被拒
  3. create_order 空清单必须被拒
  4. create_order 有确认但缺 items 参数不崩
  5. fen2yuan 分->元 换算正确
  6. cancel_order 无订单号必须被拒
  7. build_items 对脏数据（缺 code）能过滤，不生成空 item
  8. create_order 参数映射（snake -> 官方驼峰）正确
"""

import sys

sys.path.insert(0, ".")

import order as O  # noqa: E402


class FakeClient:
    """假客户端：记录被调用的工具与参数，不真的发请求。"""

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or {"success": True, "data": {}}

    def call(self, name, args=None):
        self.calls.append((name, args))
        return self.reply


fails = []
warns = []


def check(cond, label):
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        fails.append(label)


print("=" * 56)
print("  下单模块回归 _check_order.py")
print("=" * 56)

# ---------- 1. build_items 翻译 ----------
print("\n[1] build_items 字段翻译")
r = O.build_items([{"code": "1100", "count": 2}, {"code": "2200", "count": 1}])
check(r == [{"productCode": "1100", "quantity": 2},
            {"productCode": "2200", "quantity": 1}],
      "code/count → productCode/quantity")

# 已经是官方字段名的，也认
r2 = O.build_items([{"productCode": "3300", "quantity": 3}])
check(r2 == [{"productCode": "3300", "quantity": 3}], "官方字段名也认")

# 缺 count 默认 1
r3 = O.build_items([{"code": "4400"}])
check(r3 == [{"productCode": "4400", "quantity": 1}], "缺数量默认 1")

# ---------- 2. 无确认必须被拒 ----------
print("\n[2] create_order 保护：无确认")
c = FakeClient()
res = O.create_order(c, "1950751", [{"productCode": "1100", "quantity": 1}])
check(res["ok"] is False, "无 confirm 时被拒")
check(len(c.calls) == 0, "没有发出任何请求（保护生效）")

# ---------- 3. 空清单必须被拒 ----------
print("\n[3] create_order 保护：空清单")
c = FakeClient()
res = O.create_order(c, "1950751", [], confirm=True)
check(res["ok"] is False, "空清单被拒")
check(len(c.calls) == 0, "没有发出请求")

# ---------- 4. 有确认 → 真的发出请求，且参数正确 ----------
print("\n[4] create_order 参数映射")
c = FakeClient(reply={"success": True, "data": {
    "orderId": "M123", "payUrl": "https://pay.example/x"}})
res = O.create_order(
    c, "1950751",
    [{"productCode": "1100", "quantity": 2}],
    confirm=True, order_type=1, be_type=1,
    take_way_code="eat-in", remark="不要酸瓜",
)
check(res["ok"] is True, "确认后下单成功")
check(res.get("order_id") == "M123", "取到 order_id")
check(res.get("pay_url") == "https://pay.example/x", "取到支付链接")
name, args = c.calls[0]
check(name == "create-order", "调的是 create-order")
check(args["storeCode"] == "1950751", "storeCode 传对")
check(args["takeWayCode"] == "eat-in", "takeWayCode 驼峰映射对")
check(args["remark"] == "不要酸瓜", "remark 传对")
check("addressId" not in args, "没乱塞 addressId")

# 备注超长要截断到 50
print("\n[5] remark 截断")
c = FakeClient()
O.create_order(c, "1", [{"productCode": "1", "quantity": 1}],
               confirm=True, remark="备" * 120)
check(len(c.calls[0][1]["remark"]) == 50, "remark 截到 50 字")

# ---------- 6. 分 -> 元 ----------
print("\n[6] 分 -> 元 换算")
check(O.fen2yuan(3350) == 33.5, "3350 分 = ¥33.50")
check(O.fen2yuan(0) == 0.0, "0 分 = ¥0.00")
check(O.fen2yuan(None) is None, "None 不崩")

# ---------- 7. 脏数据过滤 ----------
print("\n[7] 脏数据过滤")
r = O.build_items([{"code": "", "count": 1}, {"count": 2}, {"code": "5500"}])
check(r == [{"productCode": "5500", "quantity": 1}], "缺 code 的被过滤掉")

# ---------- 8. cancel 保护 ----------
print("\n[8] cancel_order 保护")
c = FakeClient()
res = O.cancel_order(c, "")
check(res["ok"] is False, "无订单号被拒")
check(len(c.calls) == 0, "没有发出请求")

c = FakeClient(reply={"success": True, "data": {}})
res = O.cancel_order(c, "M123", "3")
check(res["ok"] is True, "有订单号能取消")
check(c.calls[0][1]["cancelReasonCode"] == "3", "取消原因传对")

# ---------- 9. 算价失败不崩 ----------
print("\n[9] 算价异常兜底")
c = FakeClient(reply={"success": False, "message": "门店已打烊"})
res = O.price_order(c, "1950751", [{"productCode": "1", "quantity": 1}])
check(res["ok"] is False, "算价失败返回 ok=False")
check("打烊" in res.get("error", ""), "错误信息透传")

c = FakeClient(reply="这不是字典")
res = O.price_order(c, "1950751", [{"productCode": "1", "quantity": 1}])
check(res["ok"] is False, "返回格式异常也不崩")

print("\n" + "=" * 56)
print(f"  结果：失败 {len(fails)} · 提醒 {len(warns)}")
print("=" * 56)
if fails:
    for f in fails:
        print(f"   ✗ {f}")
    sys.exit(1)
