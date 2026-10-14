# -*- coding: utf-8 -*-
"""零依赖 MCP 客户端 —— 只用标准库直连麦当劳 MCP Server。

协议要点（2026-10-12 实测校准）：
  - 接入地址 https://mcp.mcd.cn，Streamable HTTP
  - 请求头 Authorization: Bearer <TOKEN>
  - Accept 必须同时含 application/json 与 text/event-stream
  - 返回可能是纯 JSON，也可能是 SSE（text/event-stream）包裹的 JSON
  - 错误码：401 Token 无效；429 超过 600 次/分钟

设计原则：网络层与计算层严格解耦 —— 本模块只负责"拿到原始数据"，
所有可复现的计算都在 engine/ 里离线完成。断网也能跑 demo。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

MCP_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")


class MCPError(RuntimeError):
    """MCP 调用失败的统一异常。"""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class MCPClient:
    """极简 MCP 客户端：只需 tools/call 一种能力。"""

    def __init__(self, token: str = None, timeout: int = 30):
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        self.timeout = timeout
        self._req_id = 100

    def available(self) -> bool:
        return bool(self.token)

    # ──────────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: dict = None) -> dict:
        """调用一个 MCP Tool，返回其 JSON 结果。

        返回值的两种形态都会被归一：
          - 服务端直接返回业务 JSON → 直接返回
          - 服务端返回文本包裹（markdown + JSON）→ 提取 JSON 部分
        """
        if not self.token:
            raise MCPError(
                "未配置 MCP Token。请先到 https://open.mcd.cn/mcp 申请，"
                "然后设置环境变量 MCD_MCP_TOKEN",
                code=401,
            )

        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            MCP_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer " + self.token,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise MCPError("MCP Token 无效或已过期，请重新申请", code=401)
            if e.code == 429:
                raise MCPError("触发限流（600 次/分钟），请降低频率", code=429)
            raise MCPError("HTTP %d: %s" % (e.code, e.reason), code=e.code)
        except urllib.error.URLError as e:
            raise MCPError("网络错误: %s（离线环境请使用 demo 模式）" % e.reason)

        return self._parse_response(raw, payload["id"])

    # ──────────────────────────────────────────────────────

    def _parse_response(self, raw: str, request_id=None) -> dict:
        """逐事件解析 SSE，跳过进度通知与其他请求；结构化结果优先。"""
        text = raw.lstrip("\ufeff").strip()
        if any(line.startswith(("data:", "event:", ":", "id:", "retry:")) for line in text.splitlines()):
            envelopes, chunks = [], []
            for line in text.splitlines() + [""]:
                if not line:
                    if chunks:
                        try:
                            envelopes.append(json.loads("\n".join(chunks)))
                        except json.JSONDecodeError:
                            raise MCPError("SSE 事件不是有效 JSON") from None
                        chunks = []
                elif line.startswith("data:"):
                    value = line[5:]
                    chunks.append(value[1:] if value.startswith(" ") else value)
            matches = [item for item in envelopes if isinstance(item, dict)
                       and ("result" in item or "error" in item)
                       and "id" in item and (request_id is None or item["id"] == request_id)]
            if len(matches) != 1:
                raise MCPError("SSE 缺少唯一匹配请求 ID 的响应")
            envelope = matches[0]
        else:
            try:
                envelope = json.loads(text)
            except json.JSONDecodeError:
                envelope = self._extract_json(text)
                if envelope is None:
                    raise MCPError("无法解析 MCP 响应") from None
        if not isinstance(envelope, dict):
            raise MCPError("MCP 响应必须为对象")
        if "jsonrpc" in envelope:
            if request_id is not None and envelope.get("id") != request_id:
                raise MCPError("MCP 响应请求 ID 不匹配")
            if "result" not in envelope and "error" not in envelope:
                raise MCPError("MCP 响应缺少 result")
        if "error" in envelope:
            # 不转印服务端文本，避免错误响应回显凭据。
            raise MCPError("MCP JSON-RPC 调用失败")
        result = envelope.get("result", envelope)
        if not isinstance(result, dict):
            raise MCPError("MCP result 必须为对象")
        if "isError" in result and result["isError"] is not False:
            raise MCPError("MCP Tool 返回 isError 或无效错误标记")
        if "structuredContent" in result:
            structured = result["structuredContent"]
            if not isinstance(structured, dict):
                raise MCPError("MCP structuredContent 必须为对象")
            return structured
        if "content" in result:
            content = result["content"]
            if not isinstance(content, list):
                raise MCPError("MCP content 必须为数组")
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    extracted = self._extract_json(part["text"])
                    if isinstance(extracted, dict):
                        return extracted
            raise MCPError("MCP content 缺少业务 JSON 对象")
        return result

    @staticmethod
    def _extract_json(text: str):
        """从可能夹带说明文字的文本中提取业务 JSON。

        优先找 {"success" 开头的官方业务结构，其次做平衡括号扫描。
        """
        if not isinstance(text, str):
            return None
        m = re.search(r'\{"success"', text)
        if m:
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[m.start():])
                return obj
            except json.JSONDecodeError:
                pass
        # 平衡扫描：找第一个 { 然后逐步找到配对的 }
        start = text.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start:i + 1])
                            except json.JSONDecodeError:
                                break
            start = text.find("{", start + 1)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


# ──────────────────────────────────────────────────────────
# 高层采集函数：一次拿齐分析所需的全部数据
# ──────────────────────────────────────────────────────────

def collect_account(client: MCPClient) -> dict:
    """采集积分账户（归一化见 normalize.normalize_account，此处保留原始返回）。"""
    return client.call_tool("query-my-account")


def collect_lottery(client: MCPClient) -> dict:
    """采集抽奖活动信息（奖池 + 消耗规则）。"""
    return client.call_tool("query-lottery-info")


def collect_prizes(client: MCPClient, page_size: int = 50) -> dict:
    """采集历史中奖记录（用于欧皇鉴定）。"""
    return client.call_tool("query-my-prizes", {"pageSize": page_size})


def collect_orders(client: MCPClient) -> dict:
    """采集历史订单（用于估计点餐频率与客单价）。"""
    return client.call_tool("order-list")


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        return 0.0
