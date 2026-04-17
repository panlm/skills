# Amazon MSK — FIS Experiment Guide

## Contents

- Scope (what this guide covers)
- Architecture Overview
- MSK Broker Reboot — Full Example
  - SSM Automation Runbook
  - IAM Permissions
  - Discovery: List Broker IDs
- CFN Template Integration (SSM Document, IAM roles, FIS Action)
- IAM Design — Two-Role Pattern
- Scenario Slug
- Key Constraints
- Common Mistakes

## Scope

MSK has **no native FIS action**, so fault injection goes through an SSM
Automation runbook that calls the MSK API directly.

**Supported fault:** broker reboot via `kafka:RebootBroker` — tests Kafka
consumer/producer resilience to broker restarts.

**Use this guide when:**
- User wants to inject a fault into MSK (broker reboot, restart)
- User asks "Kafka broker failure" or similar

**Do NOT use this guide when:**
- The fault is network-level (pod-to-MSK latency/packet-loss) — use
  `aws:network:disrupt-connectivity` or `aws:eks:pod-network-*` instead
- The fault is AZ-level (MSK impact during AZ power interruption) — use
  `references/az-power-interruption-guide.md`

## Architecture Overview

```
FIS Experiment Template
  └── Action: aws:ssm:start-automation-execution
        ├── documentArn: arn:aws:ssm:{REGION}:{ACCOUNT_ID}:document/{DOC_NAME}
        ├── documentParameters: {"ClusterArn": "...", "BrokerId": "1"}
        └── maxDuration: PT15M
              │
              ▼
SSM Automation Runbook (schema 0.3)
  ├── Step 1: RebootMskBroker  (aws:executeAwsApi → kafka:RebootBroker)
  └── Step 2: WaitForClusterActive  (aws:waitForAwsResourceProperty → kafka:DescribeCluster)
```

## MSK Broker Reboot — Full Example

### SSM Automation Runbook

Schema version **0.3** is required for Automation documents.

```yaml
description: 'FIS: Reboot MSK broker to test Kafka client resilience'
schemaVersion: '0.3'
assumeRole: '{{ AutomationAssumeRoleArn }}'
parameters:
  AutomationAssumeRoleArn:
    type: String
    description: IAM Role ARN for SSM Automation to assume
  ClusterArn:
    type: String
    description: MSK cluster ARN
  BrokerId:
    type: String
    description: 'Broker ID to reboot (e.g., 1, 2, 3)'
mainSteps:
  - name: RebootMskBroker
    action: aws:executeAwsApi
    inputs:
      Service: kafka
      Api: RebootBroker
      ClusterArn: '{{ ClusterArn }}'
      BrokerIds:
        - '{{ BrokerId }}'
    outputs:
      - Name: ClusterArn
        Selector: $.ClusterArn
        Type: String
      - Name: ClusterOperationArn
        Selector: $.ClusterOperationArn
        Type: String

  - name: WaitForClusterActive
    action: aws:waitForAwsResourceProperty
    timeoutSeconds: 600
    inputs:
      Service: kafka
      Api: DescribeCluster
      ClusterArn: '{{ ClusterArn }}'
      PropertySelector: $.ClusterInfo.State
      DesiredValues:
        - ACTIVE
```

### IAM Permissions

The **SSM Automation Role** (trusted by `ssm.amazonaws.com`) needs MSK API
permissions:

```json
{
  "Effect": "Allow",
  "Action": [
    "kafka:RebootBroker",
    "kafka:DescribeCluster"
  ],
  "Resource": "{MSK_CLUSTER_ARN}"
}
```

### Discovery: List Broker IDs

```bash
aws kafka list-nodes --cluster-arn {CLUSTER_ARN} \
  --query 'NodeInfoList[].BrokerNodeInfo.BrokerId' --output json
```

Ask the user which specific broker(s) to reboot, or default to the first
broker for a minimal-impact test.

## CFN Template Integration

### SSM Document Resource

The SSM Automation runbook is deployed as an `AWS::SSM::Document` in the
same CFN template alongside the FIS experiment template.

```yaml
Resources:
  SSMAutomationDocument:
    Type: AWS::SSM::Document
    Properties:
      DocumentType: Automation
      DocumentFormat: YAML
      Name: !Sub 'fis-${ExperimentName}-runbook'
      Content:
        description: 'FIS: Reboot MSK broker to test Kafka client resilience'
        schemaVersion: '0.3'
        assumeRole: '{{ AutomationAssumeRoleArn }}'
        parameters:
          AutomationAssumeRoleArn:
            type: String
            description: IAM Role ARN
          ClusterArn:
            type: String
            description: MSK cluster ARN
          BrokerId:
            type: String
            description: 'Broker ID to reboot'
        mainSteps:
          # ... (paste full mainSteps from the runbook example above)

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
        - PolicyName: MskApiAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Sid: MskBrokerAccess
                Effect: Allow
                Action:
                  - kafka:RebootBroker
                  - kafka:DescribeCluster
                Resource: !Ref ClusterArn
```

### FIS Experiment Template Action

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
    Targets: {}  # No targets needed — SSM Automation handles targeting
    Actions:
      ExecuteSSMAutomation:
        ActionId: aws:ssm:start-automation-execution
        # CFN ExperimentTemplate.Actions.Parameters is Map of String,
        # not the list-of-strings format used by the FIS API.
        Parameters:
          documentArn: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:document/fis-${ExperimentName}-runbook'
          documentParameters: !Sub >-
            {"AutomationAssumeRoleArn":"${SSMAutomationRole.Arn}",
             "ClusterArn":"${ClusterArn}",
             "BrokerId":"${BrokerId}"}
          maxDuration: 'PT15M'
```

### FIS Experiment Role — Additional Permissions

The FIS Experiment Role must have `AWSFaultInjectionSimulatorSSMAccess`
managed policy attached, plus `iam:PassRole` for the SSM Automation Role:

```yaml
FISExperimentRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub 'fis-role-${RandomSuffix}'
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: fis.amazonaws.com
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorSSMAccess
    Policies:
      - PolicyName: PassSSMAutomationRole
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            - Sid: PassRoleToSSM
              Effect: Allow
              Action: iam:PassRole
              Resource: !GetAtt SSMAutomationRole.Arn
              Condition:
                StringEquals:
                  iam:PassedToService: ssm.amazonaws.com
```

## IAM Design — Two-Role Pattern

MSK broker reboot via SSM Automation requires **TWO IAM roles**:

| Role | Trusted By | Purpose | Permissions |
|---|---|---|---|
| FIS Experiment Role | `fis.amazonaws.com` | FIS starts the SSM Automation execution | `AWSFaultInjectionSimulatorSSMAccess` + `iam:PassRole` for SSM Automation Role |
| SSM Automation Role | `ssm.amazonaws.com` | SSM Automation calls `kafka:RebootBroker` | `kafka:RebootBroker`, `kafka:DescribeCluster` |

**Why two roles?** FIS invokes `ssm:StartAutomationExecution` using the FIS
Experiment Role, but the SSM Automation runbook itself needs to call
`kafka:RebootBroker`. SSM Automation requires a separate `assumeRole` that
trusts `ssm.amazonaws.com` — the FIS role (which trusts `fis.amazonaws.com`)
cannot be used directly by SSM Automation.

## Scenario Slug

When generating the output directory and CFN stack name:

| Scenario | SCENARIO_SLUG | Example Stack Name |
|---|---|---|
| MSK broker reboot | `ssm-auto-msk-reboot` | `fis-ssm-auto-msk-reboot-my-cluster-a3x7k2` |

See `references/slug-conventions.md` for the general SSM Automation slug
pattern (`ssm-auto-<service>-<operation>`).

## Key Constraints

| Constraint | Detail |
|---|---|
| `aws:executeAwsApi` max duration | 25 seconds per step execution. `RebootBroker` returns quickly, so this is sufficient. |
| SSM document naming | Max 128 characters. Use `fis-{ExperimentName}-runbook` pattern. |
| `documentParameters` in FIS | Must be a JSON string (not a JSON object). FIS passes this as a single string parameter to `StartAutomationExecution`. |
| SSM Automation concurrency | Default max 25 concurrent automation executions per account per region. For high-frequency experiments, request a quota increase. |
| Rollback | `kafka:RebootBroker` is self-recovering (broker comes back online automatically). No explicit rollback step needed. |
| MSK Cluster State | During reboot, cluster state transitions to `REBOOTING_BROKER` then back to `ACTIVE`. The `WaitForClusterActive` step in the runbook handles this. |

## Common Mistakes

| Mistake | Fix |
|---|---|
| Using FIS Experiment Role as SSM Automation `assumeRole` | FIS role trusts `fis.amazonaws.com`, not `ssm.amazonaws.com`. Create a separate SSM Automation Role. |
| Passing `documentParameters` as JSON object instead of string | In CFN, use `!Sub` with the JSON stringified. In CLI, wrap in single quotes. |
| Forgetting `iam:PassRole` on FIS Experiment Role | FIS needs to pass the SSM Automation Role to SSM. Add `iam:PassRole` with condition `iam:PassedToService: ssm.amazonaws.com`. |
| Not waiting for recovery | Without `aws:waitForAwsResourceProperty`, the FIS experiment ends immediately after the API call, before the broker has fully restarted. Always include the `WaitForClusterActive` step. |
| Hardcoding region/account in document ARN | Use `!Sub` with `${AWS::Region}` and `${AWS::AccountId}` in CFN templates. |
| Wrong broker ID | Use `aws kafka list-nodes` to get valid broker IDs before generating the template. Do not assume broker IDs start at 1 — they correspond to the node's physical position. |
