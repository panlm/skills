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
| [aws-service-chaos-research](./aws-service-chaos-research/) | 为特定 AWS 服务（RDS、EKS、MSK、ElastiCache 等）研究混沌工程、故障注入和韧性测试场景。识别可用的 FIS Action 及 HA 验证方法。 |
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | 生成运行 AWS FIS 实验所需的所有配置文件（实验模板、IAM 策略、CFN 模板、告警、Dashboard、预期行为文档），然后通过 CloudFormation 自愈迭代部署。支持 Scenario Library 预置场景和自定义单个 FIS Action。**注意：** Scenario Library 模板（AZ Power Interruption、AZ Application Slowdown、Cross-AZ Traffic Slowdown、Cross-Region Connectivity）无法通过 API 生成 — Skill 会读取 AWS 文档提取 JSON 模板。 |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | 部署并运行已准备好的 AWS FIS 实验。需要一个已准备好的实验目录（来自 aws-fis-experiment-prepare），处理部署、实验启动、实时监控和清理。 |
| [eks-workload-best-practice-assessment](./eks-workload-best-practice-assessment/) | 评估运行在 Amazon EKS 上的 Kubernetes 工作负载的最佳实践合规性，包括 Pod 配置、安全态势、可观测性、网络、存储、镜像安全和 CI/CD 实践。 |

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
