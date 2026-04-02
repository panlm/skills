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
| [aws-fis-experiment-prepare](./aws-fis-experiment-prepare/) | Generate all configuration files needed to run an AWS FIS experiment (experiment template, IAM policy, CFN template, alarms, dashboard, expected-behavior doc), then deploy via CloudFormation with self-healing iteration. Supports both Scenario Library pre-built scenarios and custom single FIS actions. **Note:** Scenario Library templates (AZ Power Interruption, AZ Application Slowdown, Cross-AZ Traffic Slowdown, Cross-Region Connectivity) cannot be generated via API — the skill reads AWS documentation to extract the JSON templates. |
| [aws-fis-experiment-execute](./aws-fis-experiment-execute/) | Deploy and run a prepared AWS FIS experiment. Expects a prepared experiment directory (from aws-fis-experiment-prepare) and handles deployment, experiment start, real-time monitoring, and cleanup. |
| [eks-app-log-analysis](./eks-app-log-analysis/) | Analyze EKS application logs during or after FIS fault injection experiments. Supports real-time monitoring (background log collection + live insights) and post-hoc analysis. Generates comprehensive reports with error timelines, patterns, and recovery analysis grouped by affected services. |

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

### 1. Enable EKS API Authentication Mode

FIS Pod fault injection actions (e.g., `aws:eks:pod-delete`, `aws:eks:pod-network-latency`) require the EKS cluster to support API-based authentication. Set the authentication mode to `API_AND_CONFIG_MAP` so that both `aws-auth` ConfigMap and EKS Access Entry work:

```bash
aws eks update-cluster-config \
  --name <cluster-name> \
  --access-config authenticationMode=API_AND_CONFIG_MAP
```

> **Why both?** `API_AND_CONFIG_MAP` maintains backward compatibility with existing `aws-auth` ConfigMap mappings while enabling the newer Access Entry API used by FIS and CloudFormation (`AWS::EKS::AccessEntry`).

### 2. Grant EC2 Instance Role Access to EKS

If you run these skills from an EC2 instance (e.g., Cloud9, bastion host), the instance's IAM role needs permission to interact with the EKS cluster. Create an EKS Access Entry for the EC2 role:

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

> Adjust the access policy and scope as needed. `AmazonEKSClusterAdminPolicy` with cluster scope is shown for simplicity — in production, use a more restrictive policy (e.g., `AmazonEKSEditPolicy` scoped to specific namespaces).

### 3. Create a CloudFormation Service Role

The FIS prepare skill deploys CloudFormation stacks that create IAM roles, CloudWatch resources, and FIS experiment templates. Instead of using your own broad permissions, create a dedicated CloudFormation service role to limit the blast radius.

See the setup guide: https://panlm.github.io/others/cfn-service-role-for-fis-experiment-setup-guide/

Then pass `--role-arn` when deploying stacks:

```bash
aws cloudformation deploy \
  --template-file cfn-template.yaml \
  --stack-name <stack-name> \
  --role-arn arn:aws:iam::<account-id>:role/CloudFormationFISServiceRole \
  --capabilities CAPABILITY_NAMED_IAM \
  --region <region>
```

> **Benefit:** Your calling identity only needs `cloudformation:*` and `iam:PassRole` permissions. All resource creation is delegated to the service role, limiting the blast radius.

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
