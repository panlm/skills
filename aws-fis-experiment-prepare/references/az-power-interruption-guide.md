# AZ Availability: Power Interruption — Scenario Guide

## Scope

This guide applies when the user requests an **AZ Availability: Power Interruption**
scenario from the FIS Scenario Library. It covers the unique requirements of this
scenario that differ from custom single-action FIS experiments.

**MANDATORY:** Complete all steps in this guide before generating configuration files
for this scenario.

## Design Decision: One Stack Per AZ

AZ Power Interruption experiment templates have the **target AZ hardcoded** in multiple
locations — target filters (`Placement.AvailabilityZone`), action parameters
(`availabilityZoneIdentifiers`), and target parameters (`writerAvailabilityZoneIdentifiers`,
`availabilityZoneIdentifier`). Changing the target AZ requires recreating the experiment
template.

**Chosen approach:** Create one CFN Stack per AZ. To test a different AZ, delete the
current Stack and deploy a new one with the new AZ parameter. This is the simplest
approach — AZ failure experiments are not run frequently enough to justify maintaining
multiple templates simultaneously.

**Stack naming convention:** `fis-az-power-int-{AZ_SUFFIX}-{RANDOM_SUFFIX}`
- Example: `fis-az-power-int-2a-a3x7k2`, `fis-az-power-int-2b-b8y2m1`

## Resource Tagging Strategy

### Why Tags Are Needed

AZ Power Interruption uses **tag-based target selection** for resource types that do
not support `resourceArns` (ASG, ElastiCache) and optionally for others. Each sub-action
looks for a specific tag key/value pair on target resources.

### Tagging via CFN Custom Resource (Lambda)

Tags are applied by a **Lambda-backed Custom Resource within the same CFN Stack** as
the experiment template. This approach:

- Requires **zero additional permissions on the EC2 Instance Profile** — all tagging
  is done by the Lambda role, created through the CFN Service Role
- Ties tag lifecycle to the Stack — delete Stack removes tags automatically
- Is deployed in a single `aws cloudformation deploy` command

### Tag Key/Value Table

All sub-actions share the same tag key `AzImpairmentPower`. The value identifies which
sub-action targets the resource:

| Resource Type | Tag Value | Applied To |
|---|---|---|
| EC2 Instance (standalone) | `StopInstances` | Instances in target AZ |
| EC2 Instance (ASG-managed) | `IceAsg` | ASG instances in target AZ |
| Auto Scaling Group | `IceAsg` | ASGs with instances in target AZ |
| Subnet | `DisruptSubnet` | Subnets in target AZ |
| RDS Cluster | `DisruptRds` | Aurora clusters with writer in target AZ |
| ElastiCache Replication Group | `DisruptElasticache` | Replication groups with nodes in target AZ |
| EBS Volume | `ApiPauseVolume` | Volumes attached to instances in target AZ |
| ARC Autoshift Resources | `RecoverAutoshiftResources` | Resources with zonal autoshift enabled |

### AZ Filtering Is Not Done by Tags

A critical design point: **tags do NOT distinguish AZ — the experiment template does.**

All three AZs' resources can carry the same tag values simultaneously. The experiment
template's internal AZ filters and parameters determine which resources are actually
affected:

| Target Type | AZ Selection Mechanism |
|---|---|
| EC2 Instance | `filters[].path: Placement.AvailabilityZone` |
| Subnet | `filters[].path: AvailabilityZone` |
| ASG | `parameters.availabilityZoneIdentifiers` in action |
| RDS Cluster | `parameters.writerAvailabilityZoneIdentifiers` in target |
| ElastiCache | `parameters.availabilityZoneIdentifier` in target |
| EBS Volume | `parameters.availabilityZoneIdentifier` in target |
| IAM Role (Pause Launches) | `parameters.availabilityZoneIdentifiers` in action |

This means: if you later want to test a different AZ, **tags do not need updating** —
only the experiment template (i.e., the CFN Stack) needs to be recreated.

### ASG Tag Propagation

When tagging an ASG, set `PropagateAtLaunch: true`. This ensures:

- Existing instances launched by the ASG inherit the tag
- **New instances launched during or after the experiment** (e.g., ASG scaling in a
  healthy AZ to compensate for stopped instances) also get the tag automatically
- No need to track individual instance IDs

Since AZ filtering is done by the experiment template (not tags), ASG-launched instances
in healthy AZs will carry the tag but will **not** be affected by the experiment.

## FIS Experiment Role — Required Permissions

The FIS Experiment Role needs permissions for all 9 sub-actions. Use **AWS managed
policies as the base**, supplemented by an inline policy for actions not covered.

### Managed Policies to Attach

| Managed Policy | Covers |
|---|---|
| `AWSFaultInjectionSimulatorEC2Access` | Stop/Start instances, KMS grants for encrypted EBS, SSM commands |
| `AWSFaultInjectionSimulatorNetworkAccess` | Network ACL creation/deletion/replacement for connectivity disruption |
| `AWSFaultInjectionSimulatorRDSAccess` | RDS cluster failover, instance reboot, tag-based target resolution |

### Inline Policy for Uncovered Actions

The following permissions are **NOT covered** by any managed policy and must be added
as an inline policy on the FIS Experiment Role:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ElastiCacheAZPower",
            "Effect": "Allow",
            "Action": [
                "elasticache:DescribeReplicationGroups",
                "elasticache:InterruptClusterAzPower"
            ],
            "Resource": "arn:aws:elasticache:*:*:replicationgroup:*"
        },
        {
            "Sid": "EBSPauseIO",
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeVolumes",
                "ec2:PauseVolumeIO"
            ],
            "Resource": "*"
        },
        {
            "Sid": "InjectAPIError",
            "Effect": "Allow",
            "Action": "ec2:InjectApiError",
            "Resource": "*",
            "Condition": {
                "ForAnyValue:StringEquals": {
                    "ec2:FisActionId": [
                        "aws:ec2:api-insufficient-instance-capacity-error",
                        "aws:ec2:asg-insufficient-instance-capacity-error"
                    ]
                }
            }
        },
        {
            "Sid": "DescribeASG",
            "Effect": "Allow",
            "Action": "autoscaling:DescribeAutoScalingGroups",
            "Resource": "*"
        },
        {
            "Sid": "FISExperimentLogging",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogDelivery",
                "logs:PutResourcePolicy",
                "logs:DescribeResourcePolicies",
                "logs:DescribeLogGroups"
            ],
            "Resource": "*"
        },
        {
            "Sid": "TagResolution",
            "Effect": "Allow",
            "Action": "tag:GetResources",
            "Resource": "*"
        }
    ]
}
```

**Note:** `ec2:PauseVolumeIO` resource scope is `*` because FIS selects the specific
volume at runtime. `ec2:DescribeVolumes` also requires `*`.

## CFN Service Role — Additional Permissions

If using a CFN Service Role (as described in the
[setup guide](https://panlm.github.io/others/cfn-service-role-for-fis-experiment-setup-guide/)),
verify it has:

| Permission | Why |
|---|---|
| `logs:*` | FIS experiment logging (`cloudwatch:*` does NOT cover `logs:` namespace) |
| `iam:CreateServiceLinkedRole` | ARC Zonal Autoshift creates `AWSServiceRoleForZonalAutoshiftPracticeRun` automatically |

## Service-Linked Role

The ARC Zonal Autoshift recovery action requires the service-linked role
`AWSServiceRoleForZonalAutoshiftPracticeRun`. This role is **created automatically**
when an experiment template with the AZ Power Interruption scenario is created via
Console, CLI, or SDK. No manual creation is needed, but the CFN Service Role must have
`iam:CreateServiceLinkedRole` permission.

## IAM Role Target for Pause Instance Launches

The `Pause-Instance-Launches` action targets **IAM Roles** (not EC2 instances). It
injects `InsufficientInstanceCapacity` errors on API calls (`RunInstances`,
`CreateFleet`, `StartInstances`) made by the specified roles.

You must provide the ARN(s) of roles that launch instances in the target AZ:

- **ASG service-linked role:** `arn:aws:iam::{ACCOUNT_ID}:role/aws-service-role/autoscaling.amazonaws.com/AWSServiceRoleForAutoScaling`
- **Custom launch roles:** Any IAM role used by automation to call `RunInstances`

If no roles are specified (empty `resourceArns`), this action is skipped.

## Limitations

| Limitation | Detail |
|---|---|
| No stop conditions by default | Scenario template has no built-in stop conditions — you MUST add CloudWatch Alarms |
| Fargate not supported | EKS Pods on Fargate and ECS Tasks on Fargate are not affected |
| RDS Multi-AZ with 2 readable standby not supported | Instances terminate but capacity re-provisions immediately in affected AZ |
| S3 Express One Zone | Only affects directory buckets co-located in the target AZ |

## Custom Resource Lambda — Tagging Logic

The Lambda receives target resource identifiers as input parameters and applies
`AzImpairmentPower` tags. Key behaviors:

| Event Type | Action |
|---|---|
| Create | Apply tags to all specified resources |
| Update | Remove tags from old resources (via `OldResourceProperties`), apply to new |
| Delete | Remove all `AzImpairmentPower` tags from resources |

**Resource discovery by the Lambda:**

The Lambda receives explicit resource IDs/names as CFN parameters. It does NOT
auto-discover resources. The prepare skill's resource discovery step (Step 2 in
SKILL.md) identifies target resources and passes them as parameters.

**ASG tagging:** Uses `autoscaling:CreateOrUpdateTags` with `PropagateAtLaunch: true`.

**Lambda Role permissions** (minimum):

| Permission | Resource Scope |
|---|---|
| `ec2:CreateTags` / `ec2:DeleteTags` | `arn:aws:ec2:*:*:instance/*`, `arn:aws:ec2:*:*:subnet/*`, `arn:aws:ec2:*:*:volume/*` |
| `autoscaling:CreateOrUpdateTags` / `autoscaling:DeleteTags` | `*` |
| `rds:AddTagsToResource` / `rds:RemoveTagsFromResource` | `arn:aws:rds:*:*:cluster:*` |
| `elasticache:AddTagsToResource` / `elasticache:RemoveTagsFromResource` | `arn:aws:elasticache:*:*:replicationgroup:*` |

## Quick Reference: CFN Stack Contents

A complete AZ Power Interruption CFN Stack contains:

| Resource | Type | Purpose |
|---|---|---|
| FIS Experiment Role | `AWS::IAM::Role` | 3 managed policies + inline policy |
| FIS Experiment Template | `AWS::FIS::ExperimentTemplate` | The experiment definition |
| CloudWatch Dashboard | `AWS::CloudWatch::Dashboard` | Monitoring during experiment |
| Tagging Lambda Role | `AWS::IAM::Role` | Permissions for tagging resources |
| Tagging Lambda Function | `AWS::Lambda::Function` | Applies/removes resource tags |
| Tagging Custom Resource | `Custom::FISAZPowerTags` | Triggers Lambda on Stack lifecycle |
| CloudWatch Alarm (optional) | `AWS::CloudWatch::Alarm` | Stop condition, only if user requests |
