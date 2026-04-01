[English](README.md) | [中文](README_CN.md)

# AWS FIS Experiment Execute

An agent skill that deploys infrastructure, runs an AWS FIS experiment, monitors its progress, and generates a results report. Reads configuration from a prepared experiment directory.

## Problem Statement

Running an AWS FIS experiment after preparation still involves multiple manual steps:

- **Two deployment methods** (CLI step-by-step vs CloudFormation all-in-one) with different command sequences — easy to miss steps or mix up ARNs.
- **Safety is critical** — FIS experiments affect **real production resources**. Starting without proper confirmation, impact review, or stop conditions risks unintended damage.
- **Monitoring during the experiment is manual** — polling experiment status, watching CloudWatch dashboards, and comparing actual behavior against expected behavior must happen simultaneously.
- **Results collection is scattered** — experiment status, action outcomes, timing, and recovery verification are queried from separate CLI commands and must be consolidated manually.

## What This Skill Does

1. **Loads and validates** the prepared experiment directory (from [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) or manually created).
2. **Deploys resources** via the user's chosen method (CLI step-by-step or CloudFormation).
3. **Enforces safety** — presents a clear impact warning with affected resources, requires explicit user confirmation before starting.
4. **Starts the experiment** only after explicit user confirmation.
5. **Monitors progress** — polls experiment status every 30-60 seconds, records timestamps for each status change and per-service events, reminds user to check the dashboard and expected-behavior doc.
6. **Saves results report** — writes the experiment results to a local markdown file (`YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md`) with **per-service impact analysis** where each service has its own timeline, observations, and key findings — so readers can see the full picture for each service without jumping between sections. Prints a brief summary to the terminal.

## Workflow Overview

```
Step 1: Load experiment directory + validate required files
         ↓
Step 2: Choose deployment method (CLI or CloudFormation)
         ↓
Step 3: Deploy resources (with user confirmation)
         ├── Path A: CLI — create role, alarms, dashboard, template step by step
         └── Path B: CFN — single stack deployment
         ↓
Step 4: Start experiment [CRITICAL — requires explicit user confirmation]
         ├── Display impact warning (resources, duration, stop conditions)
         ├── User confirms → start experiment
         └── User declines → skip to results report
         ↓
Step 5: Monitor experiment
         ├── Poll status every 30s (first 5 min) then 60s
         ├── Show current status after each poll
         ├── Record timestamps for each status change and action transition
         └── Remind user: check dashboard, read expected-behavior.md
         ↓
Step 6: Save results report to local file (YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md)
```

## Safety Rules

| Rule | Description |
|---|---|
| **Never auto-start** | Always require explicit user confirmation before starting the experiment |
| **Show every command** | Display each CLI command before executing it |
| **Impact warning** | Show affected resources, region, AZ, duration before start |
| **Abort at every step** | Provide abort instructions throughout the process |
| **No silent deletes** | Never delete resources without user confirmation |
| **Recommend dry-run** | Suggest reviewing all files before deploying |

## Experiment Status Values

| Status | Meaning |
|---|---|
| `initiating` | Experiment is starting |
| `running` | Experiment is in progress |
| `completed` | Experiment finished successfully |
| `stopping` | Being stopped (by user or stop condition) |
| `stopped` | Stopped before completion |
| `failed` | Experiment failed |

## Results Report

After the experiment reaches a terminal state, a results report is saved to a local
markdown file in the experiment directory. The file name uses the format:

```
YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md
```

The report includes:
- Experiment ID, template ID, final status
- Start time, end time, actual duration (all timestamps in ISO 8601 with timezone)
- Per-action results table (with action ID, status, and duration per action)
- Stop condition alarm status table
- **Per-service impact analysis** — for each service in `expected-behavior.md`, a dedicated sub-section containing:
  - **Key timeline** — only the events relevant to that specific service (timestamps in ISO 8601 with timezone), so readers can correlate with CloudWatch Dashboard metrics without leaving the section
  - **Observations** — observed behavior during and after the experiment
  - **Key findings** — what happened, why, and recovery behavior
- Recovery status summary table
- Issues requiring attention (with remediation commands)
- Cleanup instructions

A brief summary is printed to the terminal, including per-service recovery status.

## Required Files

The experiment directory must contain:

| File | Required | Purpose |
|---|---|---|
| `experiment-template.json` | Yes | FIS experiment template |
| `iam-policy.json` | Yes | IAM permissions for FIS role |
| `cfn-template.yaml` | Yes | All-in-one CloudFormation template |
| `README.md` | Yes | Experiment overview |
| `expected-behavior.md` | Yes | Runtime behavior reference |
| `alarms/stop-condition-alarms.json` | Optional | CloudWatch alarm definitions |
| `alarms/dashboard.json` | Optional | CloudWatch dashboard |

## Prerequisites

| Dependency | Required For | Notes |
|---|---|---|
| AWS CLI (`aws`) | FIS, IAM, CloudWatch, CloudFormation operations | Must have permissions for all four services |
| Prepared experiment directory | Configuration source | From aws-fis-experiment-prepare or manually created |

## Deployment Methods

### CLI Deployment (Step by Step)

1. Create IAM role + attach policy
2. Create CloudWatch alarms (stop conditions)
3. Create CloudWatch dashboard (optional)
4. Update experiment template with real ARNs
5. Create FIS experiment template

### CloudFormation Deployment (All-in-One)

1. `aws cloudformation deploy` with the CFN template
2. Wait for stack creation
3. Extract experiment template ID from stack outputs

## Cleanup Guide

### CLI Cleanup
```bash
aws fis delete-experiment-template --id "{TEMPLATE_ID}" --region {REGION}
aws cloudwatch delete-alarms --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" --region {REGION}
aws cloudwatch delete-dashboards --dashboard-names "FIS-{SCENARIO}" --region {REGION}
aws iam delete-role-policy --role-name "FISExperimentRole-{SCENARIO}" --policy-name FISExperimentPolicy
aws iam delete-role --role-name "FISExperimentRole-{SCENARIO}"
```

### CFN Cleanup
```bash
aws cloudformation delete-stack --stack-name "fis-{SCENARIO}-{TIMESTAMP}" --region {REGION}
```

## Error Handling

| Error | Cause | Resolution |
|---|---|---|
| `AccessDeniedException` | Insufficient permissions | Check IAM policy in iam-policy.json |
| `ValidationException` on template | Invalid template JSON | Validate with `aws fis create-experiment-template --generate-cli-skeleton` |
| `ResourceNotFoundException` on targets | Tagged resources not found | Verify resource tags match template |
| Alarm creation fails | Metric/namespace mismatch | Check metric name and namespace exist |
| Stack creation fails | CFN template error | Run `aws cloudformation validate-template` first |
| Experiment stuck in `initiating` | IAM role propagation delay | Wait 30 seconds and check again |

## Usage Examples

```
"Execute the FIS experiment in ./2025-03-27-10-30-00-az-power-interruption/"
"Run the chaos experiment I just prepared"
"启动 FIS 实验"
"Deploy and run the experiment in the rds-failover directory"
"运行混沌实验，目录在 ./2025-03-27-rds-failover/"
```

## Key Design Decisions

1. **Explicit confirmation is non-negotiable.** FIS experiments cause real impact. The skill never auto-starts — it always presents a warning with specific resource details and requires the user to type confirmation.

2. **Two deployment paths.** CLI gives granular control and visibility; CloudFormation gives simplicity. The user chooses based on their preference.

3. **Continuous monitoring with reminders.** During the experiment, the skill polls status and reminds the user to check the CloudWatch dashboard and expected-behavior.md. Operators should not rely solely on terminal output during fault injection.

4. **Results saved to file.** The experiment results report is written to a timestamped local markdown file, keeping terminal output concise while preserving a full record.

5. **Cleanup is offered, not forced.** After the experiment, cleanup commands are suggested but never executed without confirmation.

## Directory Structure

```
aws-fis-experiment-execute/
├── SKILL.md                              # Main skill definition (agent instructions)
├── README.md                             # This file (English)
├── README_CN.md                          # Chinese version
└── references/
    └── cli-commands.md                   # Complete AWS CLI command reference
```

## Limitations

- Requires AWS CLI with permissions for FIS, IAM, CloudWatch, and CloudFormation.
- Monitoring relies on CLI polling; real-time dashboard requires the user to open the CloudWatch console.
- The skill does not handle multi-step recovery verification — it reminds the user to check, but cannot verify application-level health automatically.
- CloudFormation deployment uses `aws cloudformation deploy` which may time out for complex stacks; the skill does not implement a self-healing loop (that is handled by aws-fis-experiment-prepare).

## Related Skills

- [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) — Generate and deploy experiment configuration (run before this skill)
- [aws-service-chaos-research](../aws-service-chaos-research/) — Research chaos testing scenarios for any AWS service
- [eks-workload-best-practice-assessment](../eks-workload-best-practice-assessment/) — Assess EKS workload configurations
