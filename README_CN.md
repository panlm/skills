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
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | 生成运行 AWS FIS 实验所需的配置文件（包含实验模板、IAM 角色、Dashboard 的 CFN 模板），然后通过 CloudFormation 自愈迭代部署。支持 Scenario Library 预置场景和自定义单个 FIS Action。AZ 电力中断场景支持**按服务范围裁剪子动作** — 仅包含用户指定服务的子动作，避免影响范围过大。默认实验持续时间 10 分钟。 |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | 运行已准备好的 AWS FIS 实验。从实验目录名提取模板 ID，通过 FIS API 查询 Actions，发现受影响的应用，经用户明确确认后启动实验，实时监控进度并展示日志洞察，生成结果报告。 |
| [app-service-log-analysis](./app-service-log-analysis/) | 在 FIS 故障注入实验期间或之后分析 EKS 应用日志。**多集群深度依赖发现** — 自动发现目标 Region 中所有 EKS 集群，为每个集群生成独立 kubeconfig 文件（绝不覆盖 `~/.kube/config`），并行深度扫描所有可访问集群（环境变量、ConfigMap、Secret、ExternalName 等）查找依赖故障注入目标服务的应用。支持实时监控和事后分析，生成综合报告。 |

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

- **EKS 认证和访问配置** — 参见 [eks-workload-best-practice-assessment 前置要求](./eks-workload-best-practice-assessment/README_CN.md#前置要求) 中关于启用 EKS API 认证模式和授予 EC2 实例角色访问 EKS 的说明。
- **CloudFormation 服务角色** — 参见 [aws-fis-experiment-prepare 前置条件](./aws-fis-experiment-prepare/README_CN.md#创建-cloudformation-服务角色) 中关于创建专用 CFN 服务角色以最小权限部署 FIS 实验 Stack 的说明。

## 致谢

本项目受到以下开源项目的启发，并在其基础上构建：

- [**aws-samples/sample-aws-resilience-skill**](https://github.com/aws-samples/sample-aws-resilience-skill) -- 韧性 Skill 示例项目，为本项目提供了关键的设计模式和架构灵感。
- [**aws-samples/fis-template-library**](https://github.com/aws-samples/fis-template-library) -- 本项目中引用的 SSM Automation 文档和 FIS 实验模板。

## 许可证

MIT
