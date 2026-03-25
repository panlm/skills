# FIS Experiment Execution Skills Design

**Date:** 2026-03-25
**Status:** Approved

## Overview

Two independent skills for creating and executing AWS FIS (Fault Injection Service)
experiments. Skill 1 generates all configuration files; Skill 2 deploys and runs them.

## Skills

| Skill | Purpose | Input | Output |
|---|---|---|---|
| **aws-fis-experiment-prepare** | Discover resources, generate configs | User describes scenario | Local directory with all files |
| **aws-fis-experiment-execute** | Deploy resources, run experiment, monitor | Prepare output directory | Experiment results report |

## Skill 1: aws-fis-experiment-prepare

### Triggers
- "prepare FIS experiment", "create FIS experiment for..."
- "generate AZ Power Interruption config"
- "准备 FIS 实验", "生成混沌实验配置"

### Workflow
1. Identify scenario (Scenario Library or custom FIS action)
2. Discover target resources (CLI: list-actions, user provides tags/ARNs)
3. Determine monitoring metrics per affected service
4. Generate all config files to local directory
5. Output README summary

### Output Directory
```
./az-power-interruption-yyyy-mm-dd-HH-MM-SS/
├── README.md
├── experiment-template.json
├── iam-policy.json
├── cfn-template.yaml        # Full: IAM role + alarms + experiment template
├── alarms/
│   ├── stop-condition-alarms.json
│   └── dashboard.json
└── expected-behavior.md
```

### Scenario Sources
- **Scenario Library:** AZ Power Interruption, AZ Application Slowdown, Cross-AZ Traffic Slowdown, Cross-Region Connectivity, EC2/EKS/EBS stress series
- **Custom FIS action:** User specifies action ID and parameters

## Skill 2: aws-fis-experiment-execute

### Triggers
- "execute FIS experiment", "run FIS experiment"
- "启动 FIS 实验", "运行混沌实验"

### Workflow
1. Load and validate experiment directory
2. User chooses deployment method: CLI or CFN
3. Deploy infrastructure (user confirms)
4. Start experiment (user confirms with impact warning)
5. Monitor experiment status (poll + dashboard URL)
6. Generate results report

### Safety Gates
- Step 3: User confirms resource creation
- Step 4: User explicitly confirms experiment start with impact summary
- All CLI commands shown before execution
- Dry-run mode supported

## Design Decisions
- **Independent skills:** No dependency on aws-service-chaos-research
- **File as interface:** Prepare outputs files, Execute reads them
- **Both CLI + CFN:** Single CFN template contains all resources
- **Strict confirmation:** Critical steps require user approval
- **Language follows user:** Output matches conversation language
