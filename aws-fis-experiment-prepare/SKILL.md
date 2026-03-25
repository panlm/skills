---
name: aws-fis-experiment-prepare
description: >
  Use when the user wants to prepare, create, or generate an AWS FIS (Fault Injection
  Service) experiment configuration. Triggers on "prepare FIS experiment", "create FIS
  experiment for [scenario]", "generate chaos experiment config", "准备 FIS 实验",
  "生成 [scenario] 混沌实验配置", "create experiment template for AZ power interruption",
  "set up fault injection test". Supports both FIS Scenario Library pre-built scenarios
  (AZ Power Interruption, AZ Application Slowdown, etc.) and custom single FIS actions
  (aws:rds:failover-db-cluster, aws:ec2:stop-instances, etc.). Generates all files
  needed to run the experiment: JSON template, IAM policy, CloudFormation template,
  CloudWatch alarms, dashboard, and expected-behavior documentation. After generating
  files, automatically deploys the CFN template with self-healing iteration — if
  deployment fails, analyzes the error, fixes the template, deletes the failed stack,
  and retries until the deployment succeeds (up to 5 retries).
---

# AWS FIS Experiment Prepare

Generate all configuration files needed to run an AWS FIS experiment, then **deploy
via CloudFormation with self-healing iteration** until the stack succeeds. Outputs a
self-contained directory with experiment template, IAM policy, CloudFormation template,
monitoring config, and expected-behavior documentation — plus a deployed, validated
CFN stack ready for experiment execution.

## Output Language Rule

Detect the language of the user's conversation and use the **same language** for all
output files (README.md, expected-behavior.md, comments in JSON/YAML).
- Chinese input -> Chinese output
- English input -> English output
- Mixed -> follow the dominant language

## Prerequisites

Required tools:
- **AWS CLI** — `aws fis list-actions`, resource discovery commands
- **aws___search_documentation** / **aws___read_documentation** — FIS docs research
- **jq** — JSON processing (optional but recommended)

## Workflow

### Step 1: Identify Scenario and Region

#### Scenario Detection

Determine whether the user wants a **Scenario Library** pre-built scenario or a
**custom FIS action**.

**Scenario Library scenarios** (composite, multi-action):
- AZ Availability: Power Interruption
- AZ: Application Slowdown
- Cross-AZ: Traffic Slowdown
- Cross-Region: Connectivity
- EC2 stress: instance failure / CPU / Memory / Disk / Network Latency
- EKS stress: Pod Delete / CPU / Disk / Memory / Network latency
- EBS: Sustained / Increasing / Intermittent / Decreasing Latency

**Custom FIS actions** (single action):
- User specifies an action ID like `aws:rds:failover-db-cluster`
- Or describes what they want to test and you map it to an action

If ambiguous, ask the user to clarify.

#### Region Detection

Same as aws-service-chaos-research — use this order:
1. User explicitly specifies
2. Infer from context (ARNs, previous conversation)
3. `aws configure get region`
4. Ask the user

Store as `TARGET_REGION`.

### Step 2: Discover Target Resources

#### For Scenario Library Scenarios

Read the scenario documentation to understand required targets and tags.
Use `aws___read_documentation` to fetch the scenario detail page:

| Scenario | Documentation URL |
|---|---|
| AZ Power Interruption | `https://docs.aws.amazon.com/fis/latest/userguide/az-availability-scenario.html` |
| AZ Application Slowdown | `https://docs.aws.amazon.com/fis/latest/userguide/az-application-slowdown-scenario.html` |
| Cross-AZ Traffic Slowdown | `https://docs.aws.amazon.com/fis/latest/userguide/cross-az-traffic-slowdown-scenario.html` |
| Cross-Region Connectivity | `https://docs.aws.amazon.com/fis/latest/userguide/cross-region-scenario.html` |

From the documentation, extract:
- **Required resource tags** (e.g., `AzImpairmentPower: StopInstances`)
- **Target resource types** (EC2 instances, RDS clusters, subnets, etc.)
- **Required parameters** (AZ, duration, etc.)
- **Sub-actions** and their individual targets

**Ask the user:**
1. Which AZ to target (for AZ-level scenarios)
2. Resource identification method:
   - Tags already applied? Which tag key/value?
   - Use default scenario tags? (user must tag resources first)
   - Specific resource ARNs?
3. For RDS/ElastiCache: cluster identifiers
4. For EC2: instance IDs or ASG names
5. For EKS: cluster name, namespace, pod labels

#### For Custom FIS Actions

Verify the action exists:
```bash
aws fis get-action --id "ACTION_ID" --region TARGET_REGION
```

Extract from the action:
- Required `targets` (resource types, e.g., `aws:rds:cluster`, `aws:ec2:instance`)
- Required `parameters` (duration, percentage, etc.)
- Ask the user for target resource details

### Step 3: Validate Resource-Action Compatibility

**This step is CRITICAL.** Before generating any files, verify that the user's actual
resources are compatible with the chosen FIS action(s). Skipping this step leads to
wasted effort — generating templates, deploying CFN stacks, only to discover at
experiment start that the action cannot target the resource.

#### 3a. Inspect the Actual Resource

Use AWS CLI to query the real resource and determine its exact type, engine, and
configuration:

| User Says | CLI Command | Key Fields to Check |
|---|---|---|
| RDS database name/ID | `aws rds describe-db-instances --db-instance-identifier {ID}` | `Engine`, `DBClusterIdentifier` (null = standalone RDS, non-null = Aurora cluster member) |
| RDS/Aurora cluster | `aws rds describe-db-clusters --db-cluster-identifier {ID}` | `Engine`, `EngineMode`, `MultiAZ` |
| EC2 instance | `aws ec2 describe-instances --instance-ids {ID}` | `InstanceType`, `State`, `Placement.AvailabilityZone` |
| EKS cluster | `aws eks describe-cluster --name {NAME}` | `status`, `version`, `resourcesVpcConfig` |
| ElastiCache | `aws elasticache describe-replication-groups --replication-group-id {ID}` | `NodeGroupConfiguration`, `MultiAZ`, `AutomaticFailover` |
| ASG | `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {NAME}` | `AvailabilityZones`, `Instances` |

#### 3b. Cross-Check Against FIS Action Requirements

Get the FIS action's required target resource type:

```bash
aws fis get-action --id "ACTION_ID" --region TARGET_REGION \
  --query 'action.targets' --output json
```

This returns the expected `resourceType` (e.g., `aws:rds:cluster` for
`aws:rds:failover-db-cluster`).

**Common incompatibility traps:**

| FIS Action | Required resourceType | Incompatible With | How to Detect |
|---|---|---|---|
| `aws:rds:failover-db-cluster` | `aws:rds:cluster` | Standalone RDS instances (non-Aurora) | `describe-db-instances`: `DBClusterIdentifier` is null |
| `aws:rds:reboot-db-instances` | `aws:rds:db` | Aurora clusters (use failover instead) | `describe-db-instances`: `Engine` starts with `aurora` |
| `aws:elasticache:replicationgroup-interrupt-az-power` | `aws:elasticache:replicationgroup` | Standalone ElastiCache nodes (no replication group) | `describe-cache-clusters`: `ReplicationGroupId` is null |
| `aws:ec2:stop-instances` | `aws:ec2:instance` | Spot instances (may terminate instead of stop) | `describe-instances`: `InstanceLifecycle` = `spot` |
| `aws:eks:pod-network-latency` | `aws:eks:pod` | EKS clusters without Chaos Mesh or FIS agent | `describe-cluster`: check addon list |

#### 3c. Decision Gate

```dot
digraph compat_check {
    "Resource matches action resourceType?" [shape=diamond];
    "Proceed to Step 4" [shape=box];
    "Suggest alternative action" [shape=box];
    "User confirms alternative?" [shape=diamond];
    "Abort and explain" [shape=box, style=bold, color=red];

    "Resource matches action resourceType?" -> "Proceed to Step 4" [label="Yes"];
    "Resource matches action resourceType?" -> "Suggest alternative action" [label="No"];
    "Suggest alternative action" -> "User confirms alternative?";
    "User confirms alternative?" -> "Proceed to Step 4" [label="Yes, use alternative"];
    "User confirms alternative?" -> "Abort and explain" [label="No"];
}
```

**If incompatible:**

1. **Explain clearly** what the mismatch is:
   > "The action `aws:rds:failover-db-cluster` requires an Aurora cluster
   > (`aws:rds:cluster`), but your database `mydb` is a standalone RDS MySQL
   > instance (Engine: mysql, no DBClusterIdentifier). This action cannot
   > target standalone RDS instances."

2. **Suggest alternatives** based on the actual resource type:
   - Standalone RDS Multi-AZ -> `aws:rds:reboot-db-instances` with `--force-failover`
   - Standalone RDS Single-AZ -> explain no failover is possible, suggest `aws:ec2:stop-instances` on the underlying host
   - Aurora cluster -> `aws:rds:failover-db-cluster`
   - ElastiCache standalone -> explain replication group is required

3. **Ask the user** whether to proceed with the alternative action or abort.

**If compatible:** proceed to Step 4.

#### 3d. For Scenario Library Scenarios

For composite scenarios (e.g., AZ Power Interruption), validate EACH sub-action
against its respective target resources. For example:
- RDS sub-action: verify the user's RDS resource is actually an Aurora cluster
- ElastiCache sub-action: verify the user's cache is a replication group
- EC2 sub-action: verify instances exist in the target AZ

Sub-actions with no matching resources are automatically skipped by FIS (this is
fine), but if the user's **primary** resource fails validation, stop and report.

### Step 4: Determine Monitoring Configuration

Based on the scenario and affected services, determine:

#### Stop Condition Alarms

For each affected service, identify the critical metric that should trigger an
experiment stop if things go wrong beyond expectations:

| Service | Metric | Namespace | Threshold Logic |
|---|---|---|---|
| EC2 | `StatusCheckFailed` | AWS/EC2 | > 0 on non-target instances |
| RDS | `DatabaseConnections` | AWS/RDS | drops to 0 for > 5 min |
| EKS | `pod_number_of_running_pods` | ContainerInsights | < expected count |
| ElastiCache | `ReplicationLag` | AWS/ElastiCache | > 60 seconds |
| ALB | `HTTPCode_ELB_5XX_Count` | AWS/ApplicationELB | > threshold |
| Application | User-defined | Custom | User-defined |

Ask the user:
- Do you have existing CloudWatch alarms to use as stop conditions?
- What is your application's error rate threshold?
- Any custom metrics to monitor?

#### Dashboard Metrics

For observation during the experiment, include:
- All stop condition metrics
- Service-specific health metrics
- Application-level metrics (if provided)
- Experiment status (manual check via CLI)

### Step 5: Generate Configuration Files

Create the output directory:
```bash
SCENARIO_SLUG=$(echo "SCENARIO_NAME" | tr '[:upper:]' '[:lower:]' | tr ' :' '-' | tr -d ',')
TIMESTAMP=$(date +%Y-%m-%d-%H-%M-%S)
OUTPUT_DIR="./${SCENARIO_SLUG}-${TIMESTAMP}"
mkdir -p "${OUTPUT_DIR}/alarms"
```

Generate files following the templates in `references/output-structure.md`:

1. **experiment-template.json** — FIS experiment template for CLI creation
2. **iam-policy.json** — IAM permissions needed by the FIS execution role
3. **cfn-template.yaml** — CloudFormation template containing ALL resources:
   - IAM Role + Policy
   - CloudWatch Alarms (stop conditions)
   - CloudWatch Dashboard
   - FIS Experiment Template
4. **alarms/stop-condition-alarms.json** — Standalone alarm definitions
5. **alarms/dashboard.json** — CloudWatch dashboard body
6. **expected-behavior.md** — Detailed expected behavior documentation
7. **README.md** — Experiment overview and execution instructions

See `references/output-structure.md` for exact file formats.
See `references/scenario-templates.md` for Scenario Library JSON templates.

### Step 6: Deploy CFN Template (Self-Healing Loop)

After generating all files, **immediately attempt to deploy the CFN template** to
validate that the generated configuration actually works. If deployment fails, analyze
the error, fix the template, delete the failed stack, and retry — repeating until the
deployment succeeds.

**This step ensures the user receives a working, validated configuration — not just
files that might contain errors.**

#### 6a. Validate Template Syntax First

```bash
aws cloudformation validate-template \
  --template-body "file://${OUTPUT_DIR}/cfn-template.yaml" \
  --region ${TARGET_REGION}
```

If validation fails, fix the YAML syntax error in `cfn-template.yaml` and re-validate.
Do NOT proceed to deployment until validation passes.

#### 6b. Deploy the Stack

```bash
STACK_NAME="fis-${SCENARIO_SLUG}-$(date +%Y%m%d-%H%M%S)"

aws cloudformation deploy \
  --template-file "${OUTPUT_DIR}/cfn-template.yaml" \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ${TARGET_REGION} \
  --no-fail-on-empty-changeset
```

#### 6c. Self-Healing Iteration Loop

```dot
digraph cfn_loop {
    "Deploy CFN stack" [shape=box];
    "Wait for completion" [shape=box];
    "Deployment succeeded?" [shape=diamond];
    "Extract error from stack events" [shape=box];
    "Analyze root cause" [shape=box];
    "Fix cfn-template.yaml" [shape=box];
    "Delete failed stack" [shape=box];
    "Max retries exceeded?" [shape=diamond];
    "Report failure to user" [shape=box, style=bold, color=red];
    "Save stack outputs" [shape=box];
    "Update local files with real ARNs" [shape=box];

    "Deploy CFN stack" -> "Wait for completion";
    "Wait for completion" -> "Deployment succeeded?";
    "Deployment succeeded?" -> "Save stack outputs" [label="Yes"];
    "Deployment succeeded?" -> "Extract error from stack events" [label="No"];
    "Extract error from stack events" -> "Analyze root cause";
    "Analyze root cause" -> "Fix cfn-template.yaml";
    "Fix cfn-template.yaml" -> "Delete failed stack";
    "Delete failed stack" -> "Max retries exceeded?";
    "Max retries exceeded?" -> "Report failure to user" [label="Yes (>5)"];
    "Max retries exceeded?" -> "Deploy CFN stack" [label="No, retry"];
    "Save stack outputs" -> "Update local files with real ARNs";
}
```

**On deployment failure:**

1. **Get the failure reason** from stack events:
   ```bash
   aws cloudformation describe-stack-events \
     --stack-name "${STACK_NAME}" \
     --region ${TARGET_REGION} \
     --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].{Resource:LogicalResourceId, Reason:ResourceStatusReason}' \
     --output table
   ```

2. **Analyze the root cause.** Common errors and fixes:

   | Error Pattern | Root Cause | Fix |
   |---|---|---|
   | `Property validation failure` | Invalid CFN property name or value | Fix the resource property in YAML |
   | `Template format error` | YAML syntax or structure issue | Fix indentation / structure |
   | `Resource type not supported` | CFN resource type unavailable in region | Check regional availability, use alternative |
   | `Invalid template property` | Wrong property for resource type | Consult CFN docs for correct schema |
   | `Circular dependency` | Resources reference each other | Use `DependsOn` or restructure |
   | `RoleArn ... is invalid` | IAM role not yet propagated | Add `DependsOn` for IAM role |
   | `Limit exceeded` | Account resource limits | Reduce resource count or request limit increase |
   | `AccessDenied` | Caller lacks permissions | Check caller's IAM permissions |

3. **Fix `cfn-template.yaml`** in the output directory based on the error analysis.
   Also update `experiment-template.json` if the fix affects the experiment template
   structure (e.g., changed action parameters, modified targets).

4. **Delete the failed stack** before retrying:
   ```bash
   aws cloudformation delete-stack \
     --stack-name "${STACK_NAME}" \
     --region ${TARGET_REGION}

   aws cloudformation wait stack-delete-complete \
     --stack-name "${STACK_NAME}" \
     --region ${TARGET_REGION}
   ```

5. **Retry deployment** with the fixed template. Use the same stack name.

6. **Maximum 5 retries.** If deployment still fails after 5 attempts, stop and report
   the error to the user with:
   - The last error message
   - All fixes attempted
   - The current state of `cfn-template.yaml`
   - Suggestion to manually review and fix

#### 6d. On Successful Deployment

After the stack deploys successfully:

1. **Extract stack outputs** (Experiment Template ID, Role ARN, Dashboard URL):
   ```bash
   aws cloudformation describe-stacks \
     --stack-name "${STACK_NAME}" \
     --query 'Stacks[0].Outputs' \
     --region ${TARGET_REGION} --output table
   ```

2. **Update `experiment-template.json`** with real ARNs from the stack (role ARN,
   alarm ARNs) so it stays in sync with what was actually deployed.

3. **Update `README.md`** to include:
   - The actual stack name
   - The experiment template ID
   - The CloudWatch dashboard URL
   - Cleanup command for this specific stack

### Step 7: Present Summary

Present to the user:
1. Scenario name and description
2. Target region and AZ
3. Affected resources summary
4. Experiment duration
5. Files generated and their locations
6. **CFN deployment status**: Stack name, deployed resources, experiment template ID
7. **CloudWatch Dashboard URL** for monitoring
8. **Next step**: How to start the experiment
   - Use aws-fis-experiment-execute skill, OR
   - Manually: `aws fis start-experiment --experiment-template-id {ID} --region {REGION}`

## Important Guidelines

- **Never start the FIS experiment in this skill.** This skill deploys the supporting
  infrastructure (IAM role, alarms, dashboard, experiment template) via CloudFormation,
  but does NOT start the actual fault injection experiment. Starting the experiment is
  handled by aws-fis-experiment-execute or manually by the user.
- **Validate resource-action compatibility BEFORE generating files.** Always inspect
  the user's actual resources (describe-db-instances, describe-db-clusters, etc.) and
  cross-check against the FIS action's required `resourceType`. Never assume a resource
  type from its name — always verify via CLI. This is the most common source of wasted
  effort: generating and deploying a template that targets an incompatible resource.
- **Always deploy and validate.** Do not just generate files — deploy the CFN template
  and iterate until it succeeds. The user should receive a working, deployed experiment
  template ready to start.
- **Self-heal on CFN errors.** When deployment fails, read the stack events, diagnose
  the issue, fix the template, delete the failed stack, and retry. Do not ask the user
  to fix CFN errors — fix them yourself.
- **Always verify FIS action availability.** Use `aws fis list-actions` or
  `aws fis get-action` to confirm actions exist in the target region before
  generating templates.
- **Don't fabricate action IDs.** If an action doesn't exist, say so clearly.
- **Resource tags must match.** The experiment template's target tags must match
  what's actually on the user's resources. Confirm with the user.
- **IAM policy must be least-privilege.** Only include permissions for the specific
  actions in the experiment, not broad FIS permissions.
- **CFN template must be self-contained.** A user should be able to deploy the CFN
  template and get a working experiment without any other steps.
- **expected-behavior.md is critical.** This is what the user reads during the
  experiment to know if things are working as expected. Be thorough and specific.
- **Sequential MCP calls.** All `aws___read_documentation` and
  `aws___search_documentation` calls must be sequential, never parallel.
  Retry up to 10 times on rate limit errors.
- **Keep local files in sync.** After successful deployment, update local files
  (experiment-template.json, README.md) with real ARNs and stack outputs so the
  directory is a complete, accurate record of the deployed experiment.
