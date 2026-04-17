# ElastiCache Redis/Valkey — FIS Experiment Guide

## Contents

- Scope
- Supported Fault Scenarios (Decision Table)
- Scenario 1: AZ Power Interruption (Native FIS Action)
  - Action Details
  - Target Selection
  - IAM Permissions
  - Dashboard Metrics
- Scenario 2: Primary Node Reboot (SSM Automation)
  - Architecture Overview
  - SSM Automation Runbook
  - IAM Design — Two-Role Pattern
  - Discovery: Identify Primary Node
  - CFN Template Integration
  - Scenario Slug
- Resource Discovery
- Compatibility Validation
- Common Mistakes
- Key Constraints

## Scope

This guide covers FIS experiment preparation for **Amazon ElastiCache** with
Redis or Valkey engines. It applies when the user wants to:

- Simulate AZ-level power interruption affecting ElastiCache nodes
- Reboot the primary node to test application connection resilience
- Test failover behavior and connection pool recovery

**Do NOT use this guide when:**
- The fault is network-level between application pods and ElastiCache — use
  `aws:eks:pod-network-*` or `aws:network:disrupt-connectivity` instead
- ElastiCache is just one service in a broader AZ Power Interruption scenario —
  use `references/az-power-interruption-guide.md` instead (which includes
  ElastiCache as a sub-action)

## Supported Fault Scenarios (Decision Table)

| User Intent | FIS Action | Guide Section |
|---|---|---|
| AZ-level power interruption (failover + blocked replacements) | `aws:elasticache:replicationgroup-interrupt-az-power` (native) | Scenario 1 |
| Reboot primary node (test reconnection/retry logic) | `aws:ssm:start-automation-execution` (SSM Automation) | Scenario 2 |
| Network latency/packet-loss between app and Redis | `aws:eks:pod-network-latency` / `aws:eks:pod-network-packet-loss` | `references/eks-pod-action-guide.md` |

If ambiguous, ask the user which fault type they want.

## Scenario 1: AZ Power Interruption (Native FIS Action)

### Action Details

| Field | Value |
|---|---|
| Action ID | `aws:elasticache:replicationgroup-interrupt-az-power` |
| Resource Type | `aws:elasticache:replicationgroup` |
| Engines | Redis, Valkey |
| Prerequisite | Multi-AZ enabled on the replication group |
| Not Supported | ElastiCache Serverless |

**Behavior:** Interrupts power to nodes in the specified AZ. When the primary
node is targeted, the replica with the least replication lag is promoted to
primary. Read replica replacements in the target AZ are **blocked for the
duration** of the action — the replication group operates with reduced capacity.
Only one AZ per replication group can be impacted at a time.

**Parameters:**
- `duration` — PT1M to PT12H (default: `PT10M`)

**Target parameters:**
- `availabilityZoneIdentifier` — the AZ containing the node(s) to impair

**Note:** The action was renamed from `aws:elasticache:interrupt-cluster-az-power`
to `aws:elasticache:replicationgroup-interrupt-az-power`. Use the new name.

### Target Selection

ElastiCache replication groups **do NOT support `resourceArns`** — you MUST use
`resourceTags`. This is a known limitation already noted in the main SKILL.md.

```yaml
Targets:
  ElastiCacheTarget:
    ResourceType: aws:elasticache:replicationgroup
    ResourceTags:
      - Key: '{TAG_KEY}'
        Value: '{TAG_VALUE}'
    Parameters:
      availabilityZoneIdentifier: '{TARGET_AZ}'
    SelectionMode: ALL
```

**IMPORTANT:** `resourceArns` and `filters` are NOT supported for this resource
type. Only `resourceTags` + `Parameters.availabilityZoneIdentifier`.

### IAM Permissions

**No AWS managed policy exists for ElastiCache FIS actions.** Use an inline
policy on the FIS Experiment Role:

```yaml
- Sid: ElastiCacheActions
  Effect: Allow
  Action:
    - elasticache:InterruptClusterAzPower
    - elasticache:DescribeReplicationGroups
  Resource: '*'
- Sid: TagResolution
  Effect: Allow
  Action:
    - tag:GetResources
  Resource: '*'
```

### Dashboard Metrics

| Widget | Metrics | Dimension |
|---|---|---|
| Replication & Availability | `ReplicationLag`, `IsPrimary` | `ReplicationGroupId`, `CacheClusterId` |
| Performance | `EngineCPUUtilization`, `CurrConnections`, `NewConnections` | `CacheClusterId` |
| Cache Efficiency | `CacheHitRate`, `Evictions`, `CurrItems` | `CacheClusterId` |

**Namespace:** `AWS/ElastiCache`

## Scenario 2: Primary Node Reboot (SSM Automation)

ElastiCache has **no native FIS action for single-node reboot**. Use
`aws:ssm:start-automation-execution` to invoke an SSM Automation runbook that
calls `elasticache:RebootCacheCluster` directly.

**Use case:** Test application connection pool resilience and retry logic during
a brief primary node reboot (1-3 minutes recovery). This is less disruptive than
AZ power interruption — only the targeted node is rebooted, and replica
replacements are NOT blocked.

**Reference:** Based on
[aws-samples/fis-template-library/elasticache-redis-primary-node-reboot](https://github.com/aws-samples/fis-template-library/tree/main/elasticache-redis-primary-node-reboot),
adapted to the single-CFN-stack pattern used by this skill.

### Architecture Overview

```
FIS Experiment Template
  └── Action: aws:ssm:start-automation-execution
        ├── documentArn: arn:aws:ssm:{REGION}:{ACCOUNT_ID}:document/{DOC_NAME}
        ├── documentParameters: {"CacheClusterId":"...","AutomationAssumeRoleArn":"..."}
        └── maxDuration: PT15M
              │
              ▼
SSM Automation Runbook (schema 0.3)
  ├── Step 1: RebootPrimaryNode  (aws:executeAwsApi → elasticache:RebootCacheCluster)
  └── Step 2: WaitForNodeAvailable  (aws:waitForAwsResourceProperty → elasticache:DescribeCacheClusters)
```

### SSM Automation Runbook

Schema version **0.3** is required for Automation documents.

```yaml
description: 'FIS: Reboot ElastiCache primary node to test client resilience'
schemaVersion: '0.3'
assumeRole: '{{ AutomationAssumeRoleArn }}'
parameters:
  AutomationAssumeRoleArn:
    type: String
    description: IAM Role ARN for SSM Automation to assume
  CacheClusterId:
    type: String
    description: CacheClusterId of the primary node to reboot
mainSteps:
  - name: RebootPrimaryNode
    action: aws:executeAwsApi
    inputs:
      Service: elasticache
      Api: RebootCacheCluster
      CacheClusterId: '{{ CacheClusterId }}'
      CacheNodeIdsToReboot:
        - '0001'
    outputs:
      - Name: CacheClusterId
        Selector: $.CacheCluster.CacheClusterId
        Type: String

  - name: WaitForNodeAvailable
    action: aws:waitForAwsResourceProperty
    timeoutSeconds: 600
    inputs:
      Service: elasticache
      Api: DescribeCacheClusters
      CacheClusterId: '{{ CacheClusterId }}'
      PropertySelector: $.CacheClusters[0].CacheClusterStatus
      DesiredValues:
        - available
```

### IAM Design — Two-Role Pattern

Same pattern as `references/msk-guide.md`:

| Role | Trusted By | Purpose | Permissions |
|---|---|---|---|
| FIS Experiment Role | `fis.amazonaws.com` | FIS starts SSM Automation | `AWSFaultInjectionSimulatorSSMAccess` + `iam:PassRole` for SSM Automation Role |
| SSM Automation Role | `ssm.amazonaws.com` | SSM calls `elasticache:RebootCacheCluster` | `elasticache:RebootCacheCluster`, `elasticache:DescribeCacheClusters` |

**SSM Automation Role inline policy:**

```json
{
  "Effect": "Allow",
  "Action": [
    "elasticache:RebootCacheCluster",
    "elasticache:DescribeCacheClusters"
  ],
  "Resource": "*"
}
```

**FIS Experiment Role additions** (beyond managed policy):

```yaml
- Sid: PassRoleToSSM
  Effect: Allow
  Action: iam:PassRole
  Resource: !GetAtt SSMAutomationRole.Arn
  Condition:
    StringEquals:
      iam:PassedToService: ssm.amazonaws.com
```

### Discovery: Identify Primary Node

The prepare skill must identify the primary node's `CacheClusterId` before
generating the template. Steps:

```bash
# 1. List replication groups
aws elasticache describe-replication-groups \
  --replication-group-id {RG_ID} \
  --query 'ReplicationGroups[0].NodeGroups[].NodeGroupMembers[].[CacheClusterId,CurrentRole,PreferredAvailabilityZone]' \
  --output table

# 2. Identify the primary (CurrentRole == "primary")
# The CacheClusterId of the primary node is the target.
# CacheNodeIdsToReboot is always ["0001"] for single-node reboot.
```

Ask the user which replication group to target. If the user doesn't know the
replication group ID:

```bash
aws elasticache describe-replication-groups \
  --query 'ReplicationGroups[].{Id:ReplicationGroupId,Status:Status,Engine:AtRestEncryptionEnabled,MultiAZ:MultiAZ,Nodes:NodeGroups[0].NodeGroupMembers[].{Node:CacheClusterId,Role:CurrentRole,AZ:PreferredAvailabilityZone}}' \
  --output json
```

### CFN Template Integration

#### SSM Document Resource

```yaml
SSMAutomationDocument:
  Type: AWS::SSM::Document
  Properties:
    DocumentType: Automation
    DocumentFormat: YAML
    Name: !Sub 'fis-${ExperimentName}-runbook'
    Content:
      description: 'FIS: Reboot ElastiCache primary node to test client resilience'
      schemaVersion: '0.3'
      assumeRole: '{{ AutomationAssumeRoleArn }}'
      parameters:
        AutomationAssumeRoleArn:
          type: String
          description: IAM Role ARN
        CacheClusterId:
          type: String
          description: CacheClusterId of the primary node to reboot
      mainSteps:
        - name: RebootPrimaryNode
          action: aws:executeAwsApi
          inputs:
            Service: elasticache
            Api: RebootCacheCluster
            CacheClusterId: '{{ CacheClusterId }}'
            CacheNodeIdsToReboot:
              - '0001'
          outputs:
            - Name: CacheClusterId
              Selector: $.CacheCluster.CacheClusterId
              Type: String
        - name: WaitForNodeAvailable
          action: aws:waitForAwsResourceProperty
          timeoutSeconds: 600
          inputs:
            Service: elasticache
            Api: DescribeCacheClusters
            CacheClusterId: '{{ CacheClusterId }}'
            PropertySelector: $.CacheClusters[0].CacheClusterStatus
            DesiredValues:
              - available

SSMAutomationRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub 'fis-ssm-auto-role-${RandomSuffix}'
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: ssm.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: ElastiCacheApiAccess
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            - Sid: ElastiCacheReboot
              Effect: Allow
              Action:
                - elasticache:RebootCacheCluster
                - elasticache:DescribeCacheClusters
              Resource: '*'
```

#### FIS Experiment Template Action

```yaml
FISExperimentTemplate:
  Type: AWS::FIS::ExperimentTemplate
  DependsOn:
    - FISExperimentRole
    - SSMAutomationDocument
  Properties:
    Description: !Sub 'FIS: ${ExperimentName}'
    RoleArn: !GetAtt FISExperimentRole.Arn
    StopConditions:
      - Source: 'none'
    Tags:
      Name: !Ref ExperimentName
    Targets: {}
    Actions:
      RebootPrimaryNode:
        ActionId: aws:ssm:start-automation-execution
        Parameters:
          documentArn: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:document/fis-${ExperimentName}-runbook'
          documentParameters: !Sub >-
            {"AutomationAssumeRoleArn":"${SSMAutomationRole.Arn}",
             "CacheClusterId":"{PRIMARY_CACHE_CLUSTER_ID}"}
          maxDuration: 'PT15M'
```

### Scenario Slug

| Scenario | SCENARIO_SLUG | Example Stack Name |
|---|---|---|
| ElastiCache AZ power interruption | `ec-rg-az-power` | `fis-ec-rg-az-power-my-rg-a3x7k2` |
| ElastiCache primary node reboot | `ssm-auto-ec-reboot` | `fis-ssm-auto-ec-reboot-my-rg-a3x7k2` |

## Resource Discovery

### Describe Replication Group

```bash
aws elasticache describe-replication-groups \
  --replication-group-id {RG_ID} \
  --region {TARGET_REGION}
```

**Key fields to check:**
- `Status` — must be `available`
- `MultiAZ` — must be `enabled` (for AZ power interruption)
- `AutomaticFailover` — must be `enabled` (for both scenarios)
- `ClusterEnabled` — cluster mode enabled or disabled
- `NodeGroups[].NodeGroupMembers[]` — node details, roles, AZs

### List Tags

```bash
aws elasticache list-tags-for-resource \
  --resource-name "arn:aws:elasticache:{REGION}:{ACCOUNT_ID}:replicationgroup:{RG_ID}"
```

## Compatibility Validation

| Check | Requirement | How to Detect | Impact |
|---|---|---|---|
| Multi-AZ | Enabled | `MultiAZ: enabled` in describe output | AZ power action requires Multi-AZ |
| Automatic Failover | Enabled | `AutomaticFailover: enabled` | Both scenarios require automatic failover for proper recovery |
| Engine | Redis or Valkey | `Engine` field — must NOT be `memcached` | Memcached does not support replication groups |
| Deployment | Non-serverless | Check if replication group exists (serverless uses different API) | AZ power action does not support serverless |
| Cluster Mode | Disabled or Enabled | `ClusterEnabled` field | Both modes supported; disabled is simpler to observe |

**If incompatible:** Explain the specific mismatch and suggest:
- Standalone ElastiCache (no replication group) → must create a replication group
  with Multi-AZ first
- Memcached → not supported for replication group actions; consider switching to
  Redis/Valkey or testing at the network level

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using `resourceArns` for ElastiCache targets | ElastiCache replication groups only support `resourceTags` — never `resourceArns` |
| Targeting Serverless ElastiCache | Not supported by `replicationgroup-interrupt-az-power`. Serverless handles failover behind a managed proxy |
| Using old action ID `aws:elasticache:interrupt-cluster-az-power` | Use the renamed `aws:elasticache:replicationgroup-interrupt-az-power` |
| Forgetting `tag:GetResources` permission | Required for tag-based target resolution |
| Not checking `AutomaticFailover` status | Both scenarios require `AutomaticFailover: enabled`; without it, failover may not occur |
| Assuming `CacheNodeIdsToReboot` varies | For ElastiCache, the node ID is always `0001` for single-node reboot within a cache cluster |
| Reboot targets a replica instead of primary | Discover the primary node's `CacheClusterId` at prepare time using `CurrentRole == "primary"`. If primary changes before execution, the reboot still tests connection resilience — just on a replica |
| Using FIS Experiment Role as SSM `assumeRole` | Same as MSK — FIS role trusts `fis.amazonaws.com`, not `ssm.amazonaws.com`. Create a separate SSM Automation Role |

## Key Constraints

| Constraint | Detail |
|---|---|
| Target resolution | Only `resourceTags` (not `resourceArns` or `filters`) |
| AZ limit | One AZ per replication group can be impacted at a time |
| Reboot recovery time | Primary node reboot typically takes 1-3 minutes to return to `available` |
| SSM document naming | Max 128 characters. Use `fis-{ExperimentName}-runbook` |
| `documentParameters` format | Must be a JSON string, not a JSON object |
| `CacheNodeIdsToReboot` | Always `["0001"]` for single-node reboot |
| Cluster mode | Both cluster-mode-enabled and cluster-mode-disabled are supported. Cluster mode disabled is easier to observe individual node role changes |
| Rollback | Both scenarios are self-recovering. AZ power: replicas resume when action ends. Reboot: node comes back online automatically |
