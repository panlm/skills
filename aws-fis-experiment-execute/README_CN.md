[English](README.md) | [中文](README_CN.md)

# AWS FIS 实验执行

一个 Agent Skill，用于验证 CloudFormation Stack 已部署、运行 AWS FIS 实验、监控进度并生成结果报告。从已准备好的实验目录读取配置。

## 问题背景

在准备完成后运行 AWS FIS 实验仍然涉及手动验证步骤：

- **Stack 部署验证** — 运行实验前需要确认 CloudFormation Stack 已成功部署且处于 `CREATE_COMPLETE` 状态。
- **模板 ID 提取** — 必须从 Stack 输出中提取 FIS 实验模板 ID 才能启动实验。
- **安全至关重要** — FIS 实验影响**真实的生产资源**。未经确认、影响评估或 Stop Condition 就启动，可能造成意外损害。
- **实验期间的监控是手动的** — 轮询实验状态、查看 CloudWatch Dashboard、对比实际行为与预期行为必须同时进行。
- **结果收集分散** — 实验状态、Action 结果、时间和恢复验证需要从不同的 CLI 命令查询，必须手动汇总。

## 核心功能

1. **加载并验证** 已准备好的实验目录（来自 [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) 或手动创建）。
2. **读取 README.md** 提取 CFN Stack 名称和实验元数据。
3. **验证 Stack 部署** — 检查 CloudFormation Stack 是否处于 `CREATE_COMPLETE` 或 `UPDATE_COMPLETE` 状态。
4. **提取模板 ID** — 从 Stack 输出中获取。
5. **发现 EKS 应用依赖** — 自动发现依赖受影响 AWS 服务的 EKS Pod（通过搜索 Pod 环境变量、ConfigMap 和常见端口），然后与用户确认。**此步骤在实验启动前完成**，避免丢失早期日志。
6. **启动后台日志收集** — 在实验开始前对所有确认的应用启动 `kubectl logs -f`。如果用户要求前后对比，可选收集 2 分钟基线日志。
7. **强制安全确认** — 展示清晰的影响警告（受影响资源和监控的应用列表），要求用户明确确认后才启动。
8. **启动实验** — 仅在用户明确确认后执行。
9. **监控进度 + 日志洞察** — 每 30-60 秒轮询实验状态，记录每次状态变更和各服务事件的时间戳，显示各应用错误/警告计数和恢复信号，提醒用户查看 Dashboard。
10. **停止日志收集并分析** — 终止后台进程，可选等待 2 分钟收集实验后基线（如用户选择），然后分析错误模式、峰值速率和恢复时间。
11. **保存结果报告** — 将实验结果写入本地 Markdown 文件（`YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md`），包含**按服务拆分的影响分析**、**应用日志分析**（错误时间线、模式、恢复时间）和原始日志文件位置。终端仅打印简要摘要。

**注意：** 本 Skill **不会**部署基础设施。它仅验证 Stack 已部署，然后执行实验。

## 工作流程概览

```
步骤 1: 加载实验目录 + 验证必需文件
         ↓
步骤 2: 读取 README.md → 提取 CFN Stack 名称 + 元数据
         ↓
步骤 3: 检查 CloudFormation Stack 状态
         ├── CREATE_COMPLETE 或 UPDATE_COMPLETE → 继续
         └── 未就绪 / 失败 / 未找到 → 中止并提供指导
         ↓
步骤 4: 从 Stack 输出提取实验模板 ID
         ↓
步骤 5: 发现 EKS 应用依赖 [实验启动前完成]
         ├── 自动发现依赖受影响 AWS 服务的应用
         └── 用户确认 + 补充应用列表
         ↓
步骤 6: 启动后台日志收集 (kubectl logs -f)
         ├── 默认：立即开始收集
         └── 可选（用户选择）：先收集 2 分钟基线日志
         ↓
步骤 7: 启动实验 [关键 — 需要用户明确确认]
         ├── 展示影响警告（资源、应用、时长、Stop Condition）
         ├── 用户确认 → 启动实验
         └── 用户拒绝 → 跳至日志清理 + 报告
         ↓
步骤 8: 监控实验 + 日志洞察
         ├── 前 5 分钟每 30 秒轮询，之后每 60 秒
         ├── 每次轮询后显示当前状态 + 各应用错误/警告计数
         ├── 记录每次状态变更和 Action 转换的时间戳
         └── 提醒用户：查看 Dashboard
         ↓
步骤 9: 停止日志收集 + 分析
         ├── 默认：实验结束后立即停止
         ├── 可选（用户选择）：等待 2 分钟收集实验后基线
         └── 分析：错误模式、峰值速率、恢复时间
         ↓
步骤 10: 保存结果报告到本地文件 (YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md)
```

## 安全规则

| 规则 | 说明 |
|---|---|
| **绝不自动启动** | 启动实验前必须获得用户明确确认 |
| **展示每条命令** | 执行前先显示 CLI 命令 |
| **影响警告** | 启动前展示受影响资源、Region、AZ、时长 |
| **随时可中止** | 全流程提供中止说明 |
| **不静默删除** | 删除资源前必须获得用户确认 |
| **不部署基础设施** | 本 Skill 仅检查现有部署，不会部署基础设施 |
| **建议预审** | 建议用户在启动前审查所有文件 |

## Stack 状态处理

| 状态 | 操作 |
|---|---|
| `CREATE_COMPLETE` | Stack 已就绪，继续执行实验 |
| `UPDATE_COMPLETE` | Stack 已就绪（已更新），继续执行实验 |
| `CREATE_IN_PROGRESS` | Stack 仍在部署中，等待并重新检查 |
| `CREATE_FAILED` | Stack 部署失败，显示失败原因并中止 |
| `ROLLBACK_COMPLETE` | Stack 创建失败并已回滚，显示原因并中止 |
| `DELETE_COMPLETE` 或未找到 | Stack 不存在，通知用户先部署 |

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
- 实验 ID、模板 ID、Stack 名称、最终状态
- 开始时间、结束时间、实际时长（所有时间戳使用 ISO 8601 格式带时区）
- 各 Action 结果表（含 Action ID、状态和持续时间）
- Stop Condition 告警状态表
- **各服务影响分析** — 针对每个受影响的服务，生成独立子章节，包含：
  - **关键时间线** — 仅列出与该服务相关的事件（时间戳使用 UTC 时间格式），方便直接对照 CloudWatch Dashboard 指标，无需离开当前章节
  - **观察结果** — 实验期间和实验后的观察行为
  - **关键发现** — 发生了什么、为什么、恢复行为如何
- **应用日志分析** — 针对每个监控的 EKS 应用：
  - 错误时间线（含时间戳和消息）
  - 关键错误模式（计数、首次和末次出现时间）
  - 关键错误日志样本（5-10 行）
  - 将应用错误与基础设施事件关联的洞察
- 恢复状态总结表
- 需要关注的问题（含修复命令）
- 原始日志文件位置（附录）
- 清理说明

终端打印简要摘要，包含各服务恢复状态。

## 必需文件

实验目录必须包含：

| 文件 | 必需 | 用途 |
|---|---|---|
| `experiment-template.json` | 是 | FIS 实验模板 |
| `iam-policy.json` | 是 | FIS 角色 IAM 权限 |
| `cfn-template.yaml` | 是 | CloudFormation 模板（参考） |
| `README.md` | 是 | 实验概览，含 CFN Stack 名称 |
| `alarms/stop-condition-alarms.json` | 可选 | CloudWatch 告警定义 |
| `alarms/dashboard.json` | 可选 | CloudWatch Dashboard |

**关键：** `README.md` 必须包含 `**CFN Stack:** {STACK_NAME}` 字段，填入实际部署的 Stack 名称。此字段由 `aws-fis-experiment-prepare` 在成功部署后设置。

## 前置条件

- **AWS CLI** (`aws`) — FIS、CloudWatch、CloudFormation 操作。需要相关服务的权限。
- **kubectl** — 已配置目标 EKS 集群访问权限（用于应用日志收集和依赖发现）。
- **已准备好的实验目录** — 配置来源，来自 aws-fis-experiment-prepare 或手动创建。

## 关键 CLI 命令

### 检查 Stack 状态
```bash
aws cloudformation describe-stacks \
  --stack-name "{STACK_NAME}" \
  --region {REGION} \
  --query 'Stacks[0].{StackStatus: StackStatus, Outputs: Outputs}'
```

### 从 Stack 输出提取模板 ID
```bash
TEMPLATE_ID=$(aws cloudformation describe-stacks \
  --stack-name "{STACK_NAME}" \
  --query 'Stacks[0].Outputs[?OutputKey==`ExperimentTemplateId`].OutputValue' \
  --output text --region {REGION})
```

### 启动实验
```bash
aws fis start-experiment \
  --experiment-template-id "{TEMPLATE_ID}" \
  --region {REGION}
```

### 获取实验状态
```bash
aws fis get-experiment \
  --id "{EXPERIMENT_ID}" \
  --region {REGION} \
  --query 'experiment.state.status'
```

### 停止实验（紧急）
```bash
aws fis stop-experiment --id "{EXPERIMENT_ID}" --region {REGION}
```

## 清理指南

### CFN 清理（推荐）
```bash
aws cloudformation delete-stack --stack-name "{STACK_NAME}" --region {REGION}
aws cloudformation wait stack-delete-complete --stack-name "{STACK_NAME}" --region {REGION}
```

### 手动资源清理（如需要）
```bash
aws fis delete-experiment-template --id "{TEMPLATE_ID}" --region {REGION}
aws cloudwatch delete-alarms --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" --region {REGION}
aws cloudwatch delete-dashboards --dashboard-names "FIS-{SCENARIO}" --region {REGION}
```

## 错误处理

| 错误 | 原因 | 解决方法 |
|---|---|---|
| README 中未找到 Stack 名称 | README 缺少 `**CFN Stack:**` 字段 | 检查是否使用最新版本的 aws-fis-experiment-prepare |
| Stack 未找到 (`ValidationError`) | Stack 不存在或已删除 | 先使用 aws-fis-experiment-prepare 部署 Stack |
| Stack 处于 `CREATE_FAILED` | Stack 部署失败 | 检查 Stack 事件了解失败原因，修复并重新部署 |
| `ExperimentTemplateId` 不在输出中 | Stack 模板缺少输出 | 检查 cfn-template.yaml 中的输出定义 |
| `AccessDeniedException` | 权限不足 | 检查 FIS、CloudWatch、CloudFormation 的 IAM 权限 |
| `ResourceNotFoundException` 目标未找到 | 标签资源不存在 | 验证资源标签与实验模板匹配 |
| 实验卡在 `initiating` | IAM 角色传播延迟 | 等待 30 秒再检查 |

## 使用示例

```
"Execute the FIS experiment in ./2025-03-27-10-30-00-az-power-interruption-my-cluster/"
"Run the chaos experiment I just prepared"
"启动 FIS 实验"
"检查 Stack 是否已部署并运行实验"
"运行混沌实验，目录在 ./2025-03-27-rds-failover-prod-db/"
```

## 关键设计决策

1. **不部署 — 仅验证。** 本 Skill 假设 CloudFormation Stack 已部署（由 `aws-fis-experiment-prepare` 或手动部署）。它在执行前验证 Stack 状态。

2. **从 README 获取 Stack 名称。** Stack 名称从实验目录的 README.md 中的 `**CFN Stack:**` 字段提取，确保与 prepare skill 的输出一致。

3. **明确确认不可妥协。** FIS 实验产生真实影响。Skill 绝不自动启动 — 始终展示具体资源细节的警告，要求用户输入确认。

4. **应用发现在实验启动前完成。** EKS 应用依赖在实验开始前发现，日志收集也在实验前启动。这防止实验开始后才找应用，导致早期日志被轮转或覆盖而丢失。

5. **集成的日志收集和分析。** 应用日志自动收集 — 无需单独调用其他 Skill。结果报告在同一文档中包含基础设施影响分析和应用日志分析。

6. **基线日志可选。** 默认情况下，日志收集在实验启动时开始，实验结束时停止。实验前（2 分钟）和实验后（2 分钟）基线收集仅在用户明确要求时激活，保持默认流程简洁高效。

7. **监控中包含日志洞察。** 实验期间，每次轮询同时展示实验状态和各应用错误/警告计数，让操作者实时了解应用受影响情况。

8. **结果保存到文件。** 实验结果报告写入带时间戳的本地 Markdown 文件，终端输出保持简洁，同时保留完整记录。

9. **清理建议但不强制。** 实验结束后提供清理命令，但绝不在未确认的情况下执行。

## 目录结构

```
aws-fis-experiment-execute/
├── SKILL.md                              # Skill 主定义文件（Agent 执行指令）
├── README.md                             # 英文版 PRD / 用户文档
├── README_CN.md                          # 本文件（中文版）
└── references/
    └── cli-commands.md                   # AWS CLI 命令参考
```

## 已知限制

- 需要 AWS CLI 并具有 FIS、CloudWatch、CloudFormation 权限。
- 需要 kubectl 已配置目标 EKS 集群访问权限（用于日志收集）。
- **不部署基础设施** — 期望 Stack 已部署。
- 监控依赖 CLI 轮询；实时 Dashboard 需要用户打开 CloudWatch 控制台。
- 应用日志收集使用 `kubectl logs -f`，仅能捕获运行中 Pod 的日志。实验期间被终止的 Pod 的日志可能丢失，除非启用了 Container Insights。
- 应用依赖自动发现依赖 Pod 环境变量和 ConfigMap 中的端点引用 — 使用服务发现或 DNS 解析的应用可能无法自动检测。

## 相关 Skill

- [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) — 生成并部署实验配置（本 Skill 之前运行）
- [aws-service-chaos-research](../aws-service-chaos-research/) — 为任意 AWS 服务研究混沌测试场景
- [eks-app-log-analysis](../eks-app-log-analysis/) — 独立的事后应用日志分析（本 Skill 现已集成实时日志分析）
- [eks-workload-best-practice-assessment](../eks-workload-best-practice-assessment/) — 评估 EKS 工作负载配置
