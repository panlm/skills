[English](README.md) | [中文](README_CN.md)

# panlm/skills

A collection of agent skills for AWS operations, best practices research, and cloud infrastructure management.

## Install

```bash
# Install all skills
npx skills add panlm/skills --skill '*'

# Install a specific skill
npx skills add panlm/skills --skill aws-bestpractice-research

# List available skills
npx skills add panlm/skills --list
```

## Available Skills

| Skill | Description |
|-------|-------------|
| [aws-best-practice-research](./aws-best-practice-research/) | Research and compile comprehensive best-practice checklists for any AWS service. Produces categorized HA/DR/security checklist tables with source annotations. Optionally audits live AWS resources against the compiled checklist. |
| [eks-workload-best-practice-assessment](./eks-workload-best-practice-assessment/) | Assess Kubernetes workloads running on Amazon EKS for best practice compliance, including pod configuration, security posture, observability, networking, storage, image security, and CI/CD practices. |
| [aws-service-chaos-research](./aws-service-chaos-research/) | Research chaos engineering, fault injection, and resilience testing scenarios for a specific AWS service (RDS, EKS, MSK, ElastiCache, etc.). Identifies available FIS actions and HA verification approaches. |
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | Generate configuration files needed to run an AWS FIS experiment (CFN template with embedded experiment template, IAM role, dashboard), then deploy via CloudFormation with self-healing iteration. Supports both Scenario Library pre-built scenarios and custom single FIS actions. For AZ Power Interruption, supports **service-scoped sub-action pruning** — only includes sub-actions for user-specified services to prevent unintended blast radius. Default experiment duration is 10 minutes. |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | Run a prepared AWS FIS experiment. Extracts the template ID from the experiment directory name, queries FIS API for actions, discovers affected applications, starts the experiment with explicit user confirmation, monitors progress with real-time log insights, and generates a results report. |
| [app-service-log-analysis](./app-service-log-analysis/) | Analyze EKS application logs during or after FIS fault injection experiments. **Multi-cluster deep dependency discovery** — automatically discovers all EKS clusters in the target region, generates isolated kubeconfig files (never overwrites `~/.kube/config`), and deep-scans all accessible clusters in parallel (env vars, ConfigMaps, Secrets, ExternalName, etc.) for applications depending on fault-injected services. Supports real-time monitoring and post-hoc analysis with comprehensive reports. |

## Other Skills

Experimental or supplementary skills in the `others/` directory:

| Skill | Description |
|-------|-------------|
| [awesome-skills-deepdive](./others/awesome-skills-deepdive/) | Deep dive research tool for exploring and analyzing skills from the awesome-skills registry. |
| [gartner-hype-cycle](./others/gartner-hype-cycle/) | Analyze technologies using the Gartner Hype Cycle framework. |
| [scp-paradigm](./others/scp-paradigm/) | Apply the Structure-Conduct-Performance paradigm for industry analysis. |
| [value-chain-analysis](./others/value-chain-analysis/) | Perform Porter's Value Chain Analysis for business strategy. |

## Prerequisites

Skills in this repo may depend on the following MCP servers and tools:

- [**aws-knowledge-mcp-server**](https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server) -- AWS documentation search and retrieval
- [**context7**](https://context7.com/) -- Library and framework documentation lookup with code examples
- **AWS CLI** -- for optional live resource auditing

<details>
<summary>OpenCode MCP configuration sample (<code>config.json</code>)</summary>

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

## Least Privilege Recommendations

Before running FIS experiments and EKS-related skills, we recommend setting up the following permissions using the principle of least privilege.

- **EKS authentication and access setup** — See [eks-workload-best-practice-assessment Prerequisites](./eks-workload-best-practice-assessment/README.md#prerequisites) for enabling EKS API authentication mode and granting EC2 instance role access to EKS.
- **CloudFormation service role** — See [aws-fis-experiment-prepare Prerequisites](./aws-fis-experiment-prepare/README.md#create-a-cloudformation-service-role) for creating a dedicated CFN service role to deploy FIS experiment stacks with least privilege.

## License

MIT
