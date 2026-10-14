# -*- coding: utf-8 -*-
"""奖品估值模型 —— 把"中奖了"翻译成"值多少钱"。

核心立场
--------
抽奖奖品的面值不是它的价值。同一张「立减 3 元券」：

  - 对每周都吃麦当劳的人 ≈ 3 元现金（迟早用掉）
  - 对两个月没进过店的人 = 0 元（券会静静过期）
  - 对"为了用券而点餐"的人 = 负值（花了本不该花的钱）

所以本模块的估值一律经过两层折价：

  第一层 · 使用概率折价   value = face_value × P(会去用掉这张券)
  第二层 · 诱导消费扣减   value -= 客单价 × P(这单本来不打算下)

第二层是本项目与"面值派"最大的分野：券面值再大，若它诱发的是
一笔你本来不会花的钱，那笔支出要从收益里扣掉。
"""

from __future__ import annotations

# 积分折算锚点：每 100 积分的商城最优兑现价值（元）。
# 2026-10-12 实测：商城最优出口 3.20 元/100分（50分换 6.9 元派），
# 最差出口 1.64 元/100分（800分换巨无霸组合）。默认取最优口径，
# 报告中标注为假设值，可由调用方覆盖。
# 注：保底回血率等核心结论是**比值**，与汇率无关（单位约掉）。
DEFAULT_POINT_VALUE_PER_100 = 3.2


def point_unit_value(point_value_per_100: float) -> float:
    """每 1 积分折合多少元（机会成本口径）。"""
    return max(point_value_per_100, 0.0) / 100.0


def estimate_use_probability(orders_per_week: float, coupon_valid_days: int) -> float:
    """用点餐频率估计一张券在有效期内被用掉的概率。

    以「下一单何时来」为指数分布的粗模型：
        P(有效期内至少下一单) = 1 - exp(-frequency × valid_days / 7)

    frequency=0（几乎不消费）→ 概率趋近 0；高频用户 → 趋近 1。
    这只是个上界估计：就算下了单，也未必用这张券，报告中按"乐观上限"标注。
    """
    import math

    if orders_per_week <= 0 or coupon_valid_days <= 0:
        return 0.0
    lam = orders_per_week * (coupon_valid_days / 7.0)
    return max(0.0, min(1.0, 1.0 - math.exp(-lam)))


def value_cash_coupon(face_value: float, use_prob: float) -> float:
    """立减券价值 = 面值 × 使用概率。"""
    return max(face_value, 0.0) * use_prob


def value_discount_coupon(reference_price: float, discount: float, use_prob: float) -> float:
    """折扣券价值 = 折扣省下的钱 × 使用概率。

    discount 为折后价比例：5 折 = 0.5 → 省下 reference_price × 0.5。
    """
    discount = min(max(discount, 0.0), 1.0)
    saved = max(reference_price, 0.0) * (1.0 - discount)
    return saved * use_prob


def induced_spending_penalty(avg_order_value: float, use_prob: float, orders_per_week: float) -> float:
    """诱导消费扣减：券诱发的、本不会发生的支出，要从券的收益里扣除。

    逻辑：对**高频用户**（≥1 次/周），用券基本发生在本来就要下的单上，
    无诱导支出（扣减 = 0）；对**低频用户**，一部分用券行为是"为了用券而
    专门去一趟"，这部分额外支出是券的隐性成本。

    诱导比例 = max(0, 1 − 周频次)，即：
      - 2 次/周 → 0（无诱导）
      - 0.5 次/周 → 0.5
      - 从不消费 → 1（全额诱导）

    扣减额 = 诱导比例 × 使用概率 × 客单价 × 0.5
    其中 0.5 为"后悔系数"：即使是被诱发的消费，也吃到了一半价值的餐品，
    只有另一半属于真正的"非计划支出"。
    """
    inducement_ratio = max(0.0, 1.0 - max(orders_per_week, 0.0))
    regret_factor = 0.5
    return max(avg_order_value, 0.0) * inducement_ratio * use_prob * regret_factor


def value_prize(prize: dict, profile: dict, point_value_per_100: float) -> dict:
    """给单个奖品估值，返回带推导过程的结果。

    prize 结构（normalize 后）:
        {name, kind: "points"|"cash_coupon"|"discount_coupon"|"other",
         points?, face_value?, reference_price?, discount?, valid_days?}

    profile 结构:
        {orders_per_week, avg_order_value, baseline_consume}

    返回:
        {name, kind, face_value, use_prob, gross, penalty, net, formula}
    """
    kind = prize.get("kind", "other")
    name = prize.get("name", "未知奖品")
    valid_days = int(prize.get("valid_days") or 7)
    opw = float(profile.get("orders_per_week") or 0.0)
    use_prob = estimate_use_probability(opw, valid_days)
    avg_order = float(profile.get("avg_order_value") or 0.0)
    unit = point_unit_value(point_value_per_100)

    if kind == "points":
        pts = float(prize.get("points") or 0)
        net = pts * unit
        return {
            "name": name, "kind": kind,
            "face_value": pts, "unit": "积分",
            "use_prob": 1.0, "gross": net, "penalty": 0.0, "net_value": net,
            "formula": "%g 积分 × %.4f 元/分" % (pts, unit),
        }

    if kind == "cash_coupon":
        face = float(prize.get("face_value") or 0)
        gross = value_cash_coupon(face, use_prob)
        penalty = induced_spending_penalty(avg_order, use_prob, opw)
        net = max(gross - penalty, 0.0)
        return {
            "name": name, "kind": kind,
            "face_value": face, "unit": "元",
            "use_prob": use_prob, "gross": gross, "penalty": penalty, "net_value": net,
            "formula": "面值 ¥%.2f × 使用概率 %.0f%% − 诱导消费扣减 ¥%.2f"
                       % (face, use_prob * 100, penalty),
        }

    if kind == "discount_coupon":
        ref = float(prize.get("reference_price") or 0)
        disc = float(prize.get("discount") or 1.0)
        gross = value_discount_coupon(ref, disc, use_prob)
        penalty = induced_spending_penalty(avg_order, use_prob, opw)
        net = max(gross - penalty, 0.0)
        return {
            "name": name, "kind": kind,
            "face_value": ref * (1 - disc), "unit": "元",
            "use_prob": use_prob, "gross": gross, "penalty": penalty, "net_value": net,
            "formula": "原价 ¥%.2f × 折扣力度 %.0f%% × 使用概率 %.0f%% − 扣减 ¥%.2f"
                       % (ref, (1 - disc) * 100, use_prob * 100, penalty),
        }

    # 无法归类的奖品：按 0 计，宁可低估，绝不臆造
    return {
        "name": name, "kind": "other",
        "face_value": 0.0, "unit": "—",
        "use_prob": 0.0, "gross": 0.0, "penalty": 0.0, "net_value": 0.0,
        "formula": "无法归类，按 ¥0 保守计",
    }


def point_value_from_mall(mall_items: list) -> tuple:
    """从商城兑换项计算「每 100 积分的兑现价值」锚点。

    mall_items: [{name, points, net_saving}]，net_saving = 常规价 − 用券价。
    取效率最高的一项作为锚（用户积分的最优出路），返回 (value_per_100, best_item)。
    无有效数据时返回 (None, None)，由调用方决定回退策略。
    """
    best = None
    best_rate = -1.0
    for item in mall_items or []:
        pts = float(item.get("points") or 0)
        saving = float(item.get("net_saving") or 0)
        if pts <= 0 or saving <= 0:
            continue
        rate = saving / pts * 100.0
        if rate > best_rate:
            best_rate = rate
            best = item
    if best is None:
        return None, None
    return best_rate, best
