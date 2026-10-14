# -*- coding: utf-8 -*-
"""渲染层 —— 终端报告 / Markdown / 欧皇鉴定卡（SVG）。

传播设计：鉴定卡是给"截图分享"用的 —— 抽奖结果的社交货币。
卡片不吹不黑：赢了给你荣誉，输了给你体面，顺便把数学结论带上。
"""

from __future__ import annotations

import html

# 终端宽度按 CJK 字符算 2 列的常识处理
def _w(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _pad(text: str, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(width - _w(text), 0)
    return (" " * gap + text) if align == "right" else (text + " " * gap)


LINE = "─" * 62


# ══════════════════════════════════════════════════════════
# 终端报告
# ══════════════════════════════════════════════════════════

def render_terminal(result: dict) -> str:
    """完整终端报告。"""
    out = []
    a = result.get("activity", {})
    acct = result.get("account", {})
    prizes = result.get("prizes", [])
    floor = result.get("floor", {})
    be = result.get("breakeven", {})
    rng = result.get("interval", {})
    decision = result.get("decision", {})
    profile = result.get("profile", {})

    out.append("")
    out.append("╔" + "═" * 60 + "╗")
    out.append("║" + _pad("  麦麦积分精算局 · 抽奖军师报告", 58) + "  ║")
    out.append("╚" + "═" * 60 + "╝")
    out.append("")

    # ── 资产概览 ──
    out.append("【积分资产】")
    out.append("  可用积分        %s" % _fmt_int(acct.get("available")))
    if acct.get("expire_this_month"):
        out.append("  ⚠ 本月将过期    %s   ← 止损优先级最高" % _fmt_int(acct.get("expire_this_month")))
    if acct.get("expire_next_month"):
        out.append("  下月将过期      %s" % _fmt_int(acct.get("expire_next_month")))
    if acct.get("expired"):
        out.append("  历史已蒸发      %s   ← 曾经忘记花的" % _fmt_int(acct.get("expired")))
    out.append("")

    # ── 活动结构 ──
    out.append("【抽奖活动】")
    out.append("  %s（%s）" % (a.get("name", "—"), a.get("status", "—")))
    out.append("  单次消耗        %g 积分" % (a.get("draw_points") or 0))
    out.append("  奖池规模        %d 档" % len(prizes))
    if a.get("reason"):
        out.append("  参与状态        %s" % a.get("reason"))
    prob_note = "官方未公示中奖概率 → 本报告使用区间分析，不编造概率"
    out.append("  概率公示        %s" % ("有" if result.get("probability_disclosed") else "无"))
    if not result.get("probability_disclosed"):
        out.append("                  ⓘ %s" % prob_note)
    out.append("")

    # ── 保底回血 ──
    if floor.get("ok"):
        out.append("【保底回血】—— 与概率无关的确定值")
        out.append("  最差一档        %s（折算 ¥%.2f）"
                   % (_truncate(floor.get("min_prize_name", "—"), 16), floor["min_value"]))
        out.append("  单次成本        ¥%.2f（%g 积分机会成本）"
                   % (floor["cost"], a.get("draw_points") or 0))
        bar = _bar(floor["recovery"])
        out.append("  保底回血率      %s %.0f%%" % (bar, floor["recovery"] * 100))
        if floor.get("rate_invariant"):
            out.append("                  ⓘ 最差档为积分奖，此比值与积分汇率假设无关")
        out.append("                  ⓘ 前提：奖池外无『谢谢参与』空奖档（官方未公示）")
        out.append("")

    # ── 盈亏平衡 ──
    if be.get("ok"):
        out.append("【盈亏平衡】—— 反推：券类中奖率要多少才不亏")
        if be["verdict"] == "threshold":
            out.append("  券类均值        ¥%.2f/张（折算后）" % (be["o_mean"] or 0))
            out.append("  积分奖均值      ¥%.2f/抽" % be["g_mean"])
            out.append("  ★ 平衡线        券类合计中奖率 ≥ %.0f%%" % (be["p_star"] * 100))
            out.append("    换言之：你相信券类中奖率超过这个数吗？")
        elif be["verdict"] == "impossible":
            out.append("  ✗ 数学结论      券类折算价值（¥%.2f）低于成本（¥%.2f）" % (be["o_mean"] or 0, be["cost"]))
            out.append("    不存在任何概率分布能让你不亏 —— 除非积分要过期")
        elif be["verdict"] == "guaranteed_win":
            out.append("  ✓ 保底已回本，任何概率下都不亏")
        elif be["verdict"] == "others_worse":
            out.append("  ⓘ 券类折算价值（¥%.2f）低于积分奖（¥%.2f），中券不如中积分"
                       % (be["o_mean"] or 0, be["g_mean"] or 0))
        out.append("")

    # ── 结果区间 ──
    if rng.get("ok"):
        out.append("【单次结果区间】—— 取值边界，非期望值")
        out.append("  最差            %+.2f 元（%s）" % (rng["worst_net"], "只中最低档"))
        out.append("  最好            %+.2f 元（%s）" % (rng["best_net"], "中最高档"))
        out.append("")

    # ── 用户画像 ──
    if profile:
        out.append("【估值口径】—— 券对『你』值多少，取决于你的消费习惯")
        src = profile.get("_source")
        if src == "estimated_from_orders":
            out.append("  点餐频率        %.1f 次/周（由历史订单推算）" % profile["orders_per_week"])
            out.append("  平均客单价      ¥%.1f" % profile["avg_order_value"])
            if profile["orders_per_week"] >= 1.0:
                out.append("  诱导消费扣减    无（高频用户，券用在本来就要下的单上）")
            else:
                out.append("  诱导消费扣减    有（低频用户，部分用券属于『为券加单』）")
        else:
            out.append("  点餐频率        未知 → 按默认画像估算（可在报告末尾修正）")
            out.append("  说明：券的价值 = 面值 × 你会用掉的概率 − 诱导消费扣减")
        out.append("")

    # ── 奖品明细 ──
    if prizes:
        out.append("【奖品折算明细】")
        out.append("  " + _pad("奖品", 26) + _pad("折算价值", 10, "right") + "  说明")
        out.append("  " + "─" * 56)
        for p in prizes:
            name = _truncate(p["name"], 12)
            val = "¥%.2f" % p.get("net_value", 0.0)
            note = p.get("formula", "")
            out.append("  " + _pad(name, 26) + _pad(val, 10, "right") + "  " + _truncate(note, 30))
        out.append("")

    # ── 最终建议 ──
    out.append("╔" + "═" * 60 + "╗")
    label = decision.get("label", "—")
    stance_icon = {"must_draw": "⏰", "draw": "✅", "small": "🎲", "avoid": "🛑"}.get(
        decision.get("stance", ""), "•")
    out.append("║  %s 结论：%s" % (stance_icon, _pad(label, 50)) + "║")
    out.append("╚" + "═" * 60 + "╝")
    for r in decision.get("reasons", []):
        out.append("  · " + r)
    out.append("")

    return "\n".join(out)


# ══════════════════════════════════════════════════════════
# 欧皇鉴定卡（SVG）—— 可截图分享
# ══════════════════════════════════════════════════════════

LUCK_STYLES = {
    "ouhuang":    {"bg1": "#FFF8E1", "bg2": "#FFE082", "accent": "#F57C00", "emoji": "👑"},
    "normal":     {"bg1": "#F5F5F5", "bg2": "#E0E0E0", "accent": "#616161", "emoji": "⚖️"},
    "feiqiu":     {"bg1": "#ECEFF1", "bg2": "#CFD8DC", "accent": "#455A64", "emoji": "🌧️"},
    "insufficient": {"bg1": "#F3E5F5", "bg2": "#E1BEE7", "accent": "#7B1FA2", "emoji": "🔬"},
}


def render_luck_card(audit: dict, activity_name: str = "麦麦积分抽奖") -> str:
    """生成欧皇/非酋鉴定卡 SVG（600×800，适合截图分享）。"""
    style = LUCK_STYLES.get(audit.get("verdict", "insufficient"), LUCK_STYLES["insufficient"])
    label = audit.get("label", "—")
    comment = audit.get("comment", "")
    n = audit.get("n_draws", 0)
    recovery = audit.get("recovery", 0.0)
    total_value = audit.get("total_value", 0.0)
    total_cost = audit.get("total_cost", 0.0)
    coupon_rate = audit.get("observed_coupon_rate", 0.0)
    coupon_hits = audit.get("coupon_hits", 0)
    expired_coupons = audit.get("expired_coupons", 0)
    expired_note = "（%d 张已过期计 ¥0）" % expired_coupons if expired_coupons else ""

    # 回收率进度条（上限 150% 显示）
    bar_max = 1.5
    bar_w = 440
    fill = min(recovery / bar_max, 1.0) * bar_w
    baseline_x = bar_w / bar_max  # 100% 线

    recovery_color = "#2E7D32" if recovery >= 1.0 else ("#F57C00" if recovery >= 0.6 else "#C62828")

    # 点评自动换行（按视觉宽度，每行约 30 个全角字符）
    comment_lines = _svg_text_lines(comment, x=300, start_y=640, max_width=31, line_height=28)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{style['bg1']}"/>
      <stop offset="100%" stop-color="{style['bg2']}"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="4" stdDeviation="8" flood-opacity="0.15"/>
    </filter>
  </defs>

  <rect width="600" height="800" rx="28" fill="url(#bg)"/>

  <!-- 顶部品牌条 -->
  <rect x="0" y="0" width="600" height="88" rx="28" fill="#DA291C"/>
  <rect x="0" y="60" width="600" height="28" fill="#DA291C"/>
  <text x="36" y="54" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="22" font-weight="700" fill="#FFC72C">麦麦积分精算局</text>
  <text x="564" y="54" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="15" fill="#FFFFFF" opacity="0.9">抽奖军师 · 鉴定报告</text>

  <!-- 主判定 -->
  <text x="300" y="210" text-anchor="middle" font-size="96">{style['emoji']}</text>
  <text x="300" y="300" text-anchor="middle" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="56" font-weight="800" fill="{style['accent']}">{html.escape(label)}</text>

  <!-- 数据面板 -->
  <g filter="url(#shadow)">
    <rect x="60" y="340" width="480" height="250" rx="20" fill="#FFFFFF"/>
  </g>

  <text x="92" y="392" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">抽奖次数</text>
  <text x="508" y="392" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">{n} 次</text>

  <text x="92" y="442" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">奖品折算总价值</text>
  <text x="508" y="442" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">¥{total_value:.1f}</text>

  <text x="92" y="492" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">消耗积分机会成本</text>
  <text x="508" y="492" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">¥{total_cost:.1f}</text>

  <!-- 回收率条 -->
  <text x="92" y="536" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">回收率</text>
  <text x="532" y="536" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="22" font-weight="700" fill="{recovery_color}">{recovery * 100:.0f}%</text>
  <rect x="92" y="548" width="{bar_w}" height="18" rx="9" fill="#EEEEEE"/>
  <rect x="92" y="548" width="{fill:.0f}" height="18" rx="9" fill="{recovery_color}"/>
  <line x1="{92 + baseline_x:.0f}" y1="542" x2="{92 + baseline_x:.0f}" y2="572"
        stroke="#9E9E9E" stroke-width="2" stroke-dasharray="4,3"/>
  <text x="{92 + baseline_x:.0f}" y="592" text-anchor="middle"
        font-family="'PingFang SC','Microsoft YaHei',sans-serif" font-size="12" fill="#9E9E9E">100% 回本线</text>

  <!-- 点评（自动换行，最多 3 行） -->
{comment_lines}

  <!-- 页脚 -->
  <line x1="60" y1="700" x2="540" y2="700" stroke="#BDBDBD" stroke-width="1" opacity="0.6"/>
  <text x="60" y="730" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="13" fill="#757575">活动：{html.escape(activity_name)} · 有效券 {coupon_hits} 张{expired_note}</text>
  <text x="60" y="756" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="12" fill="#9E9E9E">基于麦当劳 MCP 数据 · 估值口径：面值×使用概率−诱导消费 · 非官方产品</text>
</svg>'''
    return svg


# ══════════════════════════════════════════════════════════
# Markdown 报告（用于分享/存档）
# ══════════════════════════════════════════════════════════

def render_markdown(result: dict) -> str:
    """把分析结果渲染成 Markdown 报告。"""
    a = result.get("activity", {})
    acct = result.get("account", {})
    prizes = result.get("prizes", [])
    floor = result.get("floor", {})
    be = result.get("breakeven", {})
    rng = result.get("interval", {})
    decision = result.get("decision", {})
    profile = result.get("profile", {})
    audit = result.get("audit")

    L = []
    L.append("# 麦麦积分精算报告")
    L.append("")
    L.append("> 由 **麦麦积分精算局 · 抽奖军师** 生成｜基于麦当劳中国 MCP 数据")
    L.append("")

    # 结论前置
    L.append("## 结论")
    L.append("")
    L.append("**%s**" % decision.get("label", "—"))
    L.append("")
    for r in decision.get("reasons", []):
        L.append("- %s" % r)
    L.append("")

    # 资产
    L.append("## 积分资产")
    L.append("")
    L.append("| 项目 | 数值 |")
    L.append("| --- | ---: |")
    L.append("| 可用积分 | %s |" % _fmt_int(acct.get("available")))
    if acct.get("expire_this_month"):
        L.append("| ⚠️ 本月将过期 | %s |" % _fmt_int(acct.get("expire_this_month")))
    if acct.get("expire_next_month"):
        L.append("| 下月将过期 | %s |" % _fmt_int(acct.get("expire_next_month")))
    if acct.get("expired"):
        L.append("| 历史已蒸发 | %s |" % _fmt_int(acct.get("expired")))
    L.append("")

    # 活动
    L.append("## 抽奖活动")
    L.append("")
    L.append("- 活动：%s（%s）" % (a.get("name", "—"), a.get("status", "—")))
    L.append("- 单次消耗：**%g 积分**" % (a.get("draw_points") or 0))
    L.append("- 奖池规模：%d 档" % len(prizes))
    L.append("- 概率公示：**无**（官方未公示 → 本报告使用确定值模型，不编造概率）")
    L.append("")

    # 保底
    if floor.get("ok"):
        L.append("## 保底回血（与概率无关的确定值）")
        L.append("")
        L.append("最差一档 **%s** 折算 ¥%.2f，单次成本 ¥%.2f，**保底回血率 %.0f%%**"
                 % (floor.get("min_prize_name", "—"), floor["min_value"],
                    floor["cost"], floor["recovery"] * 100))
        L.append("")
        if floor.get("rate_invariant"):
            L.append("> ⓘ 最差档为积分奖，此比值与积分汇率假设无关。")
            L.append("")
        L.append("> ⓘ 前提：奖池外无『谢谢参与』空奖档（官方未公示）。")
        L.append("")

    # 盈亏平衡
    if be.get("ok"):
        L.append("## 盈亏平衡")
        L.append("")
        if be["verdict"] == "threshold":
            L.append("**券类合计中奖率需 ≥ %.0f%% 才回本**（券类折算均值 ¥%.2f vs 成本 ¥%.2f）"
                     % (be["p_star"] * 100, be["o_mean"] or 0, be["cost"]))
        elif be["verdict"] == "guaranteed_win":
            L.append("✅ 保底已回本，任何概率下都不亏。")
        elif be["verdict"] == "impossible":
            L.append("❌ 券类折算价值低于成本，数学上不存在不亏的概率。")
        elif be["verdict"] == "others_worse":
            L.append("ⓘ 券类折算价值低于积分奖，中券不如中积分。")
        L.append("")

    # 区间
    if rng.get("ok"):
        L.append("## 单次结果区间")
        L.append("")
        L.append("- 最差：%+.2f 元（%s）" % (rng["worst_net"], rng.get("worst_prize", "—")))
        L.append("- 最好：%+.2f 元（%s）" % (rng["best_net"], rng.get("best_prize", "—")))
        L.append("")

    # 画像
    if profile:
        L.append("## 估值口径")
        L.append("")
        if profile.get("_source") == "estimated_from_orders":
            L.append("点餐频率 %.1f 次/周、平均客单价 ¥%.1f（由历史订单推算）"
                     % (profile["orders_per_week"], profile["avg_order_value"]))
        else:
            L.append("点餐频率未知，按默认画像估算（1 次/周、客单价 ¥35）")
        L.append("")
        L.append("> 券的价值 = 面值 × 使用概率 − 诱导消费扣减。")
        L.append("")

    # 奖品明细
    if prizes:
        L.append("## 奖品折算明细")
        L.append("")
        L.append("| 奖品 | 折算价值 | 推导 |")
        L.append("| --- | ---: | --- |")
        for p in prizes:
            L.append("| %s | ¥%.2f | %s |"
                     % (p["name"], p.get("net_value", 0.0), p.get("formula", "")))
        L.append("")

    # 鉴定
    if audit and audit.get("ok"):
        L.append("## 欧皇鉴定")
        L.append("")
        L.append("**%s**（%d 次抽奖，回收率 %.0f%%）" % (audit["label"], audit["n_draws"], audit["recovery"] * 100))
        L.append("")
        L.append("> %s" % audit["comment"])
        L.append("")

    L.append("---")
    L.append("")
    L.append("*本项目为麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。*")
    L.append("*估值含假设，以官方渠道信息为准。*")
    L.append("")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════

def _svg_text_lines(text: str, x: int, start_y: int, max_width: int,
                    line_height: int, font_size: int = 16, fill: str = "#424242",
                    max_lines: int = 3) -> str:
    """把长文本按视觉宽度折行，生成居中排布的 SVG <text> 元素。

    中文字符按 1 个全角单位算，ASCII 按 0.5 算；max_width 为全角字符数。
    超出行数上限时末行加省略号。
    """
    lines, current, width = [], "", 0.0
    for ch in text:
        cw = 1.0 if ord(ch) > 0x2E80 else 0.5
        if width + cw > max_width and current:
            lines.append(current)
            current, width = ch, cw
        else:
            current += ch
            width += cw
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"

    out = []
    for i, line in enumerate(lines):
        y = start_y + i * line_height
        out.append(
            '  <text x="%d" y="%d" text-anchor="middle" '
            'font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif" '
            'font-size="%d" fill="%s">%s</text>'
            % (x, y, font_size, fill, html.escape(line))
        )
    return "\n".join(out)


def _bar(ratio: float, width: int = 20) -> str:
    """文本进度条。"""
    filled = max(0, min(int(round(ratio * width)), width))
    return "█" * filled + "░" * (width - filled)


def _fmt_int(v) -> str:
    try:
        return "{:,.0f}".format(float(v))
    except (TypeError, ValueError):
        return "—"


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    if _w(text) <= limit * 2:
        return text
    out, w = "", 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2E80 else 1
        if w + cw > limit * 2 - 2:
            break
        out += ch
        w += cw
    return out + "…"
