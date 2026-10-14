# -*- coding: utf-8 -*-
"""抽奖分析：确定性下界与情景估值分离，不推断未披露概率。"""
from __future__ import annotations

import math


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _points(prize):
    raw = prize.get("raw")
    return prize.get("points", raw.get("points") if isinstance(raw, dict) else None)


def floor_recovery(prizes: list, draw_cost_points: float, point_unit: float,
                   pool_complete: bool = False) -> dict:
    """分别输出模型估值与下界；pool_complete 需外部证据，不从无概率字段推断。"""
    if not prizes or not _finite(draw_cost_points) or draw_cost_points <= 0 \
            or not _finite(point_unit) or point_unit < 0:
        return {"ok": False, "guarantee_proven": False, "reason": "奖池或成本无效，无法计算下界"}
    bounds, values = [], []
    for prize in prizes:
        kind = prize.get("kind")
        if prize.get("valuation_known") is False or kind not in ("points", "cash_coupon", "discount_coupon"):
            return {"ok": False, "guarantee_proven": False, "reason": "存在未知奖品，无法证明下界"}
        points = _points(prize) if kind == "points" else 0.0
        points_known = _finite(points) and points >= 0
        bounds.append(points if points_known else None)
        model_value = points * point_unit if kind == "points" and points_known else prize.get("net_value")
        if not _finite(model_value) or model_value < 0:
            return {"ok": False, "guarantee_proven": False, "reason": "奖品模型估值无效"}
        values.append(model_value)
    if point_unit == 0 and any(p.get("kind") != "points" for p in prizes):
        return {"ok": False, "guarantee_proven": False, "reason": "零汇率下混合奖品无法比较估值"}
    worst_idx = (bounds.index(min(bounds)) if all(p.get("kind") == "points" for p in prizes)
                 and all(v is not None for v in bounds) else values.index(min(values)))
    worst = prizes[worst_idx]
    points_worst = _points(worst)
    invariant = worst.get("kind") == "points" and _finite(points_worst) and points_worst >= 0
    cost = draw_cost_points * point_unit
    ratio = points_worst / draw_cost_points if invariant else (values[worst_idx] / cost if cost > 0 else None)
    minimum = min(bounds) if all(v is not None for v in bounds) else None
    bound_ratio = minimum / draw_cost_points if minimum is not None else None
    return {
        "ok": True, "min_value": values[worst_idx],
        "lower_bound_value": minimum * point_unit if minimum is not None else None,
        "lower_bound_points": minimum, "lower_bound_recovery": bound_ratio,
        "min_prize_name": worst.get("name", "—"),
        "cost": cost, "recovery": ratio, "rate_invariant": invariant,
        "guarantee_proven": pool_complete is True and bound_ratio is not None and bound_ratio >= 1.0,
        "pool_complete": pool_complete is True,
        "note": "最低模型估值非保底；确定性下界另列，券下界为零。未证明奖池完整且无空奖，不能保证回本",
    }


def scenario_analysis(prizes: list, draw_cost_points: float, point_unit: float,
                      pessimistic_worst_share: float = 0.9,
                      pool_complete: bool = False) -> dict:
    """按奖品估值计算假设情景期望，不表示单次回本概率。"""
    if not prizes or not _finite(draw_cost_points) or draw_cost_points <= 0 \
            or not _finite(point_unit) or point_unit <= 0:
        return {"ok": False, "guarantee_proven": False, "reason": "奖池为空或成本无效"}
    values = [(_points(p) * point_unit if p.get("kind") == "points" and _finite(_points(p))
               else p.get("net_value")) for p in prizes]
    if any(p.get("kind") not in ("points", "cash_coupon", "discount_coupon")
           or p.get("valuation_known") is False for p in prizes) \
            or any(not _finite(v) or v < 0 for v in values):
        return {"ok": False, "guarantee_proven": False, "reason": "存在未知奖品或估值，无法分析情景"}
    if not _finite(pessimistic_worst_share):
        return {"ok": False, "guarantee_proven": False, "reason": "情景权重无效"}
    cost = draw_cost_points * point_unit
    worst_val, best_val = min(values), max(values)
    worst_idx, best_idx = values.index(worst_val), values.index(best_val)
    others = [v for i, v in enumerate(values) if i != worst_idx]
    q = min(max(pessimistic_worst_share, 0.0), 1.0)
    ev_pess = q * worst_val + (1 - q) * sum(others) / len(others) if others else worst_val
    ev_uniform = sum(values) / len(values)
    floor = floor_recovery(prizes, draw_cost_points, point_unit, pool_complete)
    if floor.get("guarantee_proven"):
        verdict = "guaranteed_win"
        note = "已提供完整无空奖证据，所有结果的积分下界均覆盖成本"
    elif best_val < cost:
        verdict = "impossible"
        note = "当前列表最高模型估值 ¥%.2f 低于成本 ¥%.2f；列表内情景期望为负，不是实际收益证明" % (best_val, cost)
    elif ev_pess >= cost:
        verdict = "likely_win"
        note = "悲观假设（%.0f%% 权重最低估值档）期望 ¥%.2f ≥ 成本 ¥%.2f；情景净期望非负，不代表真实回本概率" % (q * 100, ev_pess, cost)
    elif ev_uniform >= cost:
        verdict = "coin_flip"
        note = "均分假设期望 ¥%.2f ≥ 成本 ¥%.2f；悲观情景净期望为负，不代表真实回本概率" % (ev_uniform, cost)
    else:
        verdict = "likely_lose"
        note = "均分假设期望 ¥%.2f < 成本 ¥%.2f；情景净期望为负，不能推断真实亏损概率" % (ev_uniform, cost)
    return {
        "ok": True, "verdict": verdict, "note": note, "cost": cost,
        "guarantee_proven": floor.get("guarantee_proven", False),
        "lower_bound_value": floor.get("lower_bound_value"),
        "worst_value": worst_val, "best_value": best_val,
        "worst_prize": prizes[worst_idx].get("name", "—"),
        "best_prize": prizes[best_idx].get("name", "—"),
        "ev_pessimistic": ev_pess, "ev_uniform": ev_uniform, "ev_best": best_val,
        "net_pessimistic": ev_pess - cost, "net_uniform": ev_uniform - cost,
        "pessimistic_share": q,
        "assumption_note": "官方未公示概率；情景采用模型估值及假设权重，不是实际回本概率或收益边界",
    }


def interval_ev(prizes: list, draw_cost_points: float, point_unit: float) -> dict:
    """保留估值区间字段兼容；不把概率折算误称实际结果边界。"""
    scenario = scenario_analysis(prizes, draw_cost_points, point_unit)
    if not scenario.get("ok"):
        return {"ok": False, "reason": scenario.get("reason")}
    floor = floor_recovery(prizes, draw_cost_points, point_unit)
    return {
        "ok": True, "cost_yuan": scenario["cost"], "cost_points": draw_cost_points,
        "min_value": scenario["worst_value"], "max_value": scenario["best_value"],
        "lower_bound_value": floor.get("lower_bound_value"),
        "worst_net": scenario["worst_value"] - scenario["cost"],
        "best_net": scenario["best_value"] - scenario["cost"],
        "worst_prize": scenario["worst_prize"], "best_prize": scenario["best_prize"],
        "note": "奖品模型估值区间，非实际收益边界；券可能未使用，真实回本概率未知",
    }


def luck_audit(prizes_history: list, draw_cost_points: float, point_unit: float) -> dict:
    """单页奖品记录的样本估值；不推断抽奖总次数、空奖或真实收益。"""
    n = len(prizes_history)
    notes = {
        "n_draws": n, "n_records": n,
        "sample_note": "仅采集的单页奖品记录（最多50条），不是抽奖总次数；未包含未知空奖或全部历史",
        "cost_note": "假设每条记录对应一次抽奖，按当前单次积分价格估算样本成本；非历史实际支出",
    }
    if n == 0:
        return {"ok": False, "reason": "没有奖品记录，无法核对样本", **notes}
    if not _finite(draw_cost_points) or draw_cost_points <= 0 \
            or not _finite(point_unit) or point_unit <= 0:
        return {"ok": False, "reason": "当前抽奖成本未知或无效，无法核对样本", **notes}
    if any(p.get("valuation_known") is False and not p.get("_expired") for p in prizes_history):
        return {"ok": False, "reason": "存在未知历史奖品估值，无法核对样本", **notes}
    values = [0.0 if p.get("_expired") else p.get("net_value") for p in prizes_history]
    if any(not _finite(v) or v < 0 for v in values):
        return {"ok": False, "reason": "样本估值无效", **notes}
    total_value = sum(values)
    total_cost = draw_cost_points * point_unit * n
    net = total_value - total_cost
    coupon_hits = sum(p.get("kind") in ("cash_coupon", "discount_coupon")
                      and not p.get("_expired") for p in prizes_history)
    expired_coupons = sum(bool(p.get("_expired")) for p in prizes_history)
    coupon_rate = coupon_hits / n
    if n < 5:
        verdict, label = "insufficient", "样本太少"
    elif net >= 0 and coupon_rate >= 0.30:
        verdict, label = "ouhuang", "样本高估值"
    elif net >= 0:
        verdict, label = "normal", "样本估值覆盖假设成本"
    else:
        verdict, label = "feiqiu", "样本估值低于假设成本"
    comment = "%d 条记录的样本估值 ¥%.2f，当前价格假设成本 ¥%.2f，估值差额 ¥%.2f；不是实际收益" % (n, total_value, total_cost, net)
    if expired_coupons:
        comment += "；%d 张过期券按零估值" % expired_coupons
    return {
        "ok": True, **notes, "total_value": total_value, "total_cost": total_cost,
        "net": net, "recovery": total_value / total_cost,
        "coupon_hits": coupon_hits, "expired_coupons": expired_coupons,
        "observed_coupon_rate": coupon_rate, "verdict": verdict,
        "label": label, "comment": comment,
    }


def decide(floor: dict, scenario: dict, expiring_points: float,
           available_points: float, draw_cost_points: float,
           eligible: bool = True, ineligible_reason: str = "") -> dict:
    """资格优先；临期仅补充选项，不覆盖未知分析或强迫抽奖。"""
    reasons = []
    max_draws = 0
    if all(_finite(v) for v in (expiring_points, available_points, draw_cost_points)) \
            and expiring_points > 0 and draw_cost_points > 0:
        max_draws = int(max(0, min(expiring_points, available_points)) // draw_cost_points)
        reasons.append("临期积分 %.0f 分；受可用余额限制，最多可用临期部分抽 %d 次。优先比较兑换选项，临期不意味着必须抽奖" % (expiring_points, max_draws))
    if not _finite(draw_cost_points) or draw_cost_points <= 0 \
            or not _finite(available_points) or available_points < 0:
        stance, label = "unknown", "成本或余额未知"
        reasons.append("数据不足，无法给出抽奖建议")
    elif eligible is not True or available_points < draw_cost_points:
        stance, label = "cannot_draw", "暂无法抽奖"
        if available_points < draw_cost_points:
            label += "：积分不足"
            reasons.append("可用积分 %.0f 分不足单次 %.0f 分" % (available_points, draw_cost_points))
        else:
            reasons.append("当前不可参与抽奖%s" % ("（%s）" % ineligible_reason if ineligible_reason else ""))
        if expiring_points > 0:
            reasons.append("建议到商城查看可兑换选项，避免积分过期")
    elif floor.get("ok") and floor.get("guarantee_proven") is True:
        stance, label = "draw", "证据条件下可抽"
        reasons.append("仅在已证明完整无空奖且积分下界覆盖成本的条件下，模型保证不亏")
    elif floor.get("ok") and scenario.get("ok"):
        verdict = scenario.get("verdict")
        reasons.append(scenario.get("note", "情景仅供参考"))
        reasons.append("未证明奖池完整且无空奖，不能保证回本；券价值依赖使用情况")
        if verdict in ("likely_win", "coin_flip", "guaranteed_win"):
            stance, label = "small", "仅情景期望支持少量尝试"
        elif verdict in ("likely_lose", "impossible"):
            stance, label = "avoid", "情景估值不支持，优先兑换"
        else:
            stance, label = "unknown", "数据不足"
    else:
        stance, label = "unknown", "数据不足"
        reasons.append("数据不足，无法给出结论；临期不能补足未知分析")
    result = {"stance": stance, "label": label, "reasons": reasons}
    if _finite(expiring_points) and expiring_points > 0:
        result["max_draws_for_expiring"] = max_draws
    return result
