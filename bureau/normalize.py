# -*- coding: utf-8 -*-
"""归一化层 —— 把 MCP 的"给人看"结构解析成引擎的"可计算"结构。

实测校准的三处硬差异（2026-10-12 真实调用）：
  1. query-lottery-info 的 drawPoint 是字符串 "24"；能否抽只信
     drawDecision.resourceEligible，不得用 availablePoint 自行推断。
  2. 奖池没有概率字段，奖品名是自然语言（"下单立减3元券"、"麦辣三件套5折"），
     必须按名称解析类型与数值。
  3. 折扣券的面值取决于它作用在什么餐品上 —— 接口不提供，需要参照表，
     参照不到就标"无法定价"，绝不臆造。
"""

from __future__ import annotations

import math
import re

from .mcp_client import MCPError


class NormalizeError(MCPError, ValueError):
    """业务失败或结构无效，不能当作有效的零值数据。"""


def _bool(value):
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise NormalizeError("布尔字段必须为 true/false")


def _data(raw, allow_list=False):
    if not isinstance(raw, dict):
        raise NormalizeError("业务响应必须为对象")
    if "success" in raw and not _bool(raw["success"]):
        raise NormalizeError("业务响应 success=false")
    if "code" in raw and (isinstance(raw["code"], bool) or raw["code"] not in (0, 200, "0", "200")):
        raise NormalizeError("业务响应状态码失败")
    if ("isError" in raw and _bool(raw["isError"])) or raw.get("error") is not None:
        raise NormalizeError("业务响应包含错误")
    data = raw["data"] if "data" in raw else raw
    if not isinstance(data, (dict, list) if allow_list else dict):
        raise NormalizeError("业务 data 结构无效")
    return data


def _rows(data, *keys):
    rows = next((data[key] for key in keys if key in data), [])
    if not isinstance(rows, list):
        raise NormalizeError("业务列表字段必须为数组")
    return rows

# 折扣券参照价：常见餐品的公开菜单价（元）。
# 用于折算"X折券"省下多少钱。标注为估算，报告中如实说明。
DISCOUNT_REFERENCE_PRICE = {
    "麦辣三件套": 34.0,
    "板烧三件套": 35.5,
    "甜辣小食组合": 24.0,
    "小食四件套": 28.0,
    "双层鳕鱼三件套": 38.0,
    "麦旋风": 13.5,
    "巨无霸": 25.5,
    "麦辣鸡腿堡": 22.5,
    "板烧鸡腿堡": 23.5,
}

# 券的典型有效期（天）。接口不返回时按品类保守估计。
DEFAULT_VALID_DAYS = 7


def parse_prize_name(name: str) -> dict:
    """把奖品名解析成结构化奖品。

    支持的模式（来自真实奖池）：
      "下单立减3元券" / "3元券"      → cash_coupon, face=3
      "麦辣三件套5折" / "5折券"       → discount_coupon, discount=0.5, ref=参照价
      "30积分" / "30麦乐积分"         → points, points=30
      其余                            → other（按 0 计，宁可低估）
    """
    if not isinstance(name, str):
        raise NormalizeError("奖品名称必须为字符串")
    name = name.strip()
    threshold = re.search(r"满\s*(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:减|立减)\s*(\d+(?:\.\d+)?)", name)
    if threshold:
        return {"name": name, "kind": "cash_coupon", "face_value": float(threshold.group(2)),
                "min_spend": float(threshold.group(1)), "valid_days": DEFAULT_VALID_DAYS,
                "raw": name}

    # 1) 积分奖
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:麦乐|麦麦|会员)?积分", name)
    if m:
        return {
            "name": name, "kind": "points",
            "points": float(m.group(1)),
            "raw": name,
        }

    # 2) 折扣券："X折" 或 "X.X折"
    m = re.search(r"(\d(?:\.\d)?)\s*折", name)
    if m:
        discount = float(m.group(1)) / 10.0
        ref = _lookup_reference(name)
        return {
            "name": name, "kind": "discount_coupon",
            "discount": discount,
            "reference_price": ref,
            "valid_days": DEFAULT_VALID_DAYS,
            "min_spend": None if "满" in name else 0.0,
            "raw": name,
            "_ref_estimated": ref is not None,
        }

    # 3) 立减/代金券："立减X元" / "X元券" / "满X减Y"
    m = re.search(r"立减\s*(\d+(?:\.\d+)?)\s*元", name)
    if m:
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": float(m.group(1)),
            "valid_days": DEFAULT_VALID_DAYS,
            "min_spend": None if "满" in name else 0.0,
            "raw": name,
        }
    m = re.search(r"(\d+(?:\.\d+)?)\s*元(?:无门槛)?券", name)
    if m:
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": float(m.group(1)),
            "valid_days": DEFAULT_VALID_DAYS,
            "min_spend": None if "满" in name else 0.0,
            "raw": name,
        }
    # 4) 免费券（如"巨无霸免费券"）——价值 = 参照价
    if "免费" in name or "霸王餐" in name:
        ref = _lookup_reference(name)
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": ref if ref else 0.0,
            "valid_days": DEFAULT_VALID_DAYS,
            "min_spend": None if "满" in name else 0.0,
            "raw": name,
            "_ref_estimated": ref is not None,
        }

    # 5) 无法归类
    return {"name": name, "kind": "other", "raw": name}


def _lookup_reference(name: str):
    """在参照表里找名字包含的餐品，返回其价格；找不到返回 None。"""
    for key, price in DISCOUNT_REFERENCE_PRICE.items():
        if key in name:
            return price
    return None


def normalize_lottery(raw: dict) -> dict:
    """query-lottery-info 原始返回 → 引擎输入。

    返回:
        {
          activity: {name, status, draw_points, eligible, reason},
          prizes: [结构化奖品...],
          _meta: {unpriced: [...]}
        }
    """
    data = _data(raw)
    activity = data.get("activity", data)
    if not isinstance(activity, dict):
        raise NormalizeError("activity 必须为对象")
    if "drawPoint" not in activity:
        raise NormalizeError("缺少 drawPoint")
    draw_points = _num(activity["drawPoint"])
    if draw_points <= 0:
        raise NormalizeError("drawPoint 必须大于零")
    decision = activity.get("drawDecision")
    if not isinstance(decision, dict) or "resourceEligible" not in decision:
        raise NormalizeError("缺少有效 drawDecision.resourceEligible")
    eligible = _bool(decision["resourceEligible"])
    prizes_raw = _rows(activity, "prizes", "prizeList")

    prizes, unpriced = [], []
    for item in prizes_raw:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("prizeName") or item.get("desc") or ""
        else:
            raise NormalizeError("奖池记录必须为对象或名称字符串")
        if not name:
            raise NormalizeError("奖池记录缺少名称")
        parsed = parse_prize_name(name)
        if isinstance(item, dict):
            for key in ("valid_days", "min_spend"):
                if key in item:
                    parsed[key] = _num(item[key]) if item[key] is not None else None
        if parsed["kind"] == "discount_coupon" and not parsed.get("reference_price"):
            unpriced.append({"name": name, "reason": "折扣券作用的餐品不在参照表中，无法折算价值"})
        elif parsed["kind"] == "other":
            unpriced.append({"name": name, "reason": "奖品类型无法识别，按 ¥0 保守计"})
        prizes.append(parsed)

    return {
        "activity": {
            "name": activity.get("activityName") or "麦当劳积分抽奖",
            "code": activity.get("activityCode"),
            "status": activity.get("activityStatusText") or "",
            "draw_points": draw_points,
            "draw_type": activity.get("drawTypeText") or "",
            "begin": activity.get("beginTime"),
            "end": activity.get("endTime"),
            "eligible": eligible,
            "reason": decision.get("reason") or "",
            "next_consumption": decision.get("nextConsumption") or {},
        },
        "prizes": prizes,
        "_meta": {
            "prize_count": len(prizes),
            "unpriced": unpriced,
            "probability_disclosed": _has_probability(prizes_raw),
        },
    }


def _has_probability(prizes_raw) -> bool:
    """检测奖池是否包含概率字段（实测官方不公示，此处做兼容）。"""
    for item in prizes_raw or []:
        if isinstance(item, dict):
            for key in ("probability", "prob", "rate", "chance", "percent"):
                if item.get(key) is not None:
                    return True
    return False


def normalize_prizes_history(raw: dict) -> list:
    """query-my-prizes 原始返回 → 历史中奖记录列表。

    诚实处理：已过期的券价值计 0 —— 中奖的券没来得及用，等于没中。
    这是欧皇鉴定里最容易被自欺的地方（"我中了好多券" vs "都用掉了吗"）。
    """
    data = _data(raw)
    rows = _rows(data, "prizes")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise NormalizeError("奖品历史记录必须为对象")
        name = row.get("name") or ""
        parsed = parse_prize_name(name)
        status_text = row.get("statusText") or ""
        if not isinstance(status_text, str):
            raise NormalizeError("奖品状态必须为字符串")
        parsed["record_time"] = row.get("recordTime") or ""
        parsed["status"] = status_text
        # 过期/失效的券：价值归零
        if any(k in status_text for k in ("过期", "失效", "已作废")):
            parsed["_expired"] = True
        out.append(parsed)
    return out


def normalize_orders(raw: dict) -> dict:
    """order-list 原始返回 → 点餐画像（频率、客单价）。

    返回: {orders_per_week, avg_order_value, n_orders, days_span}
    无法计算时返回 None 字段，由调用方走默认画像。
    """
    data = _data(raw, allow_list=True)
    orders = None
    if isinstance(data, list):
        # 形态：[{hasNext, lastId, list: [...]}] 或直接数组
        if data and isinstance(data[0], dict) and "list" in data[0]:
            orders = []
            for block in data:
                if not isinstance(block, dict):
                    raise NormalizeError("订单分页块必须为对象")
                orders.extend(_rows(block, "list"))
        else:
            orders = data
    elif isinstance(data, dict):
        orders = _rows(data, "list", "orders")

    if not orders:
        return {"orders_per_week": None, "avg_order_value": None,
                "n_orders": 0, "days_span": None}

    total = 0.0
    dates = []
    for o in orders:
        if not isinstance(o, dict):
            raise NormalizeError("订单记录必须为对象")
        amt = _num(next((o[key] for key in ("totalAmount", "amount", "payAmount") if key in o), 0))
        if amt > 0:
            total += amt
        d = o.get("orderTime") or o.get("createTime") or o.get("orderDate")
        if d:
            dates.append(str(d)[:10])

    n = len(orders)
    avg = total / n if n else None

    orders_per_week = None
    days_span = None
    if len(dates) >= 2:
        from datetime import date
        parsed_dates = []
        for d in dates:
            try:
                y, m, dd = d.split("-")
                parsed_dates.append(date(int(y), int(m), int(dd)))
            except (ValueError, AttributeError):
                continue
        if len(parsed_dates) >= 2:
            span = (max(parsed_dates) - min(parsed_dates)).days
            if span > 0:
                days_span = span
                orders_per_week = n / (span / 7.0)

    return {
        "orders_per_week": orders_per_week,
        "avg_order_value": avg,
        "n_orders": n,
        "days_span": days_span,
    }


def normalize_account(raw: dict) -> dict:
    """query-my-account 原始返回 → 标准账户结构。

    官方字段拼写坑：currentMouthExpirePoint（Mouth 不是 Month），三个过期字段
    全部沿用这个拼错的版本，必须照抄。
    """
    data = _data(raw)
    if "availablePoint" not in data:
        raise NormalizeError("账户缺少 availablePoint")
    return {
        "available": _num(data["availablePoint"]),
        "accumulative": _num(data.get("accumulativePoint", 0)),
        "used": _num(data.get("usedPoint", 0)),
        "expired": _num(data.get("expiredPoint", 0)),
        "frozen": _num(data.get("frozenPoint", 0)),
        "expire_this_month": _num(data.get("currentMouthExpirePoint", 0)),
        "expire_next_month": _num(data.get("nextMouthExpirePoint", 0)),
        "last_month_expired": _num(data.get("lastMouthExpirePoint", 0)),
    }


def build_profile(orders: dict, default_orders_per_week: float = None,
                  default_avg_order: float = 35.0) -> dict:
    """把订单数据转成估值用的用户画像。

    有订单数据时用实测频率/客单价；无数据时用保守默认（1 次/周、¥35），
    报告中如实标注数据来源。
    """
    if orders and orders.get("orders_per_week") is not None:
        opw = float(orders["orders_per_week"])
        avg = float(orders["avg_order_value"] if orders.get("avg_order_value") is not None else default_avg_order)
        source = "estimated_from_orders"
    else:
        opw = float(default_orders_per_week if default_orders_per_week is not None else 1.0)
        avg = float(default_avg_order)
        source = "default_assumption"

    return {
        "orders_per_week": opw,
        "avg_order_value": avg,
        "_source": source,
    }


def _num(v) -> float:
    if v is None:
        raise NormalizeError("业务数值字段不能为空")
    try:
        if isinstance(v, bool):
            raise ValueError
        number = float(str(v).replace(",", "").replace("¥", "").replace("元", "").strip())
        if not math.isfinite(number) or number < 0:
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise NormalizeError("业务数值字段必须为有限非负数") from None
