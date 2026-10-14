# MCP 集成说明

## 连接与配置

| 项目 | 值 |
|---|---|
| Server | 麦当劳中国 MCP Server |
| 默认地址 | `https://mcp.mcd.cn` |
| 请求 | HTTP POST，JSON-RPC `tools/call` |
| 鉴权 | `Authorization: Bearer <MCP Token>` |
| 响应 | 客户端处理 JSON 与 SSE 包裹的 JSON |
| Token 申请 | https://open.mcd.cn/mcp |
| 官方仓库 | https://github.com/M-China/mcd-mcp-server |

本地 CLI 使用 Python 标准库 HTTP 客户端，不依赖宿主提供的 MCP 工具连接。需为 CLI 进程单独设置 `MCD_MCP_TOKEN`，或由用户在项目根目录本地 `.env` 中配置；宿主 MCP Token 不会自动传给 CLI。不要提交、输出或分享 Token。宿主安装与绝对路径调用见 [SKILL.md](SKILL.md)。

## 四个只读业务工具：串行，不并行

`python bureau.py check` 的正常采集顺序如下。四次指业务工具调用，不应理解为包括协议协商在内的全部 HTTP 请求数量。

| 顺序 | 工具 | 作用 |
|---|---|---|
| 1 | `query-my-account` | 可用积分与临期积分 |
| 2 | `query-lottery-info` | 活动、单次积分费用、奖品列表与参与资格 |
| 3 | `order-list` | 用于估计点餐频率与客单价 |
| 4 | `query-my-prizes` | 单页奖品记录，用于样本分析 |

默认路线是让 CLI 一次完成采集，不先由宿主取四份数据再重复运行 CLI。采集过程中状态可能改变，四份数据不是账户的原子快照；报告与存档都不保证执行时资格仍有效。

```text
check
  query-my-account
  query-lottery-info
  order-list
  query-my-prizes（pageSize=50，单页）
  normalize.py：字段与奖品归一化
  engine/：本地模型估值与假设情景
  render.py：终端、Markdown、SVG
```

订单采集失败时披露默认画像，奖品记录失败时跳过历史分析。资格、余额或活动读取失败不能伪造结果。`demo` 使用本地示例，不调用这四个工具；`luck` 是独立的历史卡片入口，不应作为 `check` 后的默认重复步骤。

## 字段映射与数据边界

### `query-my-account`

| 原始字段 | 归一化字段 | 说明 |
|---|---|---|
| `availablePoint` | `account.available` | 可用积分，数值化后展示 |
| `currentMouthExpirePoint` | `account.expire_this_month` | 本月到期积分；保留接口中的 `Mouth` 拼写 |
| `nextMouthExpirePoint` | `account.expire_next_month` | 下月到期积分 |
| `expiredPoint` | `account.expired` | 已到期积分记录 |

临期提示不等于抽奖指令。先比较官方兑换与已有消费需求；不能断言抽奖优于到期或必有奖品。

### `query-lottery-info`

| 原始字段 | 归一化字段 | 说明 |
|---|---|---|
| `drawPoint` | `activity.draw_points` | 返回可能为字符串，例如 `"24"`，需转数值 |
| `prizes[]` | 奖品结构 | 解析立减券、折扣券、积分等奖品名 |
| `drawDecision.resourceEligible` | `activity.eligible` | 参与资格，不用余额替代；未知不视为可参与 |
| `drawDecision.reason` | `activity.reason` | 展示不可参与原因 |
| `activityName` / `activityStatusText` | `activity.name/status` | 活动与状态 |

已存档样例未给出中奖概率。奖品列表既不证明概率分布，也**不保证没有空奖或列表之外结果**。最低列示奖品的模型估值不能成为兑现保证；`guarantee_proven` 默认 `false`。

### `order-list`

| 原始字段 | 模型字段 | 说明 |
|---|---|---|
| `list[].totalAmount` | `avg_order_value` | 样本客单价，用于诱导消费扣减 |
| `list[].orderTime` | `orders_per_week` | 样本消费频率，用于模型使用概率 |

订单画像是有限样本估计，不是已验证的用券概率。默认画像、有效期假设、频率模型与扣减规则均影响结果；即使输入是真实订单，估值仍含模型假设。

### `query-my-prizes`

| 原始字段 | 用途 |
|---|---|
| `prizes[].name` | 解析并估值历史奖品 |
| `prizes[].statusText` | 含“过期”时券估值计零 |
| `prizes[].recordTime` | 记录时间 |
| `pageSize` | 当前请求为 50，单页最多 50 条奖品记录 |

当前采集不自动翻页，不能声称覆盖全部历史。**奖品记录数不是抽奖次数**：未中奖、空奖或其他活动记录可能不在样本中。券类记录占比仅描述返回样本，不是实际中奖率。

历史成本按“返回奖品记录条数 × 当前单次积分费用 × 默认或指定积分率”估算，不是历史实际投入。未核实各记录的活动、费用与兑现状态时，估值减成本只能称模型差额，不能称真实净收益。

## 估值与情景口径

| 项目 | 输入与假设 | 不能推导什么 |
|---|---|---|
| 积分机会成本 | 默认 **¥3.2 / 100 积分**；默认模型参数，不是本次查询的实时商城率 | 不能说当前可兑换同等现金或节省额 |
| 立减券 | 面值 × 模型使用概率 − 诱导消费扣减 | 券面值不等于已兑现节省 |
| 折扣券 | 静态参照价 × 节省比例 × 模型使用概率 − 扣减 | 静态表不是现场、门店或实时价格 |
| 无参照价奖品 | 标注无法定价，不把未知价值冒充已核实估值 | 不能补造价格或据此保证最低收益 |
| 已过期券 | 模型估值计零 | 未过期也不证明已使用或一定会使用 |
| 最低列示估值 / 成本比 | 已列奖品模型值的比较 | 不保证无空奖、兑现下限或回本 |
| 情景分析 | 90% 中最低档、各档等概率等人为分布假设 | 假设净期望为正不等于真实回本概率高 |

只有在结果全集、概率与奖品兑现条件都明确时，才能讨论相应数学边界；当前列表和券估值不足以证明真实下限。报告应区分账户事实、静态参数、模型假设与无法核实项。

## 写操作仅为宿主可选能力

本项目 CLI 只读，没有 `draw` 子命令，也不执行 `draw-lottery`。不调用点餐、兑换等交易工具。

宿主若另外连接 MCP 并提供 `draw-lottery`，可在用户要求后按以下步骤操作：

1. 展示当前活动、资格和“仅抽一次，将消耗 N 积分”。费用或资格未知时停止。
2. 取得用户对具体费用的明确确认；请求分析不代表授权抽奖。
3. 执行 `draw-lottery` 一次，不默认循环。
4. 重新采集账户、活动与记录。写调用超时或结果不明时，先核实状态，不自动重试，避免重复消耗积分。

没有宿主写能力时，告知用户自行到官方渠道操作；不虚构 CLI 抽奖命令。

## 错误、限流与复现

| 情况 | 处理原则 |
|---|---|
| 401 | 提示用户本地检查或更新 Token，不输出凭据 |
| 429 | 提示降低调用频率，限额以当前服务规则为准；不无限重试 |
| 网络或协议错误 | 报告失败，不用 Demo 冒充真实数据 |
| 部分数据缺失 | 披露默认模型或跳过对应分析，不补造账户事实 |

纯计算可离线复现。测试命令覆盖当前项目用例，不固定测试数量：

```bash
python -m unittest discover -s tests -v
```

示例与存档分别见 [Demo 报告](examples/demo-output/report.md) 和 [真实采集存档](examples/real-run/report.md)。存档并非实时结论；旧产物中的估值或措辞不作为当前模型的核验依据。非官方产品，活动与价格以官方渠道为准。
