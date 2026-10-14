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
    sc = result.get("scenario", {})
    rng = result.get("interval", {})
    decision = result.get("decision", {})
    profile = result.get("profile", {})

    out.append("")
    out.append("╔" + "═" * 60 + "╗")
    out.append("║" + _pad("  麦麦积分精算局 · 抽奖军师报告", 58) + "  ║")
    out.append("╚" + "═" * 60 + "╝")
    out.append("")

    out.append("来源：%s" % result.get("source_label", "来源未标注"))
    out.append("【结论】%s" % decision.get("label", "数据不足"))
    for reason in decision.get("reasons", []):
        out.append("  · " + reason)
    out.append("")

    # ── 资产概览 ──
    out.append("【积分资产】")
    out.append("  可用积分        %s" % _fmt_int(acct.get("available")))
    if acct.get("expire_this_month"):
        out.append("  ⚠ 本月将过期    %s   ← 优先比较官方兑换，非必须抽奖" % _fmt_int(acct.get("expire_this_month")))
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
        out.append("【最低档模型估值】—— 非实际收益保底")
        out.append("  最差一档        %s（折算 ¥%.2f）"
                   % (_truncate(floor.get("min_prize_name", "—"), 16), floor["min_value"]))
        out.append("  单次成本        ¥%.2f（%g 积分机会成本）"
                   % (floor["cost"], a.get("draw_points") or 0))
        bar = _bar(floor["recovery"])
        out.append("  模型估值回收率  %s %.0f%%" % (bar, floor["recovery"] * 100))
        if floor.get("rate_invariant"):
            out.append("                  ⓘ 最差档为积分奖，此比值与积分汇率假设无关")
        out.append("                  ⓘ 仅列出奖项；空奖、用券失败与参照价变化均未排除，不能保证回本")
        out.append("")

    # ── 情景分析 ──
    if sc.get("ok"):
        out.append("【情景分析】—— 官方未公示概率，用透明假设替代")
        verdict_icon = {
            "guaranteed_win": "✓", "likely_win": "✓",
            "coin_flip": "⚖", "likely_lose": "✗", "impossible": "✗",
        }.get(sc.get("verdict", ""), "•")
        out.append("  %s %s" % (verdict_icon, sc.get("note", "")))
        out.append("  悲观情景(90%%最低档) 期望 %+.2f 元" % sc.get("net_pessimistic", 0))
        out.append("  均分情景(等概率)    期望 %+.2f 元" % sc.get("net_uniform", 0))
        out.append("                  ⓘ %s" % sc.get("assumption_note", ""))
        out.append("")

    # ── 结果区间 ──
    if rng.get("ok"):
        out.append("【列出奖项的单次模型估值区间】—— 非实际收益边界")
        out.append("  最差            %+.2f 元（%s）" % (rng["worst_net"], rng.get("worst_prize", "只中最低档")))
        out.append("  最好            %+.2f 元（%s）" % (rng["best_net"], rng.get("best_prize", "中最高档")))
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
            out.append("  点餐频率        未知 → 默认假设 1 次/周、客单 ¥35（非个性化验证）")
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

    out.append("积分折算率：¥%.2f/100 分（默认或用户指定假设，非现金）。" % result.get("point_rate", 0))
    out.append("券有效期与折扣参照价缺失时使用标注的假设；不代表当前门店价格。")
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
    label_size = min(56, int(480 / max(_w(label) / 2, 1)))
    n = audit.get("n_records", audit.get("n_draws", 0))
    recovery = audit.get("recovery", 0.0)
    total_value = audit.get("total_value", 0.0)
    total_cost = audit.get("total_cost", 0.0)
    coupon_rate = audit.get("observed_coupon_rate", 0.0)
    coupon_hits = audit.get("coupon_hits", 0)
    expired_coupons = audit.get("expired_coupons", 0)
    expired_note = "（%d 张已过期计 ¥0）" % expired_coupons if expired_coupons else ""
    source = audit.get("source_label", "来源未标注")
    period = audit.get("period", "记录期间未知")
    profile_note = audit.get("profile_note", "画像来源未知")

    # 回收率进度条（上限 150% 显示）
    bar_max = 1.5
    bar_w = 440
    fill = min(recovery / bar_max, 1.0) * bar_w
    baseline_x = bar_w / bar_max  # 100% 线

    recovery_color = "#2E7D32" if recovery >= 1.0 else ("#F57C00" if recovery >= 0.6 else "#C62828")

    comment = "样本折算差额 %+.2f 元，不是实际收益。" % (total_value - total_cost)
    if expired_coupons:
        comment += "%d 张过期券估值为零。" % expired_coupons
    comment_lines = _svg_text_lines(comment, x=300, start_y=631, max_width=31, line_height=25,
                                    max_lines=2)

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

  <text x="300" y="119" text-anchor="middle" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="16" font-weight="700" fill="#616161">{html.escape(source)}</text>

  <!-- 主判定 -->
  <text x="300" y="210" text-anchor="middle" font-size="96">{style['emoji']}</text>
  <text x="300" y="300" text-anchor="middle" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="{label_size}" font-weight="800" fill="{style['accent']}">{html.escape(label)}</text>

  <!-- 数据面板 -->
  <g filter="url(#shadow)">
    <rect x="60" y="340" width="480" height="250" rx="20" fill="#FFFFFF"/>
  </g>

  <text x="92" y="392" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">样本奖品记录（非抽奖次数）</text>
  <text x="508" y="392" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">{n} 条</text>

  <text x="92" y="442" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">奖品模型估值合计</text>
  <text x="508" y="442" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">¥{total_value:.1f}</text>

  <text x="92" y="492" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">按当前价格估算样本成本</text>
  <text x="508" y="492" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="26" font-weight="700" fill="#212121">¥{total_cost:.1f}</text>

  <!-- 回收率条 -->
  <text x="92" y="536" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="17" fill="#757575">样本估算回收率（非现金收益）</text>
  <text x="532" y="536" text-anchor="end" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="22" font-weight="700" fill="{recovery_color}">{recovery * 100:.0f}%</text>
  <rect x="92" y="548" width="{bar_w}" height="18" rx="9" fill="#EEEEEE"/>
  <rect x="92" y="548" width="{fill:.0f}" height="18" rx="9" fill="{recovery_color}"/>
  <line x1="{92 + baseline_x:.0f}" y1="542" x2="{92 + baseline_x:.0f}" y2="572"
        stroke="#9E9E9E" stroke-width="2" stroke-dasharray="4,3"/>
  <text x="{92 + baseline_x:.0f}" y="592" text-anchor="middle"
        font-family="'PingFang SC','Microsoft YaHei',sans-serif" font-size="12" fill="#616161">100% 估值成本比</text>

  <!-- 点评（自动换行，最多 3 行） -->
{comment_lines}

  <!-- 页脚 -->
  <line x1="60" y1="675" x2="540" y2="675" stroke="#BDBDBD" stroke-width="1" opacity="0.6"/>
  <text x="60" y="699" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="13" font-weight="700" fill="#616161">{html.escape(source)} · {html.escape(_truncate(profile_note, 14))}</text>
  <text x="60" y="721" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="12" fill="#616161">期间：{html.escape(period)} · 当前单抽价估算，非真实历史成本</text>
  <text x="60" y="743" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="12" fill="#616161">仅采集单页最多50条奖品，非全量历史；不推断中奖概率</text>
  <text x="60" y="765" font-family="'PingFang SC','Microsoft YaHei',sans-serif"
        font-size="12" fill="#616161">活动：{html.escape(_truncate(activity_name, 16))} · 券估值含使用假设 · 非官方产品</text>
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
    rng = result.get("interval", {})
    decision = result.get("decision", {})
    profile = result.get("profile", {})
    audit = result.get("audit")

    L = []
    L.append("# 麦麦积分精算报告")
    L.append("")
    L.append("> 由 **麦麦积分精算局 · 抽奖军师** 生成｜%s" % result.get("source_label", "来源未标注"))
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
    L.append("- 概率公示：**%s**；情景是假设，不是实际中奖概率。" % ("有" if result.get("probability_disclosed") else "无"))
    L.append("")

    if floor.get("ok"):
        L.append("## 最低档模型估值（非实际收益保底）")
        L.append("")
        L.append("列出奖项中最低估值 **%s** 为 ¥%.2f，单次假设成本 ¥%.2f，**模型估值回收率 %.0f%%**。"
                 % (floor.get("min_prize_name", "—"), floor["min_value"],
                    floor["cost"], floor["recovery"] * 100))
        L.append("")
        if floor.get("rate_invariant"):
            L.append("> 该项为积分奖，积分比与折算率无关；不证明实际奖池完整。")
            L.append("")
        L.append("> 券未使用时节省可为零；空奖未排除，不能保证回本。")
        L.append("")

    # 情景分析
    sc = result.get("scenario", {})
    if sc.get("ok"):
        L.append("## 情景分析")
        L.append("")
        L.append("**%s**" % sc.get("note", ""))
        L.append("")
        L.append("| 情景 | 假设 | 单次模型净期望（已扣成本） |")
        L.append("| --- | --- | ---: |")
        L.append("| 悲观 | 90%% 概率中最低档 | %+.2f 元 |" % sc.get("net_pessimistic", 0))
        L.append("| 均分 | 所有档位等概率（假想） | %+.2f 元 |" % sc.get("net_uniform", 0))
        L.append("| 模型回本线 | 净收益为零 | 0.00 元 |")
        L.append("")
        L.append("> %s" % sc.get("assumption_note", ""))
        L.append("")

    # 区间
    if rng.get("ok"):
        L.append("## 列出奖项的单次模型估值区间（非实际收益边界）")
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
        L.append("> 券的模型估值 = 可节省金额 × 使用概率 − 诱导消费扣减，不是已实现收益。")
        L.append("> 积分折算率 ¥%.2f/100 分为默认或指定假设，非现金兑付价；缺少有效期时假设 7 天，折扣餐品采用静态参照价，非实时门店价格。" % result.get("point_rate", 0))
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
        L.append("**%s**（%d 条奖品记录，样本估算回收率 %.0f%%，非现金收益）"
                 % (audit["label"], audit.get("n_records", audit["n_draws"]), audit["recovery"] * 100))
        L.append("")
        L.append("- 来源：%s；期间：%s；%s。" % (audit.get("source_label", "来源未标注"),
                 audit.get("period", "记录期间未知"), audit.get("profile_note", "画像来源未知")))
        L.append("- %s" % audit.get("sample_note", "仅奖品记录，非全量抽奖历史。"))
        L.append("- %s" % audit.get("cost_note", "历史成本按当前单抽价估算。"))
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
