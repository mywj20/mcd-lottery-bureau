# -*- coding: utf-8 -*-
"""麦麦积分精算局 —— 基于麦当劳 MCP 的积分抽奖决策引擎。

模块结构：
    mcp_client   零依赖 MCP 客户端（唯一触网模块）
    normalize    MCP 原始返回 → 可计算结构
    engine.value 奖品估值模型（使用概率折价 + 诱导消费扣减）
    engine.lottery 抽奖精算（保底回血 / 情景分析 / 欧皇鉴定）
    render       终端报告 / 鉴定卡 SVG

设计原则：网络层与计算层解耦，全部计算可离线复现。
"""

import os


def _load_dotenv():
    """从项目根目录的 .env 加载环境变量（零依赖极简实现）。

    放在包初始化里，保证 `import bureau` 与 `python bureau.py` 两种
    使用方式都能生效。只在变量未设置时填充，不覆盖已有环境变量。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
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

__version__ = "1.0.0"
