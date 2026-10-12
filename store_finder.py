# -*- coding: utf-8 -*-
"""
store_finder.py — 门店查找模块

解决一个真问题：
    用户不知道门店叫什么名字（比如"我家楼下那家"），
    但他知道自己在哪 —— 所以让他「说出位置」，我们把店列出来给他挑。

MCP 的门店接口（query-nearby-stores）只认「城市 + 关键词」，
不支持经纬度。所以这里做两件事：
    1. 城市 + 关键词 -> 列出候选门店（用户挑一家）
    2. 浏览器定位拿到的坐标 -> 交给调用方去做「坐标转地名」（可选增强）
"""

import re


class Store:
    """一家门店。"""

    def __init__(self, d):
        self.code = str(d.get("storeCode", ""))
        self.name = d.get("storeName", "")
        self.address = d.get("address", "")
        self.distance = d.get("distance", 0)
        self.be_code = d.get("beCode", "")
        self.reservation = d.get("reservation", False)
        self.open_time = (
            f"{d.get('businessStartTime', '')}-{d.get('businessEndTime', '')}"
        )

    def __repr__(self):
        return f"<Store {self.name} ({self.code}) {self.distance}m>"

    def pretty(self, idx=None):
        prefix = f"[{idx}] " if idx is not None else ""
        dist = f" · 约 {self.distance} 米" if self.distance else ""
        return f"{prefix}{self.name}{dist}\n      {self.address}"


def search_stores(client, city, keyword):
    """按「城市 + 地名」搜门店，返回 Store 列表（按距离升序）。

    ⚠️ 这里的 distance 是「离 keyword 那个地名」的距离，**不是离用户本人**。
    query-nearby-stores 只认「城市 + 地名」，不认识经纬度（2026-10-10 实测）：
    同一家九棵树餐厅，关键词给「九棵树」是 49 米，给「果园」就变 987 米。
    ⇒ 想让「离我最近」成立，keyword 必须填**你所在的片区名**。
    """
    raw = client.call("query-nearby-stores", {
        "beType": "1", "searchType": "2",
        "city": city, "keyword": keyword,
    })

    # 正常情况：标准 JSON，data 是数组
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, list) and data:
        stores = [Store(d) for d in data if isinstance(d, dict)]
        stores.sort(key=lambda s: s.distance or 9e9)   # 近的在前
        return stores

    # 兜底：有些返回会把数据塞在文本里
    text = raw.get("_text", "") if isinstance(raw, dict) else str(raw)
    codes = re.findall(r'"storeCode":"?(\d+)"?', text)
    names = re.findall(r'"storeName":"([^"]+)"', text)
    out = []
    for i, code in enumerate(codes):
        out.append(Store({
            "storeCode": code,
            "storeName": names[i] if i < len(names) else "未知门店",
        }))
    return out


def format_store_list(stores, limit=5):
    """把门店列表排成人能看的样子。"""
    lines = []
    for i, s in enumerate(stores[:limit], 1):
        lines.append(s.pretty(i))
    return "\n".join(lines)


# ---------- 外送：地址 ----------

class Address:
    """一个收货地址（外送必需）。

    ⚠️ 这是用户的私人信息：**只在会话里显示给用户本人核对，不写进任何文件/日志**。
    """

    def __init__(self, d):
        self.address_id = str(d.get("addressId", ""))
        self.contact = d.get("contactName", "")
        self.phone = d.get("phone", "")
        self.full = d.get("fullAddress", "")

    def pretty(self, idx=None):
        prefix = f"[{idx}] " if idx is not None else ""
        head = "".join(x for x in (self.contact, f" {self.phone}".strip() if self.phone else ""))
        return f"{prefix}{head}\n      {self.full}"


def list_addresses(client):
    """拉用户的收货地址列表。返回 [Address]。"""
    raw = client.call("delivery-query-addresses", {})
    data = raw.get("data") if isinstance(raw, dict) else None
    arr = None
    if isinstance(data, dict):
        arr = data.get("addresses")
    elif isinstance(data, list):
        arr = data
    if not arr:
        return []
    return [Address(d) for d in arr if isinstance(d, dict)]


def format_address_list(addrs, limit=8):
    lines = []
    for i, a in enumerate(addrs[:limit], 1):
        lines.append(a.pretty(i))
    return "\n".join(lines)


def delivery_stores(client, address_id, be_type=2):
    """查这个地址能配送的门店。返回 [(storeCode, beCode, storeName)]。

    ⚠️ 外送下单必须带 `beCode`（来自这里），不是门店编码。缺它会被拒。
    """
    raw = client.call("delivery-query-stores", {
        "addressId": str(address_id), "beType": be_type,
    })
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        arr = data.get("stores") or data.get("list")
    else:
        arr = None
    out = []
    for s in (arr or []):
        if isinstance(s, dict):
            out.append((
                str(s.get("storeCode", "")),
                s.get("beCode", ""),
                s.get("storeName", ""),
            ))
    return out


def create_address(client, city, contact_name, phone, address,
                   address_detail, gender=None):
    """新增一条收货地址（外送用），返回 Address。

    ⚠️ 这是**写操作**：会真的往账号里加一条地址，而且官方 MCP
       **没有「删除地址」的工具** —— 加进去就在账号里了，
       要清只能用户自己到麦当劳 App／小程序里删。
       ⇒ 能不加就不加；加之前必须让用户点头。

    字段（2026-10-11 由 `tools/list` 核实，非推测）：
        必填：city / contactName / phone / address / addressDetail
        选填：gender（"先生" / "女士"）
        phone 要 **11 位纯数字**（以 1 开头）；带横杠、空格会被拒。
    """
    args = {
        "city": city,
        "contactName": contact_name,
        "phone": phone,
        "address": address,
        "addressDetail": address_detail,
    }
    if gender:
        args["gender"] = gender

    raw = client.call("delivery-create-address", args)

    # 返回结构官方没给样例，这儿把几种可能都认一遍（别指望字段名能自动对上）
    data = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(data, dict):
        d = dict(data)
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        d = dict(data[0])
    elif isinstance(raw, dict):
        d = dict(raw)
    else:
        d = {}

    aid = d.get("addressId") or d.get("address_id") or d.get("id")
    if not aid:
        raise ValueError(
            f"新增地址没拿到 addressId，原始返回：{str(raw)[:300]}"
        )

    # 补齐「查地址」那套字段名，好让 Address 类直接用
    d["addressId"] = str(aid)
    d.setdefault("contactName", contact_name)
    d.setdefault("phone", phone)
    d.setdefault("fullAddress", f"{city}{address}{address_detail}")
    return Address(d)
