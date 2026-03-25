[English](README.md) | [中文](README_CN.md)

# AWS Best Practice Research Skill

An agent skill that researches, compiles, and optionally audits AWS service best practices against official documentation.

## Problem Statement

When configuring AWS services for production, engineers need to verify their setup against dozens of best-practice recommendations scattered across AWS documentation, Well-Architected Lenses, Security Hub controls, re:Post articles, and blog posts. Manually gathering and cross-referencing these sources is time-consuming and error-prone.

## What This Skill Does

1. **Research** — Searches official AWS documentation via [aws-knowledge-mcp-server](https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server) to find best practices for any AWS service.
2. **Compile** — Organizes findings into a categorized checklist table with 5 mandatory categories, source annotations, and priority levels.
3. **Audit (optional)** — If the user provides AWS credentials and resource identifiers, runs AWS CLI commands to check a live resource against the compiled checklist and generates an audit report with PASS/FAIL/WARN/N/A status per item.

## Prerequisites

| Dependency | Required For | Notes |
|-----------|-------------|-------|
| [aws-knowledge-mcp-server](https://github.com/awslabs/mcp/tree/main/src/aws-knowledge-mcp-server) | Checklist compilation (Steps 1-7) | Provides `aws___search_documentation`, `aws___read_documentation`, `aws___recommend` tools |
| AWS CLI (`aws`) | Live audit only (Step 8) | Must be configured with read access to the target service |
| AWS credentials + region + resource ID | Live audit only (Step 8) | Can be provided via env vars, profile, or credential file |

## Workflow Overview

```
Step 1: Identify target AWS service and audit scope
         ↓
Step 2: Search documentation (6 sequential queries)
         ↓
Step 3: Read key documentation pages (3-5 pages)
         ↓
Step 4: Extract and categorize check items
         ↓
Step 5: Compile source annotations
         ↓
Step 6: Generate checklist output (5-category table)
         ↓
Step 7: Offer next steps
         ↓
Step 8: Live resource audit (optional, only if credentials provided)
         ├── 8.1 Prepare environment
         ├── 8.2 Collect resource configuration
         ├── 8.3 Map configuration to checklist
         ├── 8.4 Generate audit report
         └── 8.5 Offer remediation
```

## Checklist Categories

Every generated checklist contains these 5 categories:

| # | Category | Example Items |
|---|----------|---------------|
| 1 | **High Availability Architecture** | Cluster mode, replication, Multi-AZ, AZ distribution, node types |
| 2 | **Disaster Recovery** | Backups, retention policies, RPO/RTO, cross-region replication |
| 3 | **Failover Planning** | Test Failover API, FIS testing, client timeout config, SNS notifications |
| 4 | **Security Configuration** | Encryption at-rest/in-transit, authentication, subnet groups, KMS |
| 5 | **Others** | Auto upgrade, monitoring, reserved memory, connection pooling, cost tags |

Each check item includes: ID (with embedded priority), name, description, source annotation, and priority level (High/Medium/Low).

## Check Item ID Format

```
{Category}-{Number}-{Priority}

Examples:
  HA-01-hi   → High Availability, item 1, High priority
  DR-02-md   → Disaster Recovery, item 2, Medium priority
  SEC-03-lo  → Security Configuration, item 3, Low priority
  OT-05-md   → Others, item 5, Medium priority
```

## Source Annotations

| Abbreviation | Source |
|--------------|--------|
| `WA-REL` / `WA-RELn` | Well-Architected Lens — Reliability Pillar |
| `WA-SEC` / `WA-SECn` | Well-Architected Lens — Security Pillar |
| `WA-PE` / `WA-PEn` | Well-Architected Lens — Performance Efficiency Pillar |
| `WA-OE` / `WA-OEn` | Well-Architected Lens — Operational Excellence Pillar |
| `WA-CO` | Well-Architected Lens — Cost Optimization Pillar |
| `Security Hub [{Service}.N]` | AWS Security Hub CSPM control |
| `re:Post` | AWS re:Post knowledge center article |
| `Official Docs` | Service user guide |
| `AWS Blog` | AWS official blog post |
| `Whitepaper` | AWS whitepaper |

## Audit Status Definitions

When performing a live audit, each check item receives one of these statuses:

| Status | Meaning |
|--------|---------|
| PASS | Resource configuration meets or exceeds the recommendation |
| FAIL | Resource configuration does not meet the recommendation |
| WARN | Cannot be fully verified from infrastructure alone, or partially meets |
| N/A | Check does not apply to this resource |

## Supported Services

The skill works with **any AWS service** that has documentation indexed by aws-knowledge-mcp-server. Pre-built audit command mappings exist for:

- **ElastiCache Redis / Valkey** — Full CLI command set and check-item-to-field mapping
- **Amazon RDS / Aurora** — Primary describe commands
- **Amazon MSK** — Cluster and configuration commands
- **Amazon DynamoDB** — Table, backup, and global table commands
- **Amazon EKS** — Cluster, nodegroup, and addon commands

Other services are supported for checklist compilation; live audit commands are derived from the service's AWS CLI reference.

## Directory Structure

```
aws-bestpractice-research/
├── SKILL.md                              # Main skill definition (agent instructions)
├── README.md                             # This file (PRD / user documentation)
└── references/
    ├── search-queries.md                 # 6 search query templates + page reading priority
    ├── output-template.md                # Checklist output format specification
    ├── audit-workflow.md                 # Per-service audit commands and field mappings
    └── audit-output-template.md          # Audit report format specification
```

## Usage Examples

**Checklist only:**
```
"帮我查找 ElastiCache Redis 的最佳实践"
"What are the best practices for Amazon MSK?"
"Compile a HA/DR/security checklist for Aurora PostgreSQL"
```

**Checklist + live audit:**
```
"Check my ElastiCache Redis cluster my-redis-cluster in us-west-2"
"审计一下我的 RDS 实例，region 是 ap-southeast-1，实例 ID 是 prod-db-01"
"Audit my DynamoDB table orders-table against best practices"
```

## Key Design Decisions

1. **Sequential MCP requests** — All documentation searches and page reads are executed one at a time to avoid rate limiting from aws-knowledge-mcp-server. This is slower but reliable.

2. **5-category structure** — Every checklist uses the same 5 categories regardless of service, providing a consistent audit framework across different AWS services.

3. **Embedded priority in ID** — The `-hi`/`-md`/`-lo` suffix in check IDs allows quick visual scanning without needing to read the Priority column.

4. **Optional live audit** — The checklist is a complete, standalone deliverable. Live audit is only triggered when the user explicitly provides credentials and resource identifiers. The skill never blocks on missing credentials.

5. **Language respect** — All output follows the language of the user's conversation (English, Chinese, etc.).

## Limitations

- Depends on aws-knowledge-mcp-server availability; if the MCP server is not configured, the skill cannot run.
- Rate limits on the MCP server mean documentation gathering takes ~30-60 seconds for 6 queries + 3-5 page reads.
- Live audit requires read-only IAM permissions for the target service; write permissions are never needed.
- Audit field mappings are pre-built for a limited set of services; other services derive audit commands dynamically.
- Client-side configurations (connection pooling, retry logic, timeouts) can only be flagged as WARN during live audit since they require application-level verification.
