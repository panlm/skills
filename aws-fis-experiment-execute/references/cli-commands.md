# CLI Commands Reference

Complete AWS CLI command reference for FIS experiment deployment and execution.
All commands use `{PLACEHOLDERS}` for values that must be replaced.

## IAM Role Commands

### Create FIS Execution Role

```bash
aws iam create-role \
  --role-name "FISExperimentRole-{SCENARIO_NAME}" \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "fis.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }'
```

### Attach Policy to Role

```bash
aws iam put-role-policy \
  --role-name "FISExperimentRole-{SCENARIO_NAME}" \
  --policy-name "FISExperimentPolicy" \
  --policy-document "file://{EXPERIMENT_DIR}/iam-policy.json"
```

### Get Role ARN (for template update)

```bash
ROLE_ARN=$(aws iam get-role \
  --role-name "FISExperimentRole-{SCENARIO_NAME}" \
  --query 'Role.Arn' --output text)
```

### Delete Role (cleanup)

```bash
aws iam delete-role-policy \
  --role-name "FISExperimentRole-{SCENARIO_NAME}" \
  --policy-name "FISExperimentPolicy"

aws iam delete-role \
  --role-name "FISExperimentRole-{SCENARIO_NAME}"
```

---

## CloudWatch Alarm Commands

### Create Stop Condition Alarm

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "FIS-StopCondition-{SCENARIO}-{SERVICE}" \
  --alarm-description "Stop FIS experiment if {CONDITION}" \
  --namespace "{NAMESPACE}" \
  --metric-name "{METRIC_NAME}" \
  --statistic "Average" \
  --period 60 \
  --evaluation-periods 1 \
  --threshold "{VALUE}" \
  --comparison-operator "{OPERATOR}" \
  --treat-missing-data "breaching" \
  --dimensions "Name={DIM_NAME},Value={DIM_VALUE}" \
  --region {REGION}
```

### Get Alarm ARN (for template update)

```bash
ALARM_ARN=$(aws cloudwatch describe-alarms \
  --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" \
  --query 'MetricAlarms[0].AlarmArn' --output text \
  --region {REGION})
```

### Delete Alarms (cleanup)

```bash
aws cloudwatch delete-alarms \
  --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" \
  --region {REGION}
```

---

## CloudWatch Dashboard Commands

### Create Dashboard

```bash
aws cloudwatch put-dashboard \
  --dashboard-name "FIS-{SCENARIO}" \
  --dashboard-body "file://{EXPERIMENT_DIR}/alarms/dashboard.json" \
  --region {REGION}
```

### Get Dashboard URL

```
https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}#dashboards:name=FIS-{SCENARIO}
```

### Delete Dashboard (cleanup)

```bash
aws cloudwatch delete-dashboards \
  --dashboard-names "FIS-{SCENARIO}" \
  --region {REGION}
```

---

## FIS Experiment Template Commands

### Create Experiment Template

```bash
TEMPLATE_RESPONSE=$(aws fis create-experiment-template \
  --cli-input-json "file://{EXPERIMENT_DIR}/experiment-template.json" \
  --region {REGION} \
  --output json)

TEMPLATE_ID=$(echo "$TEMPLATE_RESPONSE" | jq -r '.experimentTemplate.id')
echo "Experiment Template ID: $TEMPLATE_ID"
```

### List Experiment Templates

```bash
aws fis list-experiment-templates \
  --query 'experimentTemplates[].{id:id, description:description, tags:tags}' \
  --region {REGION} --output table
```

### Get Experiment Template Details

```bash
aws fis get-experiment-template \
  --id "{TEMPLATE_ID}" \
  --region {REGION}
```

### Delete Experiment Template (cleanup)

```bash
aws fis delete-experiment-template \
  --id "{TEMPLATE_ID}" \
  --region {REGION}
```

---

## FIS Experiment Execution Commands

### Start Experiment

```bash
EXPERIMENT_RESPONSE=$(aws fis start-experiment \
  --experiment-template-id "{TEMPLATE_ID}" \
  --region {REGION} \
  --output json)

EXPERIMENT_ID=$(echo "$EXPERIMENT_RESPONSE" | jq -r '.experiment.id')
echo "Experiment ID: $EXPERIMENT_ID"
```

### Get Experiment Status

```bash
aws fis get-experiment \
  --id "{EXPERIMENT_ID}" \
  --region {REGION} \
  --query '{
    Status: experiment.state.status,
    Reason: experiment.state.reason,
    StartTime: experiment.startTime,
    EndTime: experiment.endTime
  }' --output table
```

### Get Experiment Action Details

```bash
aws fis get-experiment \
  --id "{EXPERIMENT_ID}" \
  --region {REGION} \
  --query 'experiment.actions' --output json
```

### Stop Experiment (emergency)

```bash
aws fis stop-experiment \
  --id "{EXPERIMENT_ID}" \
  --region {REGION}
```

### List Recent Experiments

```bash
aws fis list-experiments \
  --query 'experiments[?state.status!=`completed`].{id:id, status:state.status, templateId:experimentTemplateId}' \
  --region {REGION} --output table
```

---

## CloudFormation Commands

### Deploy Stack (all-in-one)

```bash
aws cloudformation deploy \
  --template-file "{EXPERIMENT_DIR}/cfn-template.yaml" \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region {REGION} \
  --no-fail-on-empty-changeset
```

### Wait for Stack Creation

```bash
aws cloudformation wait stack-create-complete \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --region {REGION}
```

### Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --query 'Stacks[0].Outputs' \
  --region {REGION} --output table
```

### Get Experiment Template ID from Stack

```bash
TEMPLATE_ID=$(aws cloudformation describe-stacks \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --query 'Stacks[0].Outputs[?OutputKey==`ExperimentTemplateId`].OutputValue' \
  --output text --region {REGION})
```

### Delete Stack (cleanup)

```bash
aws cloudformation delete-stack \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --region {REGION}

aws cloudformation wait stack-delete-complete \
  --stack-name "fis-{SCENARIO}-{TIMESTAMP}" \
  --region {REGION}
```

### Validate Template (pre-check)

```bash
aws cloudformation validate-template \
  --template-body "file://{EXPERIMENT_DIR}/cfn-template.yaml" \
  --region {REGION}
```

---

## FIS Action Discovery Commands

### List All FIS Actions in Region

```bash
aws fis list-actions \
  --region {REGION} \
  --query 'actions[].{id:id, description:description}' \
  --output table
```

### List Actions for Specific Service

```bash
aws fis list-actions \
  --region {REGION} \
  --query 'actions[?starts_with(id, `aws:{SERVICE}:`)].{id:id, description:description}' \
  --output table
```

### Get Action Details

```bash
aws fis get-action \
  --id "{ACTION_ID}" \
  --region {REGION}
```

---

## Monitoring Commands (During Experiment)

### Poll Experiment Status (loop)

```bash
while true; do
  STATUS=$(aws fis get-experiment \
    --id "{EXPERIMENT_ID}" \
    --region {REGION} \
    --query 'experiment.state.status' --output text)
  echo "$(date): Status = $STATUS"
  case "$STATUS" in
    completed|stopped|failed) break ;;
    *) sleep 30 ;;
  esac
done
```

### Check Alarm State

```bash
aws cloudwatch describe-alarms \
  --alarm-names "FIS-StopCondition-{SCENARIO}-{SERVICE}" \
  --query 'MetricAlarms[].{Name:AlarmName, State:StateValue, Reason:StateReason}' \
  --region {REGION} --output table
```

### Get Recent Metric Data

```bash
aws cloudwatch get-metric-statistics \
  --namespace "{NAMESPACE}" \
  --metric-name "{METRIC}" \
  --dimensions "Name={DIM_NAME},Value={DIM_VALUE}" \
  --start-time "$(date -u -v-30M +%Y-%m-%dT%H:%M:%S)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
  --period 60 \
  --statistics Average \
  --region {REGION} --output table
```
