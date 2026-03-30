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
| [aws-service-chaos-research](./aws-service-chaos-research/) | Research chaos engineering, fault injection, and resilience testing scenarios for a specific AWS service (RDS, EKS, MSK, ElastiCache, etc.). Identifies available FIS actions and HA verification approaches. |
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | Generate all configuration files needed to run an AWS FIS experiment (experiment template, IAM policy, CFN template, alarms, dashboard, expected-behavior doc), then deploy via CloudFormation with self-healing iteration. Supports both Scenario Library pre-built scenarios and custom single FIS actions. **Note:** Scenario Library templates (AZ Power Interruption, AZ Application Slowdown, Cross-AZ Traffic Slowdown, Cross-Region Connectivity) cannot be generated via API — the skill reads AWS documentation to extract the JSON templates. |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | Deploy and run a prepared AWS FIS experiment. Expects a prepared experiment directory (from aws-fis-experiment-prepare) and handles deployment, experiment start, real-time monitoring, and cleanup. |
| [eks-workload-best-practice-assessment](./eks-workload-best-practice-assessment/) | Assess Kubernetes workloads running on Amazon EKS for best practice compliance, including pod configuration, security posture, observability, networking, storage, image security, and CI/CD practices. |

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

## Contributing

To add a new skill, create a directory under `skills/` with a `SKILL.md` file:

```
skills/
└── your-new-skill/
    ├── SKILL.md          # Required: skill definition with YAML frontmatter
    └── references/       # Optional: supporting templates and docs
```

The `SKILL.md` must include YAML frontmatter with `name` and `description`:

```yaml
---
name: your-new-skill
description: What this skill does and when to use it
---
```

## License

MIT
