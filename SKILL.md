---
name: mcd-lottery-bureau
description: 麦麦积分精算局·抽奖军师。用户询问积分抽奖是否值得、临期积分用途或历史奖品记录时使用。通过本地 Python CLI 单次采集麦当劳 MCP 数据，检查资格、解释券估值与假设情景；不预测中奖，不承诺回本，不自动抽奖。
---

# 麦麦积分精算局 · 抽奖军师

## 安装与运行前提

1. 将仓库克隆到本地，保留 `bureau.py`、`bureau/` 与 `examples/`。需要 Python 3，无第三方依赖。
2. 按宿主的 Skill 安装方式，把本文件安装或登记到宿主技能目录；宿主必须能运行本地命令。只复制 `SKILL.md` 不会安装 Python 项目，也不会让相对路径自动可用。
3. 确认仓库绝对路径。下文 Windows 示例对应 `D:\work\ZCode-test\mcd-lottery-bureau`；其他机器替换为实际路径，不能假设工作目录正好是仓库。
4. 真实模式单独为 CLI 配置 `MCD_MCP_TOKEN`。宿主中已配置 MCP 不代表 CLI 有 Token。到 https://open.mcd.cn/mcp 申请，然后由用户在本地项目 `.env` 或 CLI 进程环境变量中配置；不要让用户在对话中粘贴 Token，不读取或展示凭据。

```powershell
# 用户在本地 PowerShell 配置；占位符替换为自己的 Token
$env:MCD_MCP_TOKEN = '<你的 Token>'
python 'D:\work\ZCode-test\mcd-lottery-bureau\bureau.py' check --json
```

Bash 可用 `export MCD_MCP_TOKEN='<你的 Token>'`，再执行 `python /绝对路径/mcd-lottery-bureau/bureau.py check --json`。不要写入或分享凭据。

## 触发条件

- 积分抽奖值不值、该不该抽、能不能算期望。
- 积分快过期、积分怎么用更合适。
- 看历史奖品记录、运气分析或生成示意鉴定卡。

## 工作流程

### 1. 选择单次 CLI 路线

默认执行一次 `check --json`，由 CLI 完成采集和计算。**不要先在宿主调用四个 MCP 工具，再运行 CLI 重复采集。**

```powershell
python 'D:\work\ZCode-test\mcd-lottery-bureau\bureau.py' check --json
```

需报告与卡片时，改用一个导出命令，不再额外运行 `check` 或 `luck`：

```powershell
python 'D:\work\ZCode-test\mcd-lottery-bureau\bureau.py' check --md 'D:\work\ZCode-test\mcd-lottery-bureau\report.md' --card 'D:\work\ZCode-test\mcd-lottery-bureau\luck.svg'
```

只需历史记录卡时可选 `luck --out <绝对输出路径>`。输出路径由用户或宿主指定，不覆盖需保留的报告。

无 Token、无法联网或只体验时执行一次 `demo --json`，明确标注 Demo：

```powershell
python 'D:\work\ZCode-test\mcd-lottery-bureau\bureau.py' demo --json
```

若宿主不能运行命令，告知限制，让用户本地运行并提供脱敏输出；不要冒充已经读取真实账户。

### 2. 核对数据来源与参与资格

`check` 串行调用以下四个业务工具，不并行：

| 顺序 | 工具 | 用途与限制 |
|---|---|---|
| 1 | `query-my-account` | 积分余额、`currentMouthExpirePoint` 等到期字段 |
| 2 | `query-lottery-info` | `drawPoint`、奖品列表、`drawDecision.resourceEligible` 与原因 |
| 3 | `order-list` | 消费画像估计；失败则披露默认画像 |
| 4 | `query-my-prizes` | 单页最多 50 条奖品记录；失败则不做历史分析 |

参与资格看 `drawDecision.resourceEligible` 和返回原因，不能仅凭余额认定可抽；缺失或未知不当作 `true`。余额不足时报告不足，不指引用户充值或继续抽。记录日期与采集时间必须区分，存档不是实时数据。

### 3. 解读模型，明确假设

- **奖池最低估值 / 成本比**：针对已列奖品的模型值。列表不证明没有空奖，券估值也不是兑现下限；`guarantee_proven` 默认 `false`，不能宣称所有分布下不亏。
- **情景分析**：90% 中最低档、各档等概率均是人为假设，不是已知概率。只说明假设净期望，不转述成回本概率或抽奖建议。
- **券估值**：面值或折扣节省额 × 模型使用概率 − 诱导消费扣减。消费频率推导的概率未经用户用券行为验证；未过期券不等于现金，过期券估值计零。
- **价格与积分率**：折扣券参照价是静态表，非现场价格；缺参照价应标无法定价。默认 ¥3.2 / 100 积分仅为机会成本假设，非实时商城率。
- **历史分析**：单页奖品记录最多 50 条，不是全部抽奖次数或中奖率样本。按当前单次积分价格估算成本，不能声称历史实际成本、真实净收益或已兑现节省；卡片标签仅为样本示意。

遇到未知奖品、数据缺失或估值不可用，说明无法判断，不补造数字。

### 4. 给出可执行但非强制的选择

| 情况 | 表述 |
|---|---|
| 资格不足或未知 | 暂无法参与或无法确认；说明数据原因 |
| 积分临期 | 先比较官方兑换、已有消费需求与到期时间；临期不构成必须抽奖的理由 |
| 假设净期望为正 | 仅在给定模型下为正；实际概率、空奖与券兑现情况未知 |
| 假设净期望为负或估值不全 | 说明不利假设或信息缺口，可建议查看官方兑换，不断言真实回本概率 |

### 5. 可选宿主抽奖：必须独立确认

CLI 只读账户，没有 `draw` 子命令。仅当宿主另行安装 MCP 且确实可调用 `draw-lottery` 时，才有以下可选步骤：

1. 刷新并展示当前资格、活动和单次费用：“本次将消耗 N 积分，仅抽一次”。费用或资格未知时不要执行。
2. 取得用户对这次具体费用的明确确认。询问“值不值”、请求报告或谈及临期，都不构成授权。
3. 调用 `draw-lottery` 一次。不默认循环，不因未中奖继续抽。
4. 执行后重新运行一次 `check --json` 刷新账户和记录。若调用结果不明或超时，先查状态，不能自动重试写操作。

宿主没有写工具时告知不支持，让用户自行在官方渠道操作。

## 输出要点

- 数据来源：Demo / 本次采集 / 存档，说明局限。
- 余额与参与资格、单次积分费用；未知明说。
- 模型估值、情景假设、静态价格与默认积分率。
- 兑换等替代选项，不承诺回本，不要求抽临期积分。
- 历史记录分析注明样本条数与当前成本估算口径。

非麦当劳官方产品；规则、价格、券限制与实际抽奖结果以官方渠道为准。不分享 Token 或未脱敏账户信息。
