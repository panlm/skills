[English](README.md) | [中文](README_CN.md)

# AWS FIS Experiment Execute

An agent skill that verifies a CloudFormation stack is already deployed, runs an AWS FIS experiment, monitors its progress, and generates a results report. Reads configuration from a prepared experiment directory.

## Problem Statement

Running an AWS FIS experiment after preparation still involves manual verification steps:

- **Stack deployment verification** — Before running an experiment, you need to confirm that the CloudFormation stack deployed successfully and is in `CREATE_COMPLETE` status.
- **Template ID extraction** — The FIS experiment template ID must be extracted from stack outputs before the experiment can be started.
- **Safety is critical** — FIS experiments affect **real production resources**. Starting without proper confirmation, impact review, or stop conditions risks unintended damage.
- **Monitoring during the experiment is manual** — polling experiment status, watching CloudWatch dashboards, and comparing actual behavior against expected behavior must happen simultaneously.
- **Results collection is scattered** — experiment status, action outcomes, timing, and recovery verification are queried from separate CLI commands and must be consolidated manually.

## What This Skill Does

1. **Loads and validates** the prepared experiment directory (from [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) or manually created). Supports **automatic directory resolution** from an experiment template ID — if the user provides a template ID (e.g., `EXT1a2b3c4d5e6f7`), the skill searches the current directory for a matching experiment directory.
2. **Reads README.md** to extract the CFN stack name and experiment metadata.
3. **Verifies stack deployment** — checks that the CloudFormation stack is in `CREATE_COMPLETE` or `UPDATE_COMPLETE` status.
4. **Extracts template ID** from stack outputs.
5. **Displays experiment actions** — reads `experiment-template.json` to extract and display all action IDs. Log collection is always enabled.
6. **Discovers EKS apps and starts log collection** — loads `app-service-log-analysis` skill to discover EKS apps and start background `kubectl logs -f` **before the experiment starts**. If kubectl is not available, skips app logs but still collects managed service logs via AWS CLI.
7. **Enforces safety** — presents a clear impact warning with affected resources, monitored applications, managed service log status, and post-baseline duration, requires explicit user confirmation before starting.
8. **Starts the experiment** only after explicit user confirmation.
9. **Monitors progress** — polls experiment status every 30-60 seconds, records timestamps for each status change and per-service events. Displays per-app error counts and recovery signals during each poll cycle.
10. **Collects post-experiment baseline and analyzes** — waits 3 minutes after experiment ends to capture recovery behavior, then follows `app-service-log-analysis` Steps 7-8 to analyze error patterns, peak rates, and recovery times.
11. **Saves results report** — writes the experiment results to a markdown file **in the experiment directory** with **per-service impact analysis** and **application log analysis**. Prints a brief summary to the terminal.

**Note:** This skill does **NOT** deploy infrastructure. It only verifies that the stack is already deployed and proceeds with experiment execution.

## Workflow Overview

```
Step 1:  Resolve experiment directory (from path or template ID)
          ├── Full path provided → validate directly
          ├── Template ID provided → search CWD for *-{ID} directory
          │   ├── 1 match → use it
          │   ├── Multiple matches → ask user to choose
          │   └── No match → ask user for full path
          └── Validate required files
          ↓
Step 2:  Read README.md → extract CFN stack name + metadata
          ↓
Step 3:  Check CloudFormation stack status
          ├── CREATE_COMPLETE or UPDATE_COMPLETE → proceed
          └── Not ready / failed / not found → abort with guidance
          ↓
Step 4:  Extract experiment template ID from stack outputs
          ↓
Step 5:  Display experiment actions
          ├── Read experiment-template.json, extract and display actionIds
          └── Log collection always enabled → proceed to Step 6
          ↓
Step 6:  Discover EKS apps + start log collection [BEFORE experiment]
          ├── Check kubectl availability
          ├── kubectl available → load app-service-log-analysis skill (real-time mode) Steps 3-4
          └── kubectl NOT available → skip app logs, still collect managed service logs
          ↓
Step 7:  Start experiment [CRITICAL — requires explicit user confirmation]
          ├── Display impact warning (resources, duration, stop conditions, monitored apps)
          ├── User confirms → start experiment
          └── User declines → abort (cleanup logs)
          ↓
Step 8:  Monitor experiment + log insights
          ├── Poll status every 30s (first 5 min) then 60s
          ├── Record timestamps for each status change and action transition
          ├── Show per-app error/warning counts (or managed-service-only if no kubectl)
          └── Remind user: check dashboard
          ↓
Step 9:  Post-experiment baseline (3 min) + stop logs + analyze
          ├── Wait 3 minutes to capture recovery behavior
          └── Analyze via app-service-log-analysis Steps 7-8
          ↓
Step 10: Save results report to experiment directory (YYYY-mm-dd-HH-MM-SS-{scenario}-experiment-results.md)
```

## Safety Rules

| Rule | Description |
|---|---|
| **Never auto-start** | Always require explicit user confirmation before starting the experiment |
| **Show every command** | Display each CLI command before executing it |
| **Impact warning** | Show affected resources, region, AZ, duration before start |
| **Abort at every step** | Provide abort instructions throughout the process |
| **No silent deletes** | Never delete resources without user confirmation |
| **Never deploy** | This skill only checks existing deployments, never deploys infrastructure |
| **Recommend dry-run** | Suggest reviewing all files before starting |

## Stack Status Handling

| Status | Action |
|---|---|
| `CREATE_COMPLETE` | Stack is ready. Proceed with experiment. |
| `UPDATE_COMPLETE` | Stack is ready (was updated). Proceed with experiment. |
| `CREATE_IN_PROGRESS` | Stack is still deploying. Wait and re-check. |
| `CREATE_FAILED` | Stack deployment failed. Show failure reason and abort. |
| `ROLLBACK_COMPLETE` | Stack creation failed and rolled back. Show reason and abort. |
| `DELETE_COMPLETE` or not found | Stack does not exist. Inform user to deploy first. |

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
- Experiment ID, template ID, stack name, final status
- Start time, end time, actual duration (all timestamps in ISO 8601 with timezone)
- Per-action results table (with action ID, status, and duration per action)
- Stop condition alarm status table
- **Per-service impact analysis** — for each affected service, a dedicated sub-section containing:
  - **Key timeline** — only the events relevant to that specific service (timestamps in UTC time-only format), so readers can correlate with CloudWatch Dashboard metrics without leaving the section
  - **Observations** — observed behavior during and after the experiment
  - **Key findings** — what happened, why, and recovery behavior
- **Application log analysis** — for each monitored EKS application:
  - Error timeline with timestamps and messages
  - Key error patterns with counts and first/last occurrence
  - Critical error log samples (5-10 lines)
  - Insights correlating app errors with infrastructure events
- Recovery status summary table
- Issues requiring attention (with remediation commands)
- Raw log file locations (appendix)
- Cleanup instructions

A brief summary is printed to the terminal, including per-service recovery status.

## Required Files

The experiment directory must contain:

| File | Required | Purpose |
|---|---|---|
| `experiment-template.json` | Yes | FIS experiment template |
| `iam-policy.json` | Yes | IAM permissions for FIS role |
| `cfn-template.yaml` | Yes | CloudFormation template (reference) |
| `README.md` | Yes | Experiment overview with CFN stack name |
| `alarms/stop-condition-alarms.json` | Optional | CloudWatch alarm definitions |
| `alarms/dashboard.json` | Optional | CloudWatch dashboard |

**Critical:** The `README.md` must contain the `**CFN Stack:** {STACK_NAME}` field populated with the actual deployed stack name. This is set by `aws-fis-experiment-prepare` after successful deployment.

## Prerequisites

- **AWS CLI** (`aws`) — FIS, CloudWatch, CloudFormation operations. Must have permissions for all services.
- **kubectl** (optional) — configured with access to target EKS cluster. If not available, application log collection is skipped but managed service logs are still collected via AWS CLI.
- **Prepared experiment directory** — Configuration source, from aws-fis-experiment-prepare or manually created.

## Key CLI Commands

### Check Stack Status
```bash
aws cloudformation describe-stacks \
  --stack-name "{STACK_NAME}" \
  --region {REGION} \
  --query 'Stacks[0].{StackStatus: StackStatus, Outputs: Outputs}'
```

### Extract Template ID from Stack Outputs
```bash
TEMPLATE_ID=$(aws cloudformation describe-stacks \
  --stack-name "{STACK_NAME}" \
  --query 'Stacks[0].Outputs[?OutputKey==`ExperimentTemplateId`].OutputValue' \
  --output text --region {REGION})
```

### Start Experiment
```bash
aws fis start-experiment \
  --experiment-template-id "{TEMPLATE_ID}" \
  --region {REGION}
```

### Get Experiment Status
```bash
aws fis get-experiment \
  --id "{EXPERIMENT_ID}" \
  --region {REGION} \
  --query 'experiment.state.status'
```

### Stop Experiment (Emergency)
```bash
aws fis stop-experiment --id "{EXPERIMENT_ID}" --region {REGION}
```

## Cleanup Guide

### CFN Cleanup (Recommended)
```bash
aws cloudformation delete-stack --stack-name "{STACK_NAME}" --region {REGION}
aws cloudformation wait stack-delete-complete --stack-name "{STACK_NAME}" --region {REGION}
```

### Manual Resource Cleanup (if needed)
```bash
aws fis delete-experiment-template --id "{TEMPLATE_ID}" --region {REGION}
aws cloudwatch delete-alarms --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" --region {REGION}
aws cloudwatch delete-dashboards --dashboard-names "FIS-{SCENARIO}" --region {REGION}
```

## Error Handling

| Error | Cause | Resolution |
|---|---|---|
| Stack name not found in README | README missing `**CFN Stack:**` field | Check if prepared with recent version of aws-fis-experiment-prepare |
| Stack not found (`ValidationError`) | Stack does not exist or was deleted | Deploy the stack first using aws-fis-experiment-prepare |
| Stack in `CREATE_FAILED` | Stack deployment failed | Check stack events for failure reason, fix and redeploy |
| `ExperimentTemplateId` not in outputs | Stack template missing output | Check cfn-template.yaml for the output definition |
| `AccessDeniedException` | Insufficient permissions | Check IAM permissions for FIS, CloudWatch, CloudFormation |
| `ResourceNotFoundException` on targets | Tagged resources not found | Verify resource tags match experiment template |
| Experiment stuck in `initiating` | IAM role propagation delay | Wait 30 seconds and check again |

## Usage Examples

```
"Execute the FIS experiment in ./2025-03-27-10-30-00-az-power-interruption-my-cluster-EXT1a2b3c4d5e6f7/"
"Run the chaos experiment I just prepared"
"启动 FIS 实验"
"Check if the stack is deployed and run the experiment"
"运行混沌实验，目录在 ./2025-03-27-rds-failover-prod-db-EXTa1b2c3d4e5f6g/"
"执行实验 EXT1a2b3c4d5e6f7"
"run experiment EXTabc123def456"
```

## Key Design Decisions

1. **No deployment — only verification.** This skill assumes the CloudFormation stack has already been deployed (by `aws-fis-experiment-prepare` or manually). It verifies the stack status before proceeding.

2. **Directory resolution from template ID.** When the user provides only a template ID (e.g., `EXT1a2b3c4d5e6f7`), the skill searches the current working directory for directories ending with that ID. This supports the common workflow where the user remembers the template ID from the prepare step but not the full directory name. If no match is found, the user is prompted for the full path.

3. **Stack name from README.** The stack name is extracted from the `**CFN Stack:**` field in the experiment directory's README.md, ensuring consistency with the prepare skill's output.

4. **Explicit confirmation is non-negotiable.** FIS experiments cause real impact. The skill never auto-starts — it always presents a warning with specific resource details and requires the user to type confirmation.

5. **Action display is transparent.** Before proceeding, the skill reads `experiment-template.json`, extracts all action IDs, and displays them. This lets the user verify which fault actions will run.

6. **App discovery before experiment start.** When log collection is enabled, EKS application dependencies are discovered and log collection is started BEFORE the experiment begins. This prevents missing early log entries that may be rotated or overwritten during the experiment.

7. **Log collection is always enabled.** Both application logs and managed service logs are collected by default for every experiment. If kubectl is not available, application log collection degrades gracefully — it is skipped, but managed service logs (EKS control plane, RDS, etc.) are still collected via AWS CLI. No user opt-in required.

8. **Post-experiment baseline is automatic.** After the experiment ends, log collection continues for 3 minutes to capture recovery behavior. This baseline is always collected — no opt-in required.

9. **Continuous monitoring with log insights.** During the experiment, each poll cycle shows both experiment status and per-app error/warning counts from collected logs, giving operators a real-time view of application impact alongside infrastructure status.

10. **Results saved to file.** The experiment results report is written to a timestamped local markdown file, keeping terminal output concise while preserving a full record.

11. **Cleanup is offered, not forced.** After the experiment, cleanup commands are suggested but never executed without confirmation.

## Directory Structure

```
aws-fis-experiment-execute/
├── SKILL.md                              # Main skill definition (agent instructions)
├── README.md                             # This file (English)
├── README_CN.md                          # Chinese version
└── references/
    ├── cli-commands.md                   # AWS CLI command reference
    └── report-template.md               # Experiment results report template
```

## Limitations

- Requires AWS CLI with permissions for FIS, CloudWatch, and CloudFormation.
- Requires kubectl configured for the target EKS cluster (for log collection).
- **Does not deploy infrastructure** — expects the stack to be already deployed.
- Monitoring relies on CLI polling; real-time dashboard requires the user to open the CloudWatch console.
- Application log collection uses `kubectl logs -f` which only captures logs from running pods. Logs from pods terminated during the experiment may be lost unless Container Insights is enabled.
- Auto-discovery of application dependencies relies on endpoint references in pod env vars and ConfigMaps — applications using service discovery or DNS-based resolution may not be detected automatically.

## Related Skills

- [aws-fis-experiment-prepare](../aws-fis-experiment-prepare/) — Generate and deploy experiment configuration (run before this skill)
- [aws-service-chaos-research](../aws-service-chaos-research/) — Research chaos testing scenarios for any AWS service
- [app-service-log-analysis](../app-service-log-analysis/) — Standalone post-hoc application log analysis (this skill now integrates real-time log analysis directly)
- [eks-workload-best-practice-assessment](../eks-workload-best-practice-assessment/) — Assess EKS workload configurations
