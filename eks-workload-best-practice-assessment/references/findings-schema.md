# Findings JSON Schema

The findings JSON file is the intermediate output of Step 6 (assessment) and the
input of Step 7 (report generation). Separating these steps allows the LLM to
focus on evaluation logic first, then formatting second.

## Top-Level Structure

```json
{
  "cluster_info": { ... },
  "findings": [ ... ],
  "summary": { ... }
}
```

## `cluster_info` Object

```json
{
  "cluster_name": "my-eks-cluster",
  "region": "us-west-2",
  "k8s_version": "1.30",
  "k8s_full_version": "v1.30.2-eks-abc123",
  "eks_platform_version": "eks.15",
  "node_count": 3,
  "az_distribution": ["us-west-2a", "us-west-2b", "us-west-2c"],
  "instance_types": ["t3.medium"],
  "assessed_namespaces": ["default", "app", "monitoring"],
  "workload_counts": {
    "deployments": 12,
    "statefulsets": 2,
    "daemonsets": 3
  },
  "assessment_date": "2026-03-28",
  "assessment_timestamp": "2026-03-28-14-31-57"
}
```

## `findings` Array

Each element is one check item result:

```json
{
  "check_id": "WL-01-hi",
  "check_name": "Replicas >= 2",
  "dimension": "workload-configuration",
  "priority": "hi",
  "status": "FAIL",
  "affected_workloads": [
    "cert-manager/cert-manager",
    "ingress-nginx/ingress-nginx-controller"
  ],
  "finding": "cert-manager=1, ingress-nginx-controller=1, aws-lb-controller=2 (PASS)",
  "remediation": "Scale critical Deployments to >= 2 replicas and add PDB"
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `check_id` | string | yes | Unique ID with priority suffix: `{PREFIX}-{NN}-{hi\|md\|lo}` |
| `check_name` | string | yes | Human-readable check item name |
| `dimension` | string | yes | One of: `workload-configuration`, `security`, `observability`, `networking`, `storage`, `eks-platform`, `cicd`, `image-security`, `infrastructure` |
| `priority` | string | yes | `hi`, `md`, or `lo` |
| `status` | string | yes | `PASS`, `FAIL`, `WARN`, or `N/A` |
| `affected_workloads` | string[] | yes | Array of `namespace/name` strings. Empty array `[]` for cluster-wide checks or PASS items |
| `finding` | string | yes | Actual observed value. Must include concrete data, not just "not configured" |
| `remediation` | string\|null | yes | Fix action for FAIL/WARN items. `null` for PASS/N/A |

### Dimension Values

| Value | Maps to Report Section |
|-------|----------------------|
| `workload-configuration` | Dimension 1: Workload Configuration |
| `security` | Dimension 2: Security |
| `observability` | Dimension 3: Observability |
| `networking` | Dimension 4: Networking |
| `storage` | Dimension 5: Storage |
| `eks-platform` | Dimension 6: EKS Platform Integration |
| `cicd` | Dimension 7: CI/CD & GitOps |
| `image-security` | Dimension 8: Image Security |
| `infrastructure` | Infrastructure Layer (from Step 4) |

## `summary` Object

Pre-calculated summary to speed up report generation:

```json
{
  "total": { "pass": 32, "fail": 38, "warn": 13, "na": 2 },
  "by_dimension": {
    "workload-configuration": { "pass": 3, "fail": 8, "warn": 2, "na": 0 },
    "security": { "pass": 7, "fail": 5, "warn": 3, "na": 1 },
    "observability": { "pass": 5, "fail": 2, "warn": 1, "na": 0 },
    "networking": { "pass": 3, "fail": 5, "warn": 2, "na": 0 },
    "storage": { "pass": 3, "fail": 3, "warn": 1, "na": 0 },
    "eks-platform": { "pass": 4, "fail": 3, "warn": 1, "na": 1 },
    "cicd": { "pass": 2, "fail": 3, "warn": 1, "na": 0 },
    "image-security": { "pass": 2, "fail": 4, "warn": 1, "na": 0 },
    "infrastructure": { "pass": 3, "fail": 5, "warn": 1, "na": 0 }
  }
}
```

## Notes

- **Language**: `finding` and `remediation` fields should be in the user's conversation language
- **Ordering**: Findings should be ordered by dimension, then by check_id
- **Infrastructure findings**: Only present if Step 4 was executed
- The JSON file is a **temporary artifact** — the final deliverable is the markdown report.
  However, the JSON is kept alongside the report for potential reuse (diffing, dashboards, CI/CD)
