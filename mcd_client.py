# -*- coding: utf-8 -*-
"""
mcd_client.py — 麦当劳 MCP 轻量客户端

只依赖 Python 标准库，不需要 pip 装任何东西。
用法：
    client = McdClient(token)
    stores = client.call("query-nearby-stores", {...})
"""

import json
import urllib.request
import urllib.error

MCP_URL = "https://mcp.mcd.cn"


class McdError(Exception):
    """MCP 调用相关错误。"""
    pass


class McdClient:
    """麦当劳 MCP（Streamable HTTP）最小客户端。

    只实现本项目需要的三个方法：
      initialize -> notifications/initialized -> tools/call
    """

    def __init__(self, token: str, url: str = MCP_URL, timeout: int = 45):
        if not token or not token.strip():
            raise McdError("MCP Token 为空。")
        self.token = token.strip()
        self.url = url
        self.timeout = timeout
        self.session_id = None

    # ---------- 底层 ----------

    def _post(self, payload: dict):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise McdError("MCP Token 无效或已过期（HTTP 401）。")
            if e.code == 429:
                raise McdError("触发限流（HTTP 429），请降低请求频率。")
            raise McdError(f"MCP 请求失败：HTTP {e.code}")

        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid

        raw = resp.read().decode("utf-8", "replace")

        # 服务器可能返回 SSE 格式，取 data: 那一行
        if not raw.lstrip().startswith("{"):
            for line in raw.splitlines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    break

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise McdError(f"无法解析 MCP 响应：{raw[:200]}")

    def _rpc(self, method: str, params=None, rid: int = 1):
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        return self._post(payload)

    # ---------- 对外 ----------

    def connect(self):
        """完成握手。调用任何工具前必须先跑一次。"""
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mai-mai-saves-my-pay", "version": "1.0.0"},
            },
            rid=1,
        )
        # 标准要求：握手后发一条 initialized 通知（无返回）
        try:
            self._rpc("notifications/initialized", {}, rid=None)
        except Exception:
            pass
        return self

    def call(self, name: str, arguments: dict = None):
        """调用一个工具，返回服务器给的文本结果（已尽量解成 dict）。"""
        r = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            rid=2,
        )
        result = r.get("result", {})
        content = result.get("content", [])
        if not content:
            return result
        text = content[0].get("text", "")
        return self._parse_tool_text(text)

    @staticmethod
    def _parse_tool_text(text: str):
        """MCP 的返回常是「说明文字 + 原始 JSON」混排。

        策略：
          1) 整段能直接解析成 JSON -> 直接用
          2) 否则从后往前找最后一个完整 JSON 对象 -> 抠出来解析
          3) 都不行 -> 原样包在 _text 里
        """
        text = (text or "").strip()
        if not text:
            return {}

        # 1) 直接解析
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # 2) 从每个 '{' 起找最后一个能解析成功的 JSON 对象
        parsed = None
        decoder = json.JSONDecoder()
        idx = text.find("{")
        while idx != -1:
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict) and ("success" in obj or "data" in obj):
                    parsed = obj
            except json.JSONDecodeError:
                pass
            idx = text.find("{", idx + 1)

        if parsed is not None:
            return parsed
        return {"_text": text}

    def list_tools(self):
        """列出服务器开放的全部工具。"""
        r = self._rpc("tools/list", {}, rid=3)
        return r.get("result", {}).get("tools", [])
