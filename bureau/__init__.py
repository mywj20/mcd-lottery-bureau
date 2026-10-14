# -*- coding: utf-8 -*-
"""麦麦积分精算局 —— 基于麦当劳 MCP 的积分抽奖决策引擎。

模块结构：
    mcp_client   零依赖 MCP 客户端（唯一触网模块）
    normalize    MCP 原始返回 → 可计算结构
    engine.value 奖品估值模型（使用概率折价 + 诱导消费扣减）
    engine.lottery 抽奖精算（区间 EV / 盈亏平衡 / 保底回血 / 欧皇鉴定）
    render       终端报告 / 鉴定卡 SVG

设计原则：网络层与计算层解耦，全部计算可离线复现。
"""

__version__ = "1.0.0"
