---
name: aws-fis-experiment-execute
description: >
  Use when the user wants to run a prepared AWS FIS experiment where the
  CloudFormation stack has already been deployed. Triggers on "execute FIS
  experiment", "run FIS experiment", "start chaos experiment", "启动 FIS 实验",
  "运行混沌实验", "执行故障注入实验", "run the experiment in [directory]".
  Reads README.md from the experiment directory to extract the CFN stack name,
  verifies the stack is deployed successfully, extracts the experiment template
  ID from stack outputs, then starts the experiment with strict user
  confirmation, monitors progress, and generates results report.
  Does NOT deploy infrastructure — only checks that it is already deployed.
---

# AWS FIS Experiment Execute

Verify that infrastructure is already deployed, run an AWS FIS experiment,
monitor its progress, and generate a results report. Reads configuration from
a prepared experiment directory whose CloudFormation stack has already been
deployed.

## Output Language Rule

Detect the language of the user's conversation and use the **same language** for all output.
- Chinese input -> Chinese output
- English input -> English output

## Prerequisites

Required tools:
- **AWS CLI** — `aws fis`, `aws cloudwatch`, `aws cloudformation`
- **kubectl** — configured with access to target EKS cluster (for app log collection)
- A prepared experiment directory (from aws-fis-experiment-prepare skill)
- The CloudFormation stack for this experiment **must already be deployed**

## Workflow

```dot
digraph execute_flow {
    "Load experiment directory" [shape=box];
    "Validate files" [shape=box];
    "Read README for stack name" [shape=box];
    "Check CFN stack status" [shape=diamond];
    "Extract template ID from outputs" [shape=box];
    "Classify experiment type" [shape=diamond];
    "Discover apps + start logs\n(eks-app-log-analysis)" [shape=box];
    "User wants app logs?" [shape=diamond];
    "Baseline logs? (user opt-in)" [shape=diamond];
    "Wait 2 min baseline" [shape=box];
    "User confirms experiment start" [shape=diamond, style=bold, color=red];
    "Start experiment" [shape=box];
    "Monitor experiment + log insights" [shape=box];
    "Monitor experiment (no logs)" [shape=box];
    "Experiment complete?" [shape=diamond];
    "Post-baseline? (user opt-in)" [shape=diamond];
    "Wait 2 min post-baseline" [shape=box];
    "Stop logs + analyze\n(eks-app-log-analysis)" [shape=box];
    "Generate results report" [shape=box];

    "Load experiment directory" -> "Validate files";
    "Validate files" -> "Read README for stack name";
    "Read README for stack name" -> "Check CFN stack status";
    "Check CFN stack status" -> "Extract template ID from outputs" [label="CREATE_COMPLETE"];
    "Check CFN stack status" -> "Generate results report" [label="Not deployed / failed, abort"];
    "Extract template ID from outputs" -> "Classify experiment type";
    "Classify experiment type" -> "Discover apps + start logs\n(eks-app-log-analysis)" [label="POD / MIXED"];
    "Classify experiment type" -> "User wants app logs?" [label="INFRA"];
    "User wants app logs?" -> "Discover apps + start logs\n(eks-app-log-analysis)" [label="Yes"];
    "User wants app logs?" -> "User confirms experiment start" [label="No (default)"];
    "Discover apps + start logs\n(eks-app-log-analysis)" -> "Baseline logs? (user opt-in)";
    "Baseline logs? (user opt-in)" -> "Wait 2 min baseline" [label="Yes"];
    "Baseline logs? (user opt-in)" -> "User confirms experiment start" [label="No (default)"];
    "Wait 2 min baseline" -> "User confirms experiment start";
    "User confirms experiment start" -> "Start experiment" [label="Yes, I confirm"];
    "User confirms experiment start" -> "Stop logs + analyze\n(eks-app-log-analysis)" [label="No, abort\n(if logs active)"];
    "Start experiment" -> "Monitor experiment + log insights" [label="Logs active"];
    "Start experiment" -> "Monitor experiment (no logs)" [label="Logs skipped"];
    "Monitor experiment + log insights" -> "Experiment complete?";
    "Monitor experiment (no logs)" -> "Experiment complete?";
    "Experiment complete?" -> "Monitor experiment + log insights" [label="No, poll again\n(logs active)"];
    "Experiment complete?" -> "Monitor experiment (no logs)" [label="No, poll again\n(logs skipped)"];
    "Experiment complete?" -> "Post-baseline? (user opt-in)" [label="Yes (logs active)"];
    "Experiment complete?" -> "Generate results report" [label="Yes (logs skipped)"];
    "Post-baseline? (user opt-in)" -> "Wait 2 min post-baseline" [label="Yes"];
    "Post-baseline? (user opt-in)" -> "Stop logs + analyze\n(eks-app-log-analysis)" [label="No (default)"];
    "Wait 2 min post-baseline" -> "Stop logs + analyze\n(eks-app-log-analysis)";
    "Stop logs + analyze\n(eks-app-log-analysis)" -> "Generate results report";
}
```

### Step 1: Load and Validate Experiment Directory

The user provides the path to the experiment directory. Verify it contains the
required files:

```bash
EXPERIMENT_DIR="{USER_PROVIDED_PATH}"

# Required files
ls "${EXPERIMENT_DIR}/experiment-template.json"
ls "${EXPERIMENT_DIR}/iam-policy.json"
ls "${EXPERIMENT_DIR}/cfn-template.yaml"
ls "${EXPERIMENT_DIR}/README.md"

# Optional files
ls "${EXPERIMENT_DIR}/alarms/stop-condition-alarms.json" 2>/dev/null
ls "${EXPERIMENT_DIR}/alarms/dashboard.json" 2>/dev/null
```

### Step 2: Read README and Extract Stack Information

Read `README.md` from the experiment directory to extract:

1. **CFN Stack Name** — look for the line `**CFN Stack:** {STACK_NAME}` in the
   README header block (near the top, after the H1 heading). This is the stack
   name assigned by `aws-fis-experiment-prepare` during deployment.
2. **Scenario name** — from the H1 heading (e.g., `# FIS Experiment: AZ Power Interruption`)
3. **Target region** — from `**Region:** {REGION}`
4. **Target AZ** — from `**Target AZ:** {AZ_ID}` (if applicable)
5. **Estimated duration** — from `**Estimated Duration:** {DURATION}`
6. **Affected resources** — from the "Affected Resources" table

Present a summary to the user with all extracted information.

**If the CFN Stack Name cannot be found in the README**, stop and inform the
user that the stack name is missing. The experiment cannot proceed without it.

### Step 3: Check CloudFormation Stack Status

Using the stack name and region extracted from the README, verify the stack is deployed.
See `references/cli-commands.md` for CLI commands and stack status reference.

Only proceed if the stack is in a ready state (`CREATE_COMPLETE` or `UPDATE_COMPLETE`).

**If the stack is not ready**, inform the user clearly:
- Show the current stack status and failure reason (if applicable)
- Suggest running `aws-fis-experiment-prepare` to deploy the stack
- Do NOT attempt to deploy the stack — this skill only checks and executes

### Step 4: Extract Experiment Template ID from Stack Outputs

Extract `ExperimentTemplateId` from stack outputs. See `references/cli-commands.md` for CLI commands.

**If `ExperimentTemplateId` is not found**, list all outputs and ask the user which one contains the template ID. Common alternatives: `FISExperimentTemplateId`, `TemplateId`.

Also extract dashboard URL and alarm ARNs if available.

### Step 5: Classify Experiment Type (CRITICAL — MUST complete before Step 6)

**You MUST complete this classification BEFORE proceeding to Step 6.** The classification
result determines whether Step 6 collects application logs or asks the user first.
Do NOT skip this step. Do NOT assume the experiment type.

Read `experiment-template.json` from the experiment directory. Extract all `actionId`
values from the `actions` map. Classify the experiment into one of three types:

- **`POD_EXPERIMENT`** — ALL `actionId` values match `aws:eks:pod-*`
- **`MIXED_EXPERIMENT`** — some `actionId` values match `aws:eks:pod-*` AND some do not
- **`INFRA_EXPERIMENT`** — NO `actionId` values match `aws:eks:pod-*` (e.g., `aws:ec2:*`,
  `aws:network:*`, `aws:eks:terminate-nodegroup-instances`,
  `aws:eks:inject-kubernetes-custom-resource`, `aws:fis:inject-*`, `aws:rds:*`, or any
  other non-pod action)

For **Scenario Library templates** (where actions may be opaque or use custom resource
injection): if the scenario name or README description indicates pod-level fault injection,
classify as `POD_EXPERIMENT`. Otherwise default to `INFRA_EXPERIMENT`.

Display the classification to the user:
```
Experiment type: {POD_EXPERIMENT | MIXED_EXPERIMENT | INFRA_EXPERIMENT}
Actions found:
  - {actionId_1}
  - {actionId_2}
  ...
```

### Step 6: Decide and Execute Log Collection

Check the experiment type from Step 5 and follow **exactly one** of the three paths below.
**Read the experiment type first, then jump to the matching section. Do NOT read all
three paths sequentially.**

**If `INFRA_EXPERIMENT`:** go to Step 6a.
**If `MIXED_EXPERIMENT`:** go to Step 6b.
**If `POD_EXPERIMENT`:** go to Step 6c.

---

#### Step 6a: INFRA_EXPERIMENT — Ask User About Log Collection

**STOP. Do NOT load `eks-app-log-analysis` yet.** Do NOT proceed to Step 7.
Do NOT decide for the user. You MUST present the question below and wait for
the user to type a response — just like the experiment confirmation in Step 7.

Present this question to the user and **stop output to wait for their reply**:

```
This experiment targets infrastructure components (not pods directly).
Would you like to collect application logs to observe upstream impact?
(Infrastructure faults may cascade to application-level errors such as
connection timeouts and failover retries.)

Type "yes" to collect application logs, or "no" to skip.
```

**Do NOT continue until the user has responded.** This is a mandatory interaction
point — you cannot choose on behalf of the user.

- If the user answers **yes**: proceed to Step 6c below to load `eks-app-log-analysis`
  and start log collection. Set `LOG_COLLECTION=ACTIVE`.
- If the user answers **no**: set `LOG_COLLECTION=SKIPPED`.
  **Skip Step 6c entirely.** Proceed directly to Step 7.

---

#### Step 6b: MIXED_EXPERIMENT — Inform User, Then Collect Logs

Inform the user:

```
This is a mixed experiment targeting both pods and infrastructure.
App log collection is enabled by default.
```

Then proceed to Step 6c below to start log collection.

---

#### Step 6c: Start Log Collection (POD_EXPERIMENT, or opted-in INFRA/MIXED)

Load the `eks-app-log-analysis` skill now. Execute its real-time mode steps:

1. **Its Step 3 (Collect Application Dependencies)** — auto-discover EKS apps depending on
   affected AWS services (from README's "Affected Resources" table), then confirm with user
2. **Its Step 4 (Log Collection — Real-time Mode)** — start background `kubectl logs -f`
   for all confirmed applications

Set `LOG_COLLECTION=ACTIVE`.

This step runs **BEFORE** the experiment starts — discovering applications after the
experiment begins risks missing early log entries that get rotated or overwritten.

#### Optional: Baseline Log Collection (User Opt-In)

**Applies only when `LOG_COLLECTION=ACTIVE`.** Default: skip baseline.
Only collect baseline logs if the user explicitly requests "collect baseline logs" or
"capture pre/post experiment logs" or similar.

If opted in: wait 2 minutes after starting log collection to capture normal-state logs
as baseline, then proceed to experiment confirmation.

### Step 7: Start Experiment (CRITICAL CONFIRMATION)

**This is the most dangerous step. The experiment WILL affect real resources.**

Before starting, present a clear warning:

```
WARNING: Starting this FIS experiment will cause REAL impact:

Scenario:    {SCENARIO_NAME}
Region:      {REGION}
Target AZ:   {AZ_ID}
Duration:    {DURATION}
Stack:       {STACK_NAME} (verified: CREATE_COMPLETE)
Template ID: {TEMPLATE_ID}
Experiment type: {POD_EXPERIMENT | MIXED_EXPERIMENT | INFRA_EXPERIMENT}

Resources that WILL be affected:
  - {list each affected resource type and count from README}

Applications being monitored:
  - {list each namespace/deployment from SERVICE_APP_MAP}
  (or "None — log collection skipped" if INFRA_EXPERIMENT with no opt-in)

Stop Conditions:
  - {list each alarm that will stop the experiment}

Log collection: ACTIVE (collecting to {LOG_DIR})
               — OR —
Log collection: SKIPPED (infrastructure experiment)

Type "Yes, start experiment" to proceed, or "No" to abort.
```

**Only proceed if the user explicitly confirms.** If user aborts and log collection is
active, still proceed to Step 9 to stop log collection and generate whatever report is
possible.

Save the returned `experiment.id`.

### Step 8: Monitor Experiment + Log Insights

Poll the experiment status and display progress. See `references/cli-commands.md` for
polling commands and experiment status reference.

**Polling strategy:**
- Poll every 30 seconds for the first 5 minutes
- Poll every 60 seconds after that
- Show current status after each poll
- **Record timestamps** for each status change and action state transition — these
  feed into the per-service timeline in the final report
- **Track per-service events**: For each service affected by the experiment, note when
  it was impacted (action started), when it recovered, and any intermediate states.
  Query service-specific status (e.g., RDS instance status, ElastiCache replication
  group status, EKS node status) during monitoring to capture detailed observations.

**Log insights during each poll cycle (only when `LOG_COLLECTION=ACTIVE`):** Execute
`eks-app-log-analysis` Step 5 (Real-time Monitoring Display) — read recent logs, count
errors/warnings, display per-app summary, detect recovery signals. The skill must already
be loaded from Step 6c. If `LOG_COLLECTION=SKIPPED`, skip this paragraph entirely —
monitor only experiment status and service states.

**During monitoring, remind the user:**
- Check the CloudWatch dashboard for real-time metrics
- The experiment can be stopped at any time (see `references/cli-commands.md` for stop command)

### Step 9: Stop Log Collection and Analyze

After the experiment completes (any terminal state):

**If `LOG_COLLECTION=SKIPPED`**, skip this entire step and proceed directly to Step 10.

#### Optional: Post-Experiment Baseline (User Opt-In)

**Default: stop immediately.** Only continue collecting post-experiment logs if the
user opted in to baseline collection in Step 6c.

If opted in: wait 2 minutes after experiment ends to capture recovery behavior logs,
then stop collection.

#### Generate Application Log Analysis

Execute `eks-app-log-analysis` Steps 7-8 (skill already loaded from Step 6c):
- **Its Step 7 (Generate Analysis Report)** — analyze error patterns, peak rates, recovery
  times, and generate the "Application Log Analysis" section of the report
- **Its Step 8 (Cleanup)** — kill background `kubectl logs` processes

The application log analysis output is embedded into the experiment results report
(see Step 10 below), NOT saved as a separate file.

### Step 10: Save Results Report to Local File

After the experiment completes (any terminal state), generate a results report and
**write it directly to a local markdown file** instead of outputting the full content
to the terminal. Use the following file naming convention:

```bash
TIMESTAMP=$(date +%Y-%m-%d-%H-%M-%S)
SCENARIO_SLUG=$(echo "{SCENARIO_NAME}" | tr '[:upper:]' '[:lower:]' | tr ' :/' '-')
# File name: ${TIMESTAMP}-${SCENARIO_SLUG}-experiment-results.md
# Save the file in the current working directory (where the user invoked the skill),
# NOT in the experiment directory
```

**Timeline emphasis:** Timestamps in the report header (Start Time, End Time) use full
ISO 8601 with timezone (e.g., `2025-03-30T14:05:32+08:00`). However, in timeline tables
and action results, use **time-only format in UTC** (e.g., `05:05:32`) — the report date
is already in the header, so repeating the date on every row adds clutter. Mark the
column header as "Time (UTC)" so the timezone is clear. No milliseconds anywhere. Timeline events are embedded directly
into each service's impact analysis section — do NOT create a separate standalone
timeline section. This allows readers to see the full picture (timeline + impact +
findings) for each service without jumping between sections.

**Per-service analysis:** Identify all services affected by the experiment from the
README's "Affected Resources" table. For each service, create a sub-section under
"Per-Service Impact Analysis" that includes: (1) the timeline events relevant to that
service, (2) observed behavior from monitoring, (3) key findings. Also check for
indirectly affected services (e.g., MSK affected by network disruption) and include
them.

The results report file must include:

```markdown
## FIS Experiment Results

**Experiment ID:** {EXPERIMENT_ID}
**Template ID:**   {TEMPLATE_ID}
**Stack:**         {STACK_NAME}
**Status:**        {FINAL_STATUS}
**Start Time:**    {START_TIME}
**End Time:**      {END_TIME}
**Duration:**      {ACTUAL_DURATION}

### Action Results

| Action | Action ID | Status | Start (UTC) | End (UTC) | Duration |
|---|---|---|---|---|---|
| {action_name} | {action_id} | {status} | {HH:MM:SS} | {HH:MM:SS} | {duration} |

### Stop Condition Alarms

| Alarm | Final Status |
|---|---|
| {alarm_name} | {OK/ALARM} |

### Per-Service Impact Analysis

For EACH service listed in the README's "Affected Resources" table, create a sub-section below.
Also include indirectly affected services (e.g., services impacted by network
disruption even without a dedicated FIS action).

#### {Service Name} ({resource_identifier})

| Time (UTC) | Event | Observation |
|---|---|---|
| {HH:MM:SS} | {event} | {what was observed at this point} |
| {HH:MM:SS} | {event} | {observed result / status change} |
| ... | ... | ... |

**Key Findings:**
- {finding_1 — what happened and why}
- {finding_2 — recovery behavior}

(Repeat for each service)

### Application Log Analysis

**If log collection was active:** Embed the analysis output from eks-app-log-analysis
Step 7 here. Use the report structure defined in eks-app-log-analysis SKILL.md:
Summary table, per-application error timeline, key error patterns,
log samples, insights, cross-service correlation, and recommendations.

**If log collection was skipped:** Replace this section with:
> Application log collection was not performed for this infrastructure-focused experiment.
> To collect application logs for future runs of this experiment, answer "y" when prompted
> during experiment setup.

### Recovery Status Summary

| Resource | Recovery Status | Notes |
|---|---|---|
| {service} | {Recovered / Partially Recovered / Recovering} | {details} |

### Issues Requiring Attention

#### 1. {Issue title}
- **Problem:** {description}
- **Recommendation:** {action to take, with CLI command if applicable}

### Cleanup

{cleanup instructions with CLI commands — reference the stack name for CFN cleanup}

### Appendix: Log File Locations

**If log collection was active:**

**Raw log directory:** `{LOG_DIR}`

| Application | Log File |
|---|---|
| {namespace/deployment} | `{LOG_DIR}/{service}/{deployment}.log` |

**If log collection was skipped:** Omit this section entirely.
```

After saving the file, print a brief summary to the terminal listing only:
- The file path of the saved results report
- Experiment ID and final status
- Start time, end time, and duration (all timestamps in ISO 8601 with timezone)
- Experiment type (POD_EXPERIMENT / MIXED_EXPERIMENT / INFRA_EXPERIMENT)
- Per-action status (one line each)
- Per-service recovery status (one line each)
- Application log summary (total errors per app, one line each) — or
  "Application log collection: SKIPPED" if logs were not collected
- Issues requiring attention (if any)
- Cleanup instructions

## Safety Rules

1. **Never auto-start experiments.** Always require explicit user confirmation.
2. **Show every CLI command** before executing it.
3. **Display impact warning** before experiment start with specific resource list.
4. **Provide abort instructions** at every step.
5. **Never delete resources** without user confirmation.
6. **Never deploy infrastructure.** This skill only checks existing deployments.
7. **Recommend dry-run first** — suggest the user review all files before starting.

## Cleanup Guide

After the experiment, offer cleanup. See `references/cli-commands.md` for cleanup commands.

- **CFN Cleanup (Recommended):** Delete the stack to remove all resources
- **Manual Cleanup:** Delete individual resources if they exist outside the stack

## Error Handling

| Error | Cause | Resolution |
|---|---|---|
| Stack name not found in README | README missing `**CFN Stack:**` field | Check if the experiment was prepared with a recent version of aws-fis-experiment-prepare |
| Stack not found (`ValidationError`) | Stack does not exist or was deleted | Deploy the stack first using aws-fis-experiment-prepare |
| Stack in `CREATE_FAILED` / `ROLLBACK_COMPLETE` | Stack deployment failed | Check stack events for failure reason, fix and redeploy |
| `ExperimentTemplateId` not in outputs | Stack template missing output | Check cfn-template.yaml for the output definition |
| `AccessDeniedException` | Insufficient permissions | Check IAM permissions for FIS, CloudWatch, CloudFormation |
| `ResourceNotFoundException` on targets | Tagged resources not found | Verify resource tags match experiment template |
| Experiment stuck in `initiating` | IAM role propagation delay | Wait 30 seconds and check again |
| `kubectl: command not found` | kubectl not installed | Install kubectl and configure kubeconfig |
| `error: You must be logged in` | kubeconfig not configured | Run `aws eks update-kubeconfig --name {cluster}` |
| `/.pids: Permission denied` | `LOG_DIR` variable empty due to `&&` chain | Use multi-line script with `export LOG_DIR=...`, NOT `&&` chains |
| No EKS apps discovered | No pods reference affected service endpoints | Ask user to manually specify namespace/deployment pairs |
