# -*- coding: utf-8 -*-
"""麦麦积分精算局 · 命令行入口

用法：
    python bureau.py demo                     # 零配置演示（内置示例数据）
    python bureau.py check                    # 真实模式：读取你的积分账户与抽奖活动
    python bureau.py luck                     # 欧皇鉴定（读取历史中奖记录）
    python bureau.py card --out luck.svg      # 生成鉴定卡 SVG
    python bureau.py check --json             # 输出结构化 JSON

真实模式前置条件（二选一）：
    方式一：环境变量
        export MCD_MCP_TOKEN=<你的 Token>   （Windows: set MCD_MCP_TOKEN=...）
    方式二：项目根目录创建 .env 文件（推荐，不会被 git 追踪）
        MCD_MCP_TOKEN=<你的 Token>
    Token 申请：https://open.mcd.cn/mcp
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv():
    """从项目根目录的 .env 文件加载环境变量（零依赖的极简实现）。

    只在变量尚未设置时填充，不覆盖已有环境变量。
    .env 已加入 .gitignore，不会被提交。
    """
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()

from bureau import mcp_client, normalize, render
from bureau.engine import lottery as lot_engine
from bureau.engine import value as val_engine


# ══════════════════════════════════════════════════════════
# 核心分析管线
# ══════════════════════════════════════════════════════════

def analyze(account: dict, lottery_raw: dict, orders: dict = None,
            prize_history: list = None, mall_rate: float = None) -> dict:
    """把原始数据加工成完整分析结果（纯计算，可离线复现）。"""
    norm = normalize.normalize_lottery(lottery_raw)
    activity = norm["activity"]
    prizes = norm["prizes"]

    # 积分机会成本锚点：优先用商城实测汇率，否则用保守默认
    point_rate = mall_rate if mall_rate else val_engine.DEFAULT_POINT_VALUE_PER_100
    point_unit = val_engine.point_unit_value(point_rate)

    # 用户画像（订单 → 频率/客单价/消费基线）
    profile = normalize.build_profile(orders or {})

    # 给每个奖品估值
    valued = []
    for p in prizes:
        v = val_engine.value_prize(p, profile, point_rate)
        v["raw"] = p
        valued.append(v)

    draw_points = activity.get("draw_points") or 0

    # 三个引擎计算
    floor = lot_engine.floor_recovery(valued, draw_points, point_unit)
    breakeven = lot_engine.breakeven_probability(valued, draw_points, point_unit)
    interval = lot_engine.interval_ev(valued, draw_points, point_unit)

    # 决策
    decision = lot_engine.decide(
        floor, breakeven,
        expiring_points=account.get("expire_this_month", 0),
        available_points=account.get("available", 0),
        draw_cost_points=draw_points,
    )

    # 欧皇鉴定（有历史记录时）
    audit = None
    if prize_history:
        history_valued = []
        for h in prize_history:
            v = val_engine.value_prize(h, profile, point_rate)
            # 已过期的券：价值归零（中了没用掉 = 没中）
            if h.get("_expired"):
                v["net_value"] = 0.0
                v["_expired"] = True
                v["formula"] = "已过期，价值计 ¥0"
            v["record_time"] = h.get("record_time", "")
            v["status"] = h.get("status", "")
            history_valued.append(v)
        audit = lot_engine.luck_audit(history_valued, draw_points, point_unit)
        audit["activity_name"] = activity.get("name", "")

    return {
        "activity": activity,
        "account": account,
        "prizes": valued,
        "profile": profile,
        "floor": floor,
        "breakeven": breakeven,
        "interval": interval,
        "decision": decision,
        "audit": audit,
        "probability_disclosed": norm["_meta"]["probability_disclosed"],
        "point_rate": point_rate,
        "_meta": norm["_meta"],
    }


# ══════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════

EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


def load_demo_data() -> tuple:
    """加载内置示例数据（零配置、零 Token、零网络）。"""
    base = os.path.abspath(EXAMPLES_DIR)
    def _load(name):
        path = os.path.join(base, name)
        if not os.path.exists(path):
            raise SystemExit("示例数据缺失：%s" % path)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    account_raw = _load("demo-account.json")
    lottery = _load("demo-lottery.json")
    orders_raw = _load("demo-orders.json")
    history_raw = _load("demo-prize-history.json")
    account = normalize.normalize_account(account_raw)
    orders = normalize.normalize_orders(orders_raw)
    history = normalize.normalize_prizes_history(history_raw)
    return account, lottery, orders, history


def load_real_data(client: mcp_client.MCPClient) -> tuple:
    """真实模式：从 MCP 采集数据。"""
    print("→ 采集积分账户...", file=sys.stderr)
    account = normalize.normalize_account(mcp_client.collect_account(client))

    print("→ 采集抽奖活动...", file=sys.stderr)
    lottery = mcp_client.collect_lottery(client)

    orders = None
    try:
        print("→ 采集历史订单（用于画像）...", file=sys.stderr)
        orders = normalize.normalize_orders(mcp_client.collect_orders(client))
    except mcp_client.MCPError as e:
        print("  ⚠ 订单采集失败（%s），将使用默认画像" % e, file=sys.stderr)

    history = []
    try:
        print("→ 采集历史中奖记录...", file=sys.stderr)
        raw = mcp_client.collect_prizes(client)
        history = normalize.normalize_prizes_history(raw)
    except mcp_client.MCPError as e:
        print("  ⚠ 中奖记录采集失败（%s），跳过欧皇鉴定" % e, file=sys.stderr)

    return account, lottery, orders, history


# ══════════════════════════════════════════════════════════
# 子命令
# ══════════════════════════════════════════════════════════

def cmd_demo(args) -> int:
    account, lottery, orders, history = load_demo_data()
    result = analyze(account, lottery, orders, history)
    _output(result, args)
    return 0


def cmd_check(args) -> int:
    client = mcp_client.MCPClient()
    if not client.available():
        print("❌ 未配置 MCD_MCP_TOKEN。\n"
              "   申请：https://open.mcd.cn/mcp\n"
              "   配置：export MCD_MCP_TOKEN=<你的 Token>\n"
              "   或先运行 `python bureau.py demo` 体验零配置演示。", file=sys.stderr)
        return 1
    account, lottery, orders, history = load_real_data(client)
    result = analyze(account, lottery, orders, history)
    _output(result, args)
    return 0


def cmd_luck(args) -> int:
    """欧皇鉴定 —— 单独跑，输出鉴定卡。"""
    if args.demo:
        account, lottery, orders, history = load_demo_data()
    else:
        client = mcp_client.MCPClient()
        if not client.available():
            print("❌ 未配置 MCD_MCP_TOKEN（或用 --demo 跑示例）", file=sys.stderr)
            return 1
        account = normalize.normalize_account(mcp_client.collect_account(client))
        lottery = mcp_client.collect_lottery(client)
        orders = None
        history = normalize.normalize_prizes_history(mcp_client.collect_prizes(client))

    result = analyze(account, lottery, orders, history)
    audit = result.get("audit")
    if not audit or not audit.get("ok"):
        reason = (audit or {}).get("reason", "无中奖记录")
        print("🔬 暂时无法鉴定：%s" % reason)
        print("   （鉴定需要至少 1 条历史中奖记录，抽几次后再来）")
        return 0

    # 终端鉴定
    print()
    print("╔" + "═" * 52 + "╗")
    print("║" + render._pad("  欧皇鉴定 · " + audit["label"], 50) + "  ║")
    print("╚" + "═" * 52 + "╝")
    print("  抽奖次数        %d 次" % audit["n_draws"])
    print("  奖品总价值      ¥%.2f" % audit["total_value"])
    print("  积分机会成本    ¥%.2f" % audit["total_cost"])
    print("  回收率          %.0f%%" % (audit["recovery"] * 100))
    print("  券类命中        %d 次（%.0f%%）" % (audit["coupon_hits"], audit["observed_coupon_rate"] * 100))
    print()
    print("  %s" % audit["comment"])
    print()

    # 生成卡片
    svg = render.render_luck_card(audit, result["activity"].get("name", "麦麦积分抽奖"))
    out = args.out or "luck-card.svg"
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print("  🎴 鉴定卡已生成：%s（可直接截图分享）" % out)
    return 0


def _output(result: dict, args) -> None:
    if getattr(args, "json", False):
        # JSON 输出：去掉原始冗余字段
        slim = dict(result)
        print(json.dumps(slim, ensure_ascii=False, indent=2, default=str))
        return

    if getattr(args, "md", None):
        md = render.render_markdown(result)
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(md)
        print("📄 Markdown 报告已生成：%s" % args.md)

    print(render.render_terminal(result))

    if result.get("audit", {}) and result["audit"].get("ok"):
        svg = render.render_luck_card(
            result["audit"], result["activity"].get("name", "麦麦积分抽奖"))
        out = getattr(args, "card", None) or "luck-card.svg"
        with open(out, "w", encoding="utf-8") as f:
            f.write(svg)
        print("  🎴 欧皇鉴定卡已生成：%s" % out)
        print()


# ══════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="bureau",
        description="麦麦积分精算局 · 抽奖军师 —— 用数学决定你的积分该不该拿去抽奖",
    )
    sub = parser.add_subparsers(dest="command")

    p_demo = sub.add_parser("demo", help="零配置演示（内置示例数据）")
    p_demo.add_argument("--json", action="store_true", help="输出 JSON")
    p_demo.add_argument("--md", help="Markdown 报告输出路径")
    p_demo.add_argument("--card", help="鉴定卡输出路径")
    p_demo.set_defaults(func=cmd_demo)

    p_check = sub.add_parser("check", help="真实模式：读取你的账户")
    p_check.add_argument("--json", action="store_true", help="输出 JSON")
    p_check.add_argument("--md", help="Markdown 报告输出路径")
    p_check.add_argument("--card", help="鉴定卡输出路径")
    p_check.set_defaults(func=cmd_check)

    p_luck = sub.add_parser("luck", help="欧皇鉴定")
    p_luck.add_argument("--demo", action="store_true", help="用示例数据")
    p_luck.add_argument("--out", help="鉴定卡输出路径（默认 luck-card.svg）")
    p_luck.set_defaults(func=cmd_luck)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
