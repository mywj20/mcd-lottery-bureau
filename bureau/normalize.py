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

import re

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
    name = (name or "").strip()

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
            "raw": name,
        }
    m = re.search(r"(\d+(?:\.\d+)?)\s*元(?:无门槛)?券", name)
    if m:
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": float(m.group(1)),
            "valid_days": DEFAULT_VALID_DAYS,
            "raw": name,
        }
    m = re.search(r"满\s*(\d+)\s*减\s*(\d+(?:\.\d+)?)", name)
    if m:
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": float(m.group(2)),
            "min_spend": float(m.group(1)),
            "valid_days": DEFAULT_VALID_DAYS,
            "raw": name,
        }

    # 4) 免费券（如"巨无霸免费券"）——价值 = 参照价
    if "免费" in name or "霸王餐" in name:
        ref = _lookup_reference(name)
        return {
            "name": name, "kind": "cash_coupon",
            "face_value": ref if ref else 0.0,
            "valid_days": DEFAULT_VALID_DAYS,
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
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    # 兼容两种层级：data 直接是活动对象，或 data 下有 activity 字段
    activity = data.get("activity") if isinstance(data.get("activity"), dict) else data

    draw_points = _num(activity.get("drawPoint"))
    decision = activity.get("drawDecision") or {}
    prizes_raw = activity.get("prizes") or activity.get("prizeList") or []

    prizes, unpriced = [], []
    for item in prizes_raw:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name") or item.get("prizeName") or item.get("desc") or ""
        else:
            continue
        parsed = parse_prize_name(name)
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
            "eligible": bool(decision.get("resourceEligible")),
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
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    rows = data.get("prizes") or []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or ""
        parsed = parse_prize_name(name)
        status_text = row.get("statusText") or ""
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
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    orders = None
    if isinstance(data, list):
        # 形态：[{hasNext, lastId, list: [...]}] 或直接数组
        if data and isinstance(data[0], dict) and "list" in data[0]:
            orders = []
            for block in data:
                orders.extend(block.get("list") or [])
        else:
            orders = data
    elif isinstance(data, dict):
        orders = data.get("list") or data.get("orders") or []

    if not orders:
        return {"orders_per_week": None, "avg_order_value": None,
                "n_orders": 0, "days_span": None}

    total = 0.0
    dates = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        amt = _num(o.get("totalAmount") or o.get("amount") or o.get("payAmount"))
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
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    return {
        "available": _num(data.get("availablePoint")),
        "accumulative": _num(data.get("accumulativePoint")),
        "used": _num(data.get("usedPoint")),
        "expired": _num(data.get("expiredPoint")),
        "frozen": _num(data.get("frozenPoint")),
        "expire_this_month": _num(data.get("currentMouthExpirePoint")),
        "expire_next_month": _num(data.get("nextMouthExpirePoint")),
        "last_month_expired": _num(data.get("lastMouthExpirePoint")),
    }


def build_profile(orders: dict, default_orders_per_week: float = None,
                  default_avg_order: float = 35.0) -> dict:
    """把订单数据转成估值用的用户画像。

    有订单数据时用实测频率/客单价；无数据时用保守默认（1 次/周、¥35），
    报告中如实标注数据来源。
    """
    if orders and orders.get("orders_per_week"):
        opw = float(orders["orders_per_week"])
        avg = float(orders.get("avg_order_value") or default_avg_order)
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
    try:
        return float(str(v).replace(",", "").replace("¥", "").replace("元", "").strip())
    except (TypeError, ValueError):
        return 0.0
