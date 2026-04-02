[English](README.md) | [中文](README_CN.md)

# panlm/skills

一组用于 AWS 运维、最佳实践研究和云基础设施管理的 Agent Skills。

## 安装

```bash
# 安装所有 Skills
npx skills add panlm/skills --skill '*'

# 安装单个 Skill
npx skills add panlm/skills --skill aws-bestpractice-research

# 列出可用 Skills
npx skills add panlm/skills --list
```

## 可用 Skills

| Skill | 说明 |
|-------|------|
| [aws-best-practice-research](./aws-best-practice-research/) | 为任意 AWS 服务研究并整理全面的最佳实践清单。生成分类的 HA/DR/安全检查表（含来源标注），可选对线上 AWS 资源进行合规审计。 |
| [eks-workload-best-practice-assessment](./eks-workload-best-practice-assessment/) | 评估运行在 Amazon EKS 上的 Kubernetes 工作负载的最佳实践合规性，包括 Pod 配置、安全态势、可观测性、网络、存储、镜像安全和 CI/CD 实践。 |
| [aws-service-chaos-research](./aws-service-chaos-research/) | 为特定 AWS 服务（RDS、EKS、MSK、ElastiCache 等）研究混沌工程、故障注入和韧性测试场景。识别可用的 FIS Action 及 HA 验证方法。 |
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | 生成运行 AWS FIS 实验所需的所有配置文件（实验模板、IAM 策略、CFN 模板、告警、Dashboard、预期行为文档），然后通过 CloudFormation 自愈迭代部署。支持 Scenario Library 预置场景和自定义单个 FIS Action。**注意：** Scenario Library 模板（AZ Power Interruption、AZ Application Slowdown、Cross-AZ Traffic Slowdown、Cross-Region Connectivity）无法通过 API 生成 — Skill 会读取 AWS 文档提取 JSON 模板。 |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | 部署并运行已准备好的 AWS FIS 实验。需要一个已准备好的实验目录（来自 aws-fis-experiment-prepare），处理部署、实验启动、实时监控和清理。 |
| [eks-app-log-analysis](./eks-app-log-analysis/) | 在 FIS 故障注入实验期间或之后分析 EKS 应用日志。支持实时监控（后台日志收集 + 实时洞察）和事后分析。生成按受影响服务分组的综合报告，包含错误时间线、模式识别和恢复分析。 |

## 其他 Skills

`others/` 目录下的实验性或补充性 Skills：

| Skill | 说明 |
|-------|------|
| [awesome-skills-deepdive](./others/awesome-skills-deepdive/) | 深度研究工具，用于探索和分析 awesome-skills 注册表中的 Skills。 |
| [gartner-hype-cycle](./others/gartner-hype-cycle/) | 使用 Gartner 技术成熟度曲线框架分析技术。 |
| [scp-paradigm](./others/scp-paradigm/) | 应用结构-行为-绩效范式进行行业分析。 |
| [value-chain-analysis](./others/value-chain-analysis/) | 执行波特价值链分析，用于商业战略。 |

## 前置条件

本仓库中的 Skills 可能依赖以下 MCP Server 和工具：

- [**aws-knowledge-mcp-server**](https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server) — AWS 文档搜索与检索
- [**context7**](https://context7.com/) — 库和框架文档查询，提供代码示例
- **AWS CLI** — 用于可选的线上资源审计

<details>
<summary>OpenCode MCP 配置示例（<code>config.json</code>）</summary>

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "aws-knowledge-mcp-server": {
      "type": "local",
      "command": ["uvx", "fastmcp", "run", "https://knowledge-mcp.global.api.aws"],
      "enabled": true
    },
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "enabled": true,
      "headers": {
        "CONTEXT7_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

</details>

## 最小权限建议

在运行 FIS 实验和 EKS 相关 Skills 之前，建议按最小权限原则配置以下权限。

### 1. 启用 EKS API 认证模式

FIS Pod 故障注入 Action（如 `aws:eks:pod-delete`、`aws:eks:pod-network-latency`）要求 EKS 集群支持 API 认证。将认证模式设置为 `API_AND_CONFIG_MAP`，同时兼容 `aws-auth` ConfigMap 和 EKS Access Entry：

```bash
aws eks update-cluster-config \
  --name <cluster-name> \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

> **为什么选两者兼容？** `API_AND_CONFIG_MAP` 保持与已有 `aws-auth` ConfigMap 映射的向后兼容，同时启用 FIS 和 CloudFormation（`AWS::EKS::AccessEntry`）所需的新版 Access Entry API。

### 2. 授予 EC2 实例角色访问 EKS 的权限

如果从 EC2 实例（如 Cloud9、堡垒机）运行这些 Skills，实例的 IAM 角色需要 EKS 集群的访问权限。为 EC2 角色创建 EKS Access Entry：

```bash
aws eks create-access-entry \
  --cluster-name <cluster-name> \
  --principal-arn arn:aws:iam::<account-id>:role/<ec2-role-name> \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name <cluster-name> \
  --principal-arn arn:aws:iam::<account-id>:role/<ec2-role-name> \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
```

> 请根据实际需要调整访问策略和范围。此处使用 `AmazonEKSClusterAdminPolicy` + cluster 范围仅为演示 — 生产环境建议使用更严格的策略（如 `AmazonEKSEditPolicy` 并限定到特定命名空间）。

### 3. 创建 CloudFormation 服务角色

FIS 准备 Skill 通过 CloudFormation 部署 Stack，其中包含 IAM 角色、CloudWatch 资源和 FIS 实验模板。建议创建专用的 CloudFormation 服务角色，而不是使用自身的宽泛权限。

参见配置指南：https://panlm.github.io/others/cfn-service-role-for-fis-experiment-setup-guide/

部署 Stack 时传入 `--role-arn`：

```bash
aws cloudformation deploy \
  --template-file cfn-template.yaml \
  --stack-name <stack-name> \
  --role-arn arn:aws:iam::<account-id>:role/CloudFormationFISServiceRole \
  --capabilities CAPABILITY_NAMED_IAM \
  --region <region>
```

> **好处：** 调用者只需 `cloudformation:*` 和 `iam:PassRole` 权限，所有资源创建都委托给服务角色，缩小影响范围。

## 贡献指南

添加新 Skill，请在 `skills/` 下创建目录并包含 `SKILL.md` 文件：

```
skills/
└── your-new-skill/
    ├── SKILL.md          # 必需：包含 YAML frontmatter 的 Skill 定义
    └── references/       # 可选：辅助模板和文档
```

`SKILL.md` 必须包含带有 `name` 和 `description` 的 YAML frontmatter：

```yaml
---
name: your-new-skill
description: What this skill does and when to use it
---
```

## 许可证

MIT
