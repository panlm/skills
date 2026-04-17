---
name: aws-fis-experiment-prepare
description: >
  Use when the user wants to prepare, create, or generate an AWS FIS (Fault
  Injection Service) experiment configuration. Triggers on "prepare FIS
  experiment", "create FIS experiment for [scenario]", "generate chaos
  experiment config", "准备 FIS 实验", "生成 [scenario] 混沌实验配置",
  "create experiment template for AZ power interruption", "set up fault
  injection test". Covers Scenario Library pre-built scenarios (AZ Power
  Interruption, AZ Application Slowdown, Cross-AZ Traffic Slowdown,
  Cross-Region Connectivity), custom single FIS actions
  (aws:rds:failover-db-cluster, aws:ec2:stop-instances, etc.), and SSM
  Automation-based fault injection for Amazon MSK (broker reboot).
---

# AWS FIS Experiment Prepare

Generate all configuration files needed to run an AWS FIS experiment, then
deploy via CloudFormation with self-healing iteration until the stack
succeeds. Outputs a self-contained directory with a validated, deployed
experiment template ready for execution.

**Core principle:** Validate resource-action compatibility before generating
files. Never deliver untested configuration — deploy and self-heal first.

## References

**Always load for every experiment:**
- `references/output-format.md` — directory layout, slug naming, README template
- `references/cfn-base-template.md` — CFN skeleton (Parameters, IAM Role,
  Dashboard, FIS Template, Outputs)
- `references/slug-conventions.md` — scenario/context slug abbreviations,
  resource naming, name length budget

**Load conditionally:**
- `references/az-power-interruption-guide.md` — when scenario is AZ Power
  Interruption (sub-action pruning, tagging strategy, permissions)
- `references/eks-pod-action-guide.md` — when any `aws:eks:pod-*`
  action is used (RBAC Lambda, EKS Access Entry, Pod memory stress
  calculation)
- `references/msk-guide.md` — when the experiment targets Amazon MSK
  (broker reboot via SSM Automation — no native FIS action exists)

**Utility scripts (execute, do not read as reference):**
- `scripts/precheck-cfn-permissions.sh` — detects required CFN service role
- `scripts/deploy-with-retry.sh` — validate + deploy + delete-on-fail
- `scripts/rename-output-dir.sh` — appends FIS template ID to directory name

**Script invocation:** In examples below, `${SKILL_DIR}` refers to the
absolute path of this skill's directory (where SKILL.md lives). Resolve it
from the skill's filesystem location before running any scripts.

## Output Language Rule

Detect the language of the user's conversation and use the **same language**
for all output files (README.md, comments in JSON/YAML).
- Chinese input → Chinese output
- English input → English output
- Mixed → follow the dominant language

## Prerequisites

Required tools:
- **AWS CLI** — `aws fis list-actions`, resource discovery, CloudFormation
- **aws___search_documentation** / **aws___read_documentation** — FIS docs research
- **jq** — JSON processing (required by `scripts/deploy-with-retry.sh` and
  `scripts/precheck-cfn-permissions.sh`)

**EKS Pod fault injection:** Cluster authentication mode must be
`API_AND_CONFIG_MAP` or `API`. Check with:
```bash
aws eks describe-cluster --name {CLUSTER} --query 'cluster.accessConfig.authenticationMode'
```
If mode is `CONFIG_MAP` only, the user must update the cluster first.

**MANDATORY:** When using any `aws:eks:pod-*` action, follow
`references/eks-pod-action-guide.md`.

## Workflow

### Step 1: Identify Scenario and Region

**Classify the user intent into one of three branches:**

| Branch | Trigger | Additional Reference |
|---|---|---|
| Scenario Library | User asks for AZ Power Interruption, AZ App Slowdown, Cross-AZ/Region scenarios | Read AWS doc URL (see below) |
| Custom FIS action | User specifies an action ID (`aws:rds:failover-db-cluster` etc.) or describes a single fault | — |
| SSM Automation | Target service has no native FIS action (currently: Amazon MSK) | `references/msk-guide.md` |

If ambiguous, ask the user.

**Scenario Library documentation URLs** (the JSON templates are NOT available
via CLI/API — read the doc to extract):

| Scenario | Documentation URL |
|---|---|
| AZ Power Interruption | `https://docs.aws.amazon.com/en_us/fis/latest/userguide/az-availability-scenario.html` |
| AZ Application Slowdown | `https://docs.aws.amazon.com/en_us/fis/latest/userguide/az-application-slowdown-scenario.html` |
| Cross-AZ Traffic Slowdown | `https://docs.aws.amazon.com/en_us/fis/latest/userguide/cross-az-traffic-slowdown-scenario.html` |
| Cross-Region Connectivity | `https://docs.aws.amazon.com/en_us/fis/latest/userguide/cross-region-scenario.html` |

**Region detection order:**
1. User explicitly specifies
2. Infer from context (ARNs, previous conversation)
3. `aws configure get region`
4. Ask the user

Store as `TARGET_REGION`.

**Default experiment duration: `PT10M` (10 minutes)** for all scenarios and
sub-actions unless the user specifies otherwise. For AZ Power Interruption,
scale ARC Zonal Autoshift timing proportionally (ARC starts at minute 2,
runs for 8 minutes at PT10M; formula: `startAfter = duration × (5/30)`).

### Step 2: Discover Target Resources

#### For Scenario Library Scenarios

**CRITICAL: Scenario Library experiment templates CANNOT be generated via
FIS API.** You MUST call `aws___read_documentation` with the scenario URL
(Step 1 table) to extract the JSON experiment template before generating
any files. The documentation is the only authoritative source.

**Target identification — prefer `resourceArns` over `resourceTags`:**
- Use `resourceArns` (exact ARNs) for most resource types — more precise and
  requires no pre-tagging
- Exception — these types do NOT support `resourceArns`, use `resourceTags`
  instead:
  - `aws:elasticache:replicationgroup`
  - `aws:ec2:autoscaling-group`
- EKS pod actions use Kubernetes namespace + pod labels (neither `resourceArns`
  nor `resourceTags`)

**`resourceArns` and `filters` are mutually exclusive.** FIS rejects targets
that specify both. For AZ-scoped targeting, either use `resourceArns` with
only the target AZ's ARNs, or use `resourceTags` + `filters` together.

**If scenario is AZ Power Interruption:** follow
`references/az-power-interruption-guide.md` for:
- Service-scoped sub-action pruning (blast radius control)
- Tagging strategy via Lambda Custom Resource
- FIS Experiment Role permissions
- One-Stack-per-AZ design

**Ask the user:**
1. Which AZ to target (for AZ-level scenarios)
2. Which services to include (for AZ Power Interruption) — if user mentions
   specific services, include ONLY those + mandatory infrastructure sub-actions
3. Target resource identifiers (cluster IDs, instance IDs, etc.)

#### For Custom FIS Actions

```bash
aws fis get-action --id "ACTION_ID" --region TARGET_REGION
```

Extract required `targets` and `parameters`. Resolve user-provided identifiers
to ARNs via AWS CLI.

#### For Services Without Native FIS Actions (SSM Automation)

1. Confirm no native action exists:
   ```bash
   aws fis list-actions --query "actions[?starts_with(id, 'aws:{SERVICE}:')]" \
     --region TARGET_REGION
   ```

2. If empty, follow the service-specific guide:
   - Amazon MSK → `references/msk-guide.md`
   - Other services without native FIS action → not yet documented in this
     skill. Stop and inform the user that SSM Automation support for the
     requested service has not been added to this skill.

3. Discover resources via the target service's CLI (`aws kafka list-clusters`,
   `aws mq list-brokers`, `aws redshift describe-clusters`, etc.).

### Step 2.5: EKS Pod Action Setup Gate

**If the experiment includes ANY `aws:eks:pod-*` action, complete this gate
BEFORE Step 3.**

Applicable actions: `aws:eks:pod-cpu-stress`, `aws:eks:pod-delete`,
`aws:eks:pod-io-stress`, `aws:eks:pod-memory-stress`,
`aws:eks:pod-network-blackhole-port`, `aws:eks:pod-network-latency`,
`aws:eks:pod-network-packet-loss`.

1. Read the official documentation:
   ```
   aws___read_documentation:
     url: https://docs.aws.amazon.com/fis/latest/userguide/eks-pod-actions.html
   ```

2. Follow ALL requirements in `references/eks-pod-action-guide.md`:
   - Lambda-backed CFN Custom Resource for K8s RBAC (fixed names: `fis-sa`,
     `fis-experiment-role`, `fis-experiment-role-binding`)
   - EKS Access Entry for FIS Experiment Role (`Username: fis-experiment`)
   - Cluster auth mode check (`API_AND_CONFIG_MAP` or `API`)
   - Pod `readOnlyRootFilesystem: false` check
   - Network action limitations (no Fargate, no bridge mode)
   - **Pod memory stress threshold calculation** (if action is
     `aws:eks:pod-memory-stress`) — user's percent is total target, not
     injection value

Do NOT skip. EKS pod actions have complex setup requirements that differ
significantly from other FIS actions.

### Step 3: Validate Resource-Action Compatibility

**CRITICAL GATE.** Before generating any files, verify that the user's actual
resources are compatible with the chosen FIS action(s).

#### 3a. Inspect the Actual Resource

| User Says | CLI Command | Key Fields |
|---|---|---|
| RDS database | `aws rds describe-db-instances --db-instance-identifier {ID}` | `Engine`, `DBClusterIdentifier` |
| RDS/Aurora cluster | `aws rds describe-db-clusters --db-cluster-identifier {ID}` | `Engine`, `EngineMode`, `MultiAZ` |
| EC2 instance | `aws ec2 describe-instances --instance-ids {ID}` | `InstanceType`, `Placement.AvailabilityZone` |
| EKS cluster | `aws eks describe-cluster --name {NAME}` | `accessConfig.authenticationMode`, `version` |
| ElastiCache | `aws elasticache describe-replication-groups --replication-group-id {ID}` | `NodeGroupConfiguration`, `MultiAZ` |
| ASG | `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {NAME}` | `AvailabilityZones`, `Instances` |

#### 3b. Cross-Check Against FIS Action Requirements

```bash
aws fis get-action --id "ACTION_ID" --region TARGET_REGION \
  --query 'action.targets' --output json
```

**Common incompatibility traps:**

| FIS Action | Required resourceType | Incompatible With | How to Detect |
|---|---|---|---|
| `aws:rds:failover-db-cluster` | `aws:rds:cluster` | Standalone RDS (non-Aurora) | `DBClusterIdentifier` is null |
| `aws:rds:reboot-db-instances` | `aws:rds:db` | Aurora clusters | `Engine` starts with `aurora` |
| `aws:elasticache:replicationgroup-interrupt-az-power` | `aws:elasticache:replicationgroup` | Standalone ElastiCache nodes | No replication group |
| `aws:ec2:stop-instances` | `aws:ec2:instance` | Spot instances | `InstanceLifecycle` = `spot` |

#### 3c. Decision Gate

- **Compatible** → proceed to Step 4.
- **Incompatible** → explain the mismatch, suggest alternatives based on the
  actual resource type, ask the user to confirm the alternative or abort.

Example alternatives:
- Standalone RDS Multi-AZ → `aws:rds:reboot-db-instances` with `--force-failover`
- Aurora cluster → `aws:rds:failover-db-cluster`
- ElastiCache standalone → explain replication group is required

#### 3d. For Scenario Library Scenarios

Validate EACH included sub-action against its target resources. Only validate
sub-actions that remain after service-scoped pruning (Step 2).

### Step 4: Determine Monitoring Configuration

**Stop Conditions — default: `source: "none"` (no alarm).** Only create a
CloudWatch Alarm if the user explicitly provides one.

**Dashboard Metrics — comprehensive, per-service.** Group widgets by service,
3 widgets per service (availability, performance, errors/latency). Include
only services actually affected by the experiment.

| Service | Metrics |
|---|---|
| EC2 | `StatusCheckFailed`, `CPUUtilization`, `NetworkIn/Out`, `NetworkPacketsIn/Out` |
| RDS/Aurora | `DatabaseConnections`, `ReadLatency`, `WriteLatency`, `AuroraReplicaLag`, `FreeableMemory` |
| EKS | `pod_number_of_running_pods`, `pod_number_of_container_restarts`, `node_cpu_utilization`, `node_memory_utilization` |
| ElastiCache | `ReplicationLag`, `EngineCPUUtilization`, `CurrConnections`, `CacheHitRate`, `Evictions` |
| ALB | `HealthyHostCount`, `UnHealthyHostCount`, `HTTPCode_ELB_5XX_Count`, `TargetResponseTime` |
| NLB | `ActiveFlowCount`, `TCP_Client_Reset_Count`, `TCP_Target_Reset_Count` |

### Step 5: Generate Configuration Files

**Create output directory:**

```bash
# ─── Fill in from user's request + references/slug-conventions.md ───
SCENARIO_SLUG="..."         # e.g., pod-delete, az-power-int, rds-failover
TARGET_RESOURCE_ID="..."    # e.g., my-aurora-cluster, i-0abc123def
CONTEXT_NAME=""             # optional (e.g., redis, msk); leave empty if not applicable
# ────────────────────────────────────────────────────────────────────

# Derived values (do not edit):
TARGET_SLUG=$(echo "${TARGET_RESOURCE_ID}" | tr '[:upper:]' '[:lower:]' | tr ' :/' '-' | cut -c1-20)
CONTEXT_SLUG=$(echo "${CONTEXT_NAME}" | tr '[:upper:]' '[:lower:]' | tr ' :/' '-' | cut -c1-10)
TIMESTAMP=$(TZ=Asia/Shanghai date +%Y-%m-%d-%H-%M-%S)

if [ -n "${CONTEXT_SLUG}" ]; then
    OUTPUT_DIR="./${TIMESTAMP}-${SCENARIO_SLUG}-${TARGET_SLUG}-${CONTEXT_SLUG}"
else
    OUTPUT_DIR="./${TIMESTAMP}-${SCENARIO_SLUG}-${TARGET_SLUG}"
fi
mkdir -p "${OUTPUT_DIR}"
```

**REQUIRED:** Before generating `cfn-template.yaml`, read the
`AWS::FIS::ExperimentTemplate` CloudFormation resource documentation:

```
aws___read_documentation:
  url: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-fis-experimenttemplate.html
```

**ALSO REQUIRED:** Search for CloudFormation examples for the resources used:

```
aws___search_documentation:
  search_phrase: "<CFN resource types in this experiment>"
  topics: ["cloudformation"]
```

**Generate files:**

1. **cfn-template.yaml** — use `references/cfn-base-template.md` as the
   skeleton. Extend with scenario-specific resources per:
   - `references/az-power-interruption-guide.md` (if AZ Power Interruption)
   - `references/eks-pod-action-guide.md` (if EKS pod actions)
   - `references/msk-guide.md` (if MSK)

2. **README.md** — use the template in `references/output-format.md`.

### Step 5.5: CFN Permission Pre-Check

Run the precheck script to detect whether a CFN service role is required:

```bash
CFN_ROLE_ARN=$("${SKILL_DIR}/scripts/precheck-cfn-permissions.sh")
```

If the caller lacks CloudFormation permissions, the script exits 1 with
guidance — **stop and inform the user**. Otherwise, `CFN_ROLE_ARN` is either
empty (no service role needed) or contains the required role ARN.

### Step 6: Deploy CFN Template (Self-Healing Loop)

**Generate deployment parameters:**

```bash
# See references/slug-conventions.md for the ExperimentName composition rule
RANDOM_SUFFIX=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c6)

if [ -n "${CONTEXT_SLUG}" ]; then
    EXPERIMENT_NAME="${SCENARIO_SLUG}-${TARGET_SLUG}-${CONTEXT_SLUG}-${RANDOM_SUFFIX}"
else
    EXPERIMENT_NAME="${SCENARIO_SLUG}-${TARGET_SLUG}-${RANDOM_SUFFIX}"
fi
STACK_NAME="fis-${EXPERIMENT_NAME}"
```

**Deploy with self-healing retry loop** (maximum 5 attempts driven by the
agent). The `deploy-with-retry.sh` script performs **one attempt** — the
agent drives the loop externally. On each attempt:

1. Run `scripts/deploy-with-retry.sh`:
   ```bash
   "${SKILL_DIR}/scripts/deploy-with-retry.sh" \
     "${OUTPUT_DIR}/cfn-template.yaml" \
     "${STACK_NAME}" \
     "${TARGET_REGION}" \
     "${CFN_ROLE_ARN}" \
     "ExperimentName=${EXPERIMENT_NAME}" \
     "RandomSuffix=${RANDOM_SUFFIX}"
   ```
2. If the script exits 0 → deployment succeeded, proceed to "On Successful
   Deployment" below.
3. If the script exits 1 (validation failed) or 2 (deployment failed, stack
   deleted) → analyze the stderr output, fix `cfn-template.yaml`, increment
   the attempt counter, and re-invoke the script.
4. If 5 attempts exhausted → stop and report to the user with the last error,
   all fixes attempted, and the current state of `cfn-template.yaml`.

**Common CFN errors and fixes:**

| Error Pattern | Root Cause | Fix |
|---|---|---|
| `Property validation failure` | Invalid CFN property name/value | Fix the resource property |
| `Template format error` | YAML syntax issue | Fix indentation/structure |
| `Resource type not supported` | Resource unavailable in region | Check regional availability |
| `Circular dependency` | Resources reference each other | Use `DependsOn` or restructure |
| `RoleArn ... is invalid` | IAM role not yet propagated | Add `DependsOn` for IAM role |
| `Must specify at least one log destination` | AZ Power Interruption doc includes empty `logConfiguration` | Remove the `logConfiguration` block entirely |

#### On Successful Deployment

1. Extract stack outputs:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name "${STACK_NAME}" \
     --query 'Stacks[0].Outputs' \
     --region "${TARGET_REGION}" --output table
   ```

2. Update `README.md` with the actual stack name, template ID, dashboard URL,
   and cleanup command (replace all `{STACK_NAME}` placeholders with the real
   stack name — do NOT leave placeholders in the final output).

### Step 7: Rename Output Directory with Template ID

Run the rename script:

```bash
NEW_OUTPUT_DIR=$("${SKILL_DIR}/scripts/rename-output-dir.sh" \
    "${OUTPUT_DIR}" \
    "${STACK_NAME}" \
    "${TARGET_REGION}")
OUTPUT_DIR="${NEW_OUTPUT_DIR}"
```

Then update `README.md`'s `**Directory:**` field with the full absolute path
of the renamed directory.

If the CFN deployment failed (Step 6 exceeded max retries), skip this step.

Print a brief summary to the terminal:
- Experiment output directory (with template ID)
- CFN stack name and deployment status
- Experiment template ID
- Next step instruction

## Important Guidelines

- **Scenario Library templates come from documentation.** The 4 Scenario
  Library scenarios cannot be generated via FIS API — call
  `aws___read_documentation` on the scenario's doc URL (Step 1 table) before
  generating any files.
- **Never start the FIS experiment in this skill.** This skill deploys the
  supporting infrastructure via CloudFormation; starting the actual experiment
  is handled by `aws-fis-experiment-execute` or manually by the user.
- **Validate resource-action compatibility BEFORE generating files** (Step 3).
  The most common source of wasted effort is deploying a template that
  targets an incompatible resource.
- **Always deploy and validate.** Do not just generate files — deploy the CFN
  template and iterate until it succeeds (Step 6). The user should receive a
  working, deployed experiment template ready to start.
- **Self-heal on CFN errors.** When deployment fails, read the stack events,
  diagnose the issue, fix the template, delete the failed stack, retry. Do
  not ask the user to fix CFN errors — fix them yourself.
- **Verify FIS action availability** (`aws fis list-actions` /
  `aws fis get-action`) before generating templates. Don't fabricate action IDs.
- **Prefer `resourceArns` over `resourceTags` for targets.** Exceptions:
  `aws:elasticache:replicationgroup`, `aws:ec2:autoscaling-group`. Never
  combine `resourceArns` with `filters`.
- **IAM policy must be least-privilege.** Only include permissions for the
  specific actions in the experiment.
- **CFN template must be self-contained.** A user should be able to deploy
  the CFN template and get a working experiment without any other steps.
- **Sequential MCP calls.** All `aws___read_documentation` and
  `aws___search_documentation` calls must be sequential, never parallel.
  Retry up to 10 times on rate limit errors.
- **Keep local files in sync.** After successful deployment, update README.md
  with real ARNs and stack outputs.
