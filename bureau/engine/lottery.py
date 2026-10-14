# -*- coding: utf-8 -*-
"""抽奖精算引擎 —— 在"官方不公示概率"的现实约束下，给出可信的结论。

现实约束
--------
麦当劳积分抽奖（query-lottery-info）**不公示中奖概率**，只给奖池清单。
市面上多数工具此时会"假设等概率"或"编个概率"糊弄过去 —— 两者都是错的。

本引擎的处理方式：**不猜概率，只算确定值**

  1. 保底回血率：最差一档奖品的价值 ÷ 单次成本 —— 完全确定，与概率无关
  2. 结果区间：最差/最好单次结果的边界 —— 完全确定
  3. 情景分析：悲观/均分两种透明假设下的期望，替代"编造概率"

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
# 情景分析：不猜概率，算三种情景下的结果
# ──────────────────────────────────────────────────────────────

def scenario_analysis(prizes: list, draw_cost_points: float, point_unit: float,
                      pessimistic_worst_share: float = 0.9) -> dict:
    """三种明确标注假设的情景分析，替代"编造概率"。

    数学边界（严格）：
        EV ∈ [最差档价值, 最好档价值] —— 任何概率分布的结果都在此区间内。

    情景（透明假设，供决策参考）：
        ① 悲观情景：90% 概率中最低档，其余 10% 均分给其他档
           （不是数学下界，而是一个"相当倒霉"的可信场景）
        ② 均分情景：所有档位等概率（官方未公示概率，此为假想参照）
        ③ 最好情况：每次都是最高档（数学上界）

    判定逻辑（按可信度排序）：
        - 最差档价值 ≥ 成本 → 稳赚不亏（严格结论，任何分布）
        - 悲观情景 EV ≥ 成本 → 大概率回本（即使 90% 中最低档也不亏）
        - 均分情景 EV ≥ 成本 → 看运气（需要中奖分布不至于太差）
        - 最好档价值 < 成本 → 不可能回本（严格结论）
    """
    cost = float(draw_cost_points) * point_unit
    if not prizes or cost <= 0:
        return {"ok": False, "reason": "奖池为空或成本为零"}

    values = [float(p.get("net_value") or 0.0) for p in prizes]
    worst_val, best_val = min(values), max(values)
    worst_prize = min(prizes, key=lambda p: float(p.get("net_value") or 0.0))
    best_prize = max(prizes, key=lambda p: float(p.get("net_value") or 0.0))

    # ① 悲观情景：90% 最低档 + 10% 均分其余
    worst_idx = values.index(worst_val)
    others = [v for i, v in enumerate(values) if i != worst_idx]
    if others:
        q = min(max(pessimistic_worst_share, 0.0), 1.0)
        ev_pess = q * worst_val + (1 - q) * (sum(others) / len(others))
    else:
        ev_pess = worst_val

    # ② 均分情景
    ev_uniform = sum(values) / len(values)

    # ③ 最好情况
    ev_best = best_val

    # 判定
    if worst_val >= cost:
        verdict = "guaranteed_win"
        note = "最差档（%s，¥%.2f）已覆盖成本（¥%.2f）—— 任何概率分布下都不亏" % (
            worst_prize.get("name", "—"), worst_val, cost)
    elif best_val < cost:
        verdict = "impossible"
        note = "最好档（%s，¥%.2f）都低于成本（¥%.2f）—— 任何概率分布下都是净亏" % (
            best_prize.get("name", "—"), best_val, cost)
    elif ev_pess >= cost:
        verdict = "likely_win"
        note = ("即使 90%% 概率都中最低档（%s），期望值 ¥%.2f 仍高于成本 ¥%.2f —— "
                "只要中奖分布不是极端恶劣就回本" % (worst_prize.get("name", "—"), ev_pess, cost))
    elif ev_uniform >= cost:
        verdict = "coin_flip"
        note = ("需要运气不至于太差：均分假设下期望 ¥%.2f ≥ 成本 ¥%.2f，"
                "但若概率明显偏向低档就会亏" % (ev_uniform, cost))
    else:
        verdict = "likely_lose"
        note = ("即使均分假设下期望值 ¥%.2f 也低于成本 ¥%.2f —— "
                "除非大奖概率远高于小奖，否则亏" % (ev_uniform, cost))

    return {
        "ok": True,
        "verdict": verdict, "note": note,
        "cost": cost,
        "worst_value": worst_val, "best_value": best_val,
        "worst_prize": worst_prize.get("name", "—"),
        "best_prize": best_prize.get("name", "—"),
        "ev_pessimistic": ev_pess,
        "ev_uniform": ev_uniform,
        "ev_best": ev_best,
        "net_pessimistic": ev_pess - cost,
        "net_uniform": ev_uniform - cost,
        "pessimistic_share": pessimistic_worst_share,
        "assumption_note": "官方未公示概率；悲观/均分情景为透明假设，非官方数据",
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

def decide(floor: dict, scenario: dict, expiring_points: float,
           available_points: float, draw_cost_points: float,
           eligible: bool = True, ineligible_reason: str = "") -> dict:
    """综合输入给出最终建议（按优先级）：

      0. 参与资格检查（积分不足等）→ 直接给出可执行的结论
      1. 有临期积分 → 止损逻辑（过期归零 vs 抽奖折损）
      2. 保底已回本（最差档 ≥ 成本）→ 任何概率下不亏
      3. 情景分析 → 按可信度分级的建议
    """
    reasons = []

    # ── 场景零：参与资格（最高优先级 —— 不能抽就没什么可分析的）──
    if not eligible:
        if draw_cost_points > 0 and available_points < draw_cost_points:
            reasons.append(
                "您当前可用积分 %.0f 分，不足单次抽奖所需的 %.0f 分 —— 无法参与抽奖"
                % (available_points, draw_cost_points)
            )
            if expiring_points > 0:
                reasons.append(
                    "⚠ 另有 %.0f 积分本月将过期：请在过期前到麦麦商城兑换"
                    "（积分不足时抽奖不是选项，兑换是）" % expiring_points
                )
            return {"stance": "cannot_draw", "label": "暂无法抽奖：积分不足",
                    "reasons": reasons}
        reasons.append("当前不可参与抽奖%s" % ("（%s）" % ineligible_reason if ineligible_reason else ""))
        if expiring_points > 0:
            reasons.append("建议在积分过期前到麦麦商城兑换，避免归零")
        return {"stance": "cannot_draw", "label": "暂无法抽奖", "reasons": reasons}

    # ── 场景一：临期积分 ──
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

    # ── 场景二：保底已回本（最差档 ≥ 成本，严格结论）──
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

    # ── 场景三：情景分析 ──
    if scenario.get("ok"):
        v = scenario.get("verdict")
        if v == "likely_win":
            reasons.append(scenario["note"])
            reasons.append(
                "⚠ 提醒：这是期望口径。单次结果仍可能只中最低档（%s，¥%.2f），"
                "建议只投入计划内积分的部分" % (scenario.get("worst_prize", "—"),
                                        scenario.get("worst_value", 0))
            )
            return {"stance": "small", "label": "可以小抽，见好就收", "reasons": reasons}
        if v == "coin_flip":
            reasons.append(scenario["note"])
            reasons.append(
                "参考：悲观情景（90%% 最低档）期望 ¥%.2f，均分情景期望 ¥%.2f，成本 ¥%.2f"
                % (scenario.get("ev_pessimistic", 0), scenario.get("ev_uniform", 0),
                   scenario.get("cost", 0))
            )
            return {"stance": "small", "label": "看运气，建议浅尝辄止", "reasons": reasons}
        if v == "likely_lose":
            reasons.append(scenario["note"])
            reasons.append(
                "建议优先到麦麦商城兑换 —— 除非积分即将过期（那时抽奖是止损）"
            )
            return {"stance": "avoid", "label": "大概率不值，建议兑换", "reasons": reasons}
        if v == "impossible":
            reasons.append(scenario["note"])
            reasons.append("建议到麦麦商城兑换，或等积分商城上新")
            return {"stance": "avoid", "label": "不建议抽", "reasons": reasons}

    reasons.append("数据不足，无法给出结论")
    return {"stance": "unknown", "label": "数据不足", "reasons": reasons}
