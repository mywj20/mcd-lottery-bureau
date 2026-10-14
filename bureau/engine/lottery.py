# -*- coding: utf-8 -*-
"""抽奖精算引擎 —— 在"官方不公示概率"的现实约束下，给出可信的结论。

现实约束
--------
麦当劳积分抽奖（query-lottery-info）**不公示中奖概率**，只给奖池清单。
市面上多数工具此时会"假设等概率"或"编个概率"糊弄过去 —— 两者都是错的。

本引擎的处理方式：**不猜概率，只算确定值**

  1. 保底回血率：最差一档奖品的价值 ÷ 单次成本 —— 完全确定，与概率无关
  2. 结果区间：最差/最好单次结果的边界 —— 完全确定
  3. 盈亏平衡概率：反推"券类中奖率要到多少才不亏" —— 可被常识检验的阈值

三个输出没有一个依赖编造的概率，但组合起来足够回答"该不该抽"。
当保底已回本时（现实数据中确实如此），概率甚至不再重要 —— 任何分布下都不亏。
"""

from __future__ import annotations


# ──────────────────────────────────────────────────────────────
# 保底回血：不需要概率的确定值
# ──────────────────────────────────────────────────────────────

def floor_recovery(prizes: list, draw_cost_points: float, point_unit: float) -> dict:
    """保底回血率 = 最差一档奖品的折算价值 ÷ 单次机会成本。

    这是**完全确定**的数字：奖池公示在案，最差结果不会比最差档更差。
    前提：奖池外不存在"谢谢参与"档（官方未公示，报告中如实标注）。

    不变性：当最差档是积分奖时，回血率 = 积分奖积分数 ÷ 单次消耗积分数，
    是纯积分比值 —— 与"1 积分值多少元"的汇率假设无关。
    （实测案例：24 分/抽、保底 30 分 → 125%，换任何汇率都是 125%。）
    """
    cost = float(draw_cost_points) * point_unit
    if not prizes or cost <= 0:
        return {"ok": False, "reason": "奖池为空或成本为零，无法计算保底"}

    worst = min(prizes, key=lambda p: float(p.get("net_value") or 0.0))

    # 积分奖：用纯积分比值计算，保证对汇率假设不变
    if worst.get("kind") == "points" and float(worst.get("points") or 0) > 0 \
            and draw_cost_points > 0:
        ratio = float(worst["points"]) / float(draw_cost_points)
        min_value = float(worst["points"]) * point_unit
    else:
        min_value = float(worst.get("net_value") or 0.0)
        ratio = min_value / cost

    return {
        "ok": True,
        "min_value": min_value,
        "min_prize_name": worst.get("name", "—"),
        "cost": cost,
        "recovery": ratio,
        "rate_invariant": worst.get("kind") == "points",
        "note": "最差一档奖品的价值 ÷ 单次成本；不含概率假设，前提是奖池外无空奖档",
    }


# ──────────────────────────────────────────────────────────────
# 盈亏平衡概率：反推阈值
# ──────────────────────────────────────────────────────────────

def breakeven_probability(prizes: list, draw_cost_points: float, point_unit: float,
                          guaranteed_kind: str = "points") -> dict:
    """反推：非保底类奖品（券类）的合计中奖概率至少要到多少，抽奖才不亏。

    模型：
        设 p = 券类奖品的合计中奖概率（未知），其余概率给积分奖。
        单次 EV = p × E[券类价值] + (1-p) × E[积分价值]
        不亏条件：EV ≥ 成本
        ⇒ p* = (成本 − 积分价值均值) / (券类价值均值 − 积分价值均值)

    若积分奖价值已 ≥ 成本 → p* ≤ 0：任何概率下都不亏（"保底已回本"）。
    若券类均值 ≤ 成本 → p* ≥ 1：数学上不存在不亏的概率，明说。
    """
    cost = float(draw_cost_points) * point_unit

    guaranteed = [p for p in prizes if p.get("kind") == guaranteed_kind]
    others = [p for p in prizes if p.get("kind") != guaranteed_kind]

    if not prizes:
        return {"ok": False, "reason": "奖池为空"}

    g_vals = [float(p.get("net_value") or 0.0) for p in guaranteed]
    o_vals = [float(p.get("net_value") or 0.0) for p in others]

    g_mean = sum(g_vals) / len(g_vals) if g_vals else 0.0
    o_mean = sum(o_vals) / len(o_vals) if o_vals else None

    if not others:
        if g_mean >= cost:
            return {"ok": True, "p_star": 0.0, "verdict": "guaranteed_win",
                    "g_mean": g_mean, "o_mean": None, "cost": cost,
                    "n_guaranteed": len(guaranteed), "n_others": 0,
                    "note": "奖池全部为积分奖且均值已覆盖成本，任何概率下都是回血"}
        return {"ok": True, "p_star": None, "verdict": "impossible",
                "g_mean": g_mean, "o_mean": None, "cost": cost,
                "n_guaranteed": len(guaranteed), "n_others": 0,
                "note": "奖池全部为积分奖且均值低于成本，任何概率下都是净损耗"}

    if o_mean <= g_mean:
        # 券类折算价值还不如积分奖 —— 对这位用户，抽中券反而不如中积分
        return {"ok": True, "p_star": None, "verdict": "others_worse",
                "g_mean": g_mean, "o_mean": o_mean, "cost": cost,
                "n_guaranteed": len(guaranteed), "n_others": len(others),
                "note": "券类奖品的折算价值低于积分奖，中券反而不如中积分"}

    denom = o_mean - g_mean
    p_star = (cost - g_mean) / denom

    if p_star <= 0:
        verdict = "guaranteed_win"
        note = "积分奖本身已回本，任何概率下都不亏"
        p_star = 0.0
    elif p_star >= 1:
        verdict = "impossible"
        note = "券类奖品折算均值低于单次成本，数学上不存在不亏的概率"
    else:
        verdict = "threshold"
        note = "券类合计中奖率需高于此值才值得抽"

    return {
        "ok": True, "p_star": p_star, "verdict": verdict,
        "g_mean": g_mean, "o_mean": o_mean, "cost": cost,
        "n_guaranteed": len(guaranteed), "n_others": len(others),
        "note": note,
    }


# ──────────────────────────────────────────────────────────────
# 结果区间
# ──────────────────────────────────────────────────────────────

def interval_ev(prizes: list, draw_cost_points: float, point_unit: float) -> dict:
    """单次抽奖的收益取值边界（不含概率信息，只表示可能范围）。"""
    if not prizes:
        return {"ok": False, "reason": "奖池为空"}

    cost = float(draw_cost_points) * point_unit
    values = [float(p.get("net_value") or 0.0) for p in prizes]
    lo, hi = min(values), max(values)
    lo_prize = min(prizes, key=lambda p: float(p.get("net_value") or 0.0))
    hi_prize = max(prizes, key=lambda p: float(p.get("net_value") or 0.0))

    return {
        "ok": True,
        "cost_yuan": cost,
        "cost_points": float(draw_cost_points),
        "min_value": lo,
        "max_value": hi,
        "worst_net": lo - cost,
        "best_net": hi - cost,
        "worst_prize": lo_prize.get("name", "—"),
        "best_prize": hi_prize.get("name", "—"),
        "note": "取值边界，非期望值；不含概率信息",
    }


# ──────────────────────────────────────────────────────────────
# 欧皇鉴定：用历史中奖记录做确定性核对
# ──────────────────────────────────────────────────────────────

def luck_audit(prizes_history: list, draw_cost_points: float, point_unit: float) -> dict:
    """欧皇/非酋鉴定：把历史中奖记录折算成钱，与机会成本对账。

    判定（不依赖概率）：
      - 净收益 ≥ 0 且券类命中率 ≥ 30% → 欧皇（高价值档命中频繁）
      - 净收益 ≥ 0 → 欧非守恒（回本，主要靠保底积分）
      - 净收益 < 0 → 非酋（连机会成本都没收回）
      - 样本 < 5 → 样本太少，不出结论
    """
    n = len(prizes_history)
    if n == 0:
        return {"ok": False, "reason": "没有中奖记录，先去抽几发再来鉴定"}

    total_value = sum(float(p.get("net_value") or 0.0) for p in prizes_history)
    total_cost = float(draw_cost_points) * point_unit * n
    net = total_value - total_cost

    coupons = [p for p in prizes_history
               if p.get("kind") != "points" and not p.get("_expired")]
    coupon_hits = len(coupons)
    expired_coupons = sum(1 for p in prizes_history if p.get("_expired"))
    observed_coupon_rate = coupon_hits / n if n > 0 else 0.0

    recovery = total_value / total_cost if total_cost > 0 else 0.0

    if n < 5:
        verdict, label = "insufficient", "样本太少"
        comment = "抽了 %d 次，还看不出手气，至少 5 次再来鉴定" % n
    elif net >= 0 and observed_coupon_rate >= 0.30:
        verdict, label = "ouhuang", "欧皇"
        comment = "%d 次里命中 %d 张有效券，折算净赚 ¥%.2f，手气在线" % (n, coupon_hits, net)
    elif net >= 0:
        verdict, label = "normal", "欧非守恒"
        comment = "回本了（净赚 ¥%.2f），主要靠保底积分档，属于正常波动" % net
    else:
        verdict, label = "feiqiu", "非酋"
        comment = "折算净亏 ¥%.2f，低于机会成本线 —— 建议回归商城兑换" % abs(net)

    if expired_coupons > 0:
        comment += "；另有 %d 张券过期未用，价值已计 ¥0" % expired_coupons

    return {
        "ok": True, "n_draws": n,
        "total_value": total_value, "total_cost": total_cost, "net": net,
        "recovery": recovery, "coupon_hits": coupon_hits,
        "expired_coupons": expired_coupons,
        "observed_coupon_rate": observed_coupon_rate,
        "verdict": verdict, "label": label, "comment": comment,
    }


# ──────────────────────────────────────────────────────────────
# 决策汇总
# ──────────────────────────────────────────────────────────────

def decide(floor: dict, breakeven: dict, expiring_points: float,
           available_points: float, draw_cost_points: float) -> dict:
    """综合三个输入给出最终建议（按优先级）：

      1. 有临期积分 → 止损逻辑（过期归零 vs 抽奖折损）
      2. 保底已回本 → 任何概率下不亏
      3. 盈亏平衡阈值 → 可被常识检验的建议
    """
    reasons = []

    # ── 场景一：临期积分（最高优先级）──
    if expiring_points > 0 and draw_cost_points > 0:
        max_draws = int(expiring_points // draw_cost_points)
        if max_draws > 0:
            reasons.append(
                "您有 %.0f 积分本月将过期，可抽 %d 次。过期 = 100%% 归零，"
                "而抽奖最差也能拿回 %.0f%% 的成本 —— 对临期积分，抽是止损而非消费"
                % (expiring_points, max_draws, floor.get("recovery", 0) * 100)
            )
            return {
                "stance": "must_draw",
                "label": "建议抽掉临期部分",
                "reasons": reasons,
                "max_draws_for_expiring": max_draws,
            }

    # ── 场景二：保底已回本 ──
    if floor.get("ok") and floor.get("recovery", 0) >= 1.0:
        reasons.append(
            "保底回血率 %.0f%%：最差一档（%s）折算 ¥%.2f，已覆盖单次成本 ¥%.2f —— "
            "任何概率分布下都不亏"
            % (floor["recovery"] * 100, floor["min_prize_name"],
               floor["min_value"], floor["cost"])
        )
        reasons.append(
            "⚠ 但请知悉：抽到的是券，真正省钱需要你后续到店消费激活；"
            "对『本来就要吃』的人是福利，对『为券加单』的人才是陷阱"
        )
        return {"stance": "draw", "label": "可以放心抽", "reasons": reasons}

    # ── 场景三：看盈亏平衡 ──
    if breakeven.get("ok"):
        v = breakeven.get("verdict")
        if v == "guaranteed_win":
            reasons.append("积分奖折算价值已回本，任何概率下都不亏")
            return {"stance": "draw", "label": "可以放心抽", "reasons": reasons}
        if v == "impossible":
            reasons.append(
                "券类奖品对您的折算价值（¥%.2f/张）低于单次成本（¥%.2f）—— "
                "数学上不存在『不亏』的概率，除非积分即将过期"
                % (breakeven.get("o_mean") or 0, breakeven.get("cost") or 0)
            )
            return {"stance": "avoid", "label": "不建议抽", "reasons": reasons}
        if v == "threshold":
            p = breakeven["p_star"]
            total = (breakeven.get("n_others", 0) + breakeven.get("n_guaranteed", 0))
            reasons.append(
                "券类奖品合计中奖率需 ≥ %.0f%% 才回本（券类折算均值 ¥%.2f vs 成本 ¥%.2f）"
                % (p * 100, breakeven.get("o_mean") or 0, breakeven.get("cost") or 0)
            )
            if total:
                reasons.append(
                    "奖池共 %d 档，其中券类 %d 档 —— 这个概率门槛是否现实，您可以自己判断"
                    % (total, breakeven.get("n_others", 0))
                )
            stance = "small" if p <= 0.5 else "avoid"
            label = "可小抽怡情" if stance == "small" else "大概率不值"
            return {"stance": stance, "label": label, "reasons": reasons}
        if v == "others_worse":
            reasons.append(
                "券类奖品对您的折算价值（¥%.2f/张）低于积分奖（¥%.2f）—— "
                "奖池里真正对您有价值的主要是积分奖档，其余用不上"
                % (breakeven.get("o_mean") or 0, breakeven.get("g_mean") or 0)
            )
            reasons.append("建议优先走商城兑换；除非积分即将过期，否则不必赌积分奖那一档")
            return {"stance": "avoid", "label": "不建议抽", "reasons": reasons}

    reasons.append("数据不足，无法给出结论")
    return {"stance": "unknown", "label": "数据不足", "reasons": reasons}
