[English](README.md) | [中文](README_CN.md)

# AWS FIS 实验执行

一个 Agent Skill，用于部署基础设施、运行 AWS FIS 实验、监控进度并生成结果报告。从已准备好的实验目录读取配置。

## 问题背景

在准备完成后运行 AWS FIS 实验仍然涉及多个手动步骤：

- **两种部署方式**（CLI 逐步执行 vs CloudFormation 一键部署）有不同的命令序列 — 容易漏步或搞混 ARN。
- **安全至关重要** — FIS 实验影响**真实的生产资源**。未经确认、影响评估或 Stop Condition 就启动，可能造成意外损害。
- **实验期间的监控是手动的** — 轮询实验状态、查看 CloudWatch Dashboard、对比实际行为与预期行为必须同时进行。
- **结果收集分散** — 实验状态、Action 结果、时间和恢复验证需要从不同的 CLI 命令查询，必须手动汇总。

## 核心功能

1. **加载并验证** 已准备好的实验目录（来自 [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) 或手动创建）。
2. **部署资源** — 按用户选择的方式（CLI 逐步或 CloudFormation）部署。
3. **强制安全确认** — 展示清晰的影响警告（受影响资源列表），要求用户明确确认后才启动。
4. **启动实验** — 仅在用户明确确认后执行。
5. **监控进度** — 每 30-60 秒轮询实验状态，记录每次状态变更和各服务事件的时间戳，提醒用户查看 Dashboard 和预期行为文档。
6. **保存结果报告** — 将实验结果写入本地 Markdown 文件（`YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md`），采用**按服务拆分的影响分析**结构，每个服务有独立的时间线、观察结果和关键发现 — 读者无需在章节间来回跳转即可看到每个服务的完整分析。终端仅打印简要摘要。

## 工作流程概览

```
步骤 1: 加载实验目录 + 验证必需文件
         ↓
步骤 2: 选择部署方式（CLI 或 CloudFormation）
         ↓
步骤 3: 部署资源（需用户确认）
         ├── 路径 A: CLI — 逐步创建角色、告警、Dashboard、模板
         └── 路径 B: CFN — 单个 Stack 部署
         ↓
步骤 4: 启动实验 [关键 — 需要用户明确确认]
         ├── 展示影响警告（资源、时长、Stop Condition）
         ├── 用户确认 → 启动实验
         └── 用户拒绝 → 跳至结果报告
         ↓
步骤 5: 监控实验
         ├── 前 5 分钟每 30 秒轮询，之后每 60 秒
         ├── 每次轮询后显示当前状态
         ├── 记录每次状态变更和 Action 转换的时间戳
         └── 提醒用户：查看 Dashboard，阅读 expected-behavior.md
         ↓
步骤 6: 保存结果报告到本地文件 (YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md)
```

## 安全规则

| 规则 | 说明 |
|---|---|
| **绝不自动启动** | 启动实验前必须获得用户明确确认 |
| **展示每条命令** | 执行前先显示 CLI 命令 |
| **影响警告** | 启动前展示受影响资源、Region、AZ、时长 |
| **随时可中止** | 全流程提供中止说明 |
| **不静默删除** | 删除资源前必须获得用户确认 |
| **建议预审** | 建议用户在部署前审查所有文件 |

## 实验状态值

| 状态 | 含义 |
|---|---|
| `initiating` | 实验正在启动 |
| `running` | 实验进行中 |
| `completed` | 实验成功完成 |
| `stopping` | 正在停止（用户或 Stop Condition 触发） |
| `stopped` | 完成前被停止 |
| `failed` | 实验失败 |

## 结果报告

实验到达终态后，结果报告保存为实验目录中的本地 Markdown 文件，文件名格式：

```
YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md
```

报告包含：
- 实验 ID、模板 ID、最终状态
- 开始时间、结束时间、实际时长（所有时间戳使用 ISO 8601 格式带时区）
- 各 Action 结果表（含 Action ID、状态和持续时间）
- Stop Condition 告警状态表
- **各服务影响分析** — 针对 `expected-behavior.md` 中的每个服务，生成独立子章节，包含：
  - **关键时间线** — 仅列出与该服务相关的事件（时间戳使用 ISO 8601 格式带时区），方便直接对照 CloudWatch Dashboard 指标，无需离开当前章节
  - **观察结果** — 实验期间和实验后的观察行为
  - **关键发现** — 发生了什么、为什么、恢复行为如何
- 恢复状态总结表
- 需要关注的问题（含修复命令）
- 清理说明

终端打印简要摘要，包含各服务恢复状态。

## 必需文件

实验目录必须包含：

| 文件 | 必需 | 用途 |
|---|---|---|
| `experiment-template.json` | 是 | FIS 实验模板 |
| `iam-policy.json` | 是 | FIS 角色 IAM 权限 |
| `cfn-template.yaml` | 是 | 全包 CloudFormation 模板 |
| `README.md` | 是 | 实验概览 |
| `expected-behavior.md` | 是 | 运行时行为参考 |
| `alarms/stop-condition-alarms.json` | 可选 | CloudWatch 告警定义 |
| `alarms/dashboard.json` | 可选 | CloudWatch Dashboard |

## 前置条件

| 依赖 | 用于 | 说明 |
|---|---|---|
| AWS CLI (`aws`) | FIS、IAM、CloudWatch、CloudFormation 操作 | 需要四项服务的权限 |
| 已准备好的实验目录 | 配置来源 | 来自 aws-fis-experiment-prepare 或手动创建 |

## 部署方式

### CLI 部署（逐步执行）

1. 创建 IAM 角色 + 附加策略
2. 创建 CloudWatch 告警（Stop Condition）
3. 创建 CloudWatch Dashboard（可选）
4. 用真实 ARN 更新实验模板
5. 创建 FIS 实验模板

### CloudFormation 部署（一键部署）

1. 使用 CFN 模板执行 `aws cloudformation deploy`
2. 等待 Stack 创建完成
3. 从 Stack 输出提取实验模板 ID

## 清理指南

### CLI 清理
```bash
aws fis delete-experiment-template --id "{TEMPLATE_ID}" --region {REGION}
aws cloudwatch delete-alarms --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" --region {REGION}
aws cloudwatch delete-dashboards --dashboard-names "FIS-{SCENARIO}" --region {REGION}
aws iam delete-role-policy --role-name "FISExperimentRole-{SCENARIO}" --policy-name FISExperimentPolicy
aws iam delete-role --role-name "FISExperimentRole-{SCENARIO}"
```

### CFN 清理
```bash
aws cloudformation delete-stack --stack-name "fis-{SCENARIO}-{TIMESTAMP}" --region {REGION}
```

## 错误处理

| 错误 | 原因 | 解决方法 |
|---|---|---|
| `AccessDeniedException` | 权限不足 | 检查 iam-policy.json 中的 IAM 策略 |
| `ValidationException` 模板错误 | 无效的模板 JSON | 用 `aws fis create-experiment-template --generate-cli-skeleton` 验证 |
| `ResourceNotFoundException` 目标未找到 | 标签资源不存在 | 验证资源标签与模板匹配 |
| 告警创建失败 | 指标/命名空间不匹配 | 检查指标名称和命名空间是否存在 |
| Stack 创建失败 | CFN 模板错误 | 先运行 `aws cloudformation validate-template` |
| 实验卡在 `initiating` | IAM 角色传播延迟 | 等待 30 秒再检查 |

## 使用示例

```
"Execute the FIS experiment in ./2025-03-27-10-30-00-az-power-interruption/"
"Run the chaos experiment I just prepared"
"启动 FIS 实验"
"部署并运行目录中的实验"
"运行混沌实验，目录在 ./2025-03-27-rds-failover/"
```

## 关键设计决策

1. **明确确认不可妥协。** FIS 实验产生真实影响。Skill 绝不自动启动 — 始终展示具体资源细节的警告，要求用户输入确认。

2. **两种部署路径。** CLI 提供细粒度控制和可见性；CloudFormation 提供简洁性。用户根据偏好选择。

3. **持续监控加提醒。** 实验期间，Skill 轮询状态并提醒用户查看 CloudWatch Dashboard 和 expected-behavior.md。故障注入期间不应仅依赖终端输出。

4. **结果保存到文件。** 实验结果报告写入带时间戳的本地 Markdown 文件，终端输出保持简洁，同时保留完整记录。

5. **清理建议但不强制。** 实验结束后提供清理命令，但绝不在未确认的情况下执行。

## 目录结构

```
aws-fis-experiment-execute/
├── SKILL.md                              # Skill 主定义文件（Agent 执行指令）
├── README.md                             # 英文版 PRD / 用户文档
├── README_CN.md                          # 本文件（中文版）
└── references/
    └── cli-commands.md                   # 完整的 AWS CLI 命令参考
```

## 已知限制

- 需要 AWS CLI 并具有 FIS、IAM、CloudWatch、CloudFormation 权限。
- 监控依赖 CLI 轮询；实时 Dashboard 需要用户打开 CloudWatch 控制台。
- Skill 不处理多步恢复验证 — 会提醒用户检查，但无法自动验证应用层健康。
- CloudFormation 部署使用 `aws cloudformation deploy`，复杂 Stack 可能超时；Skill 不实现自动修复循环（由 aws-fis-experiment-prepare 处理）。

## 相关 Skill

- [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) — 生成并部署实验配置（本 Skill 之前运行）
- [aws-service-chaos-research](../aws-service-chaos-research/) — 为任意 AWS 服务研究混沌测试场景
- [eks-workload-best-practice-assessment](../eks-workload-best-practice-assessment/) — 评估 EKS 工作负载配置
