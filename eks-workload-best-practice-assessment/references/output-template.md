# Output Template — Detailed Markdown Report

Use this structure for the full detailed assessment report.
Replace `{CLUSTER}`, `{REGION}`, and other placeholders with actual values.

**Language**: All content must be in the same language as the user's conversation.
The template below uses English as an example — translate all content if the
conversation is in another language.

---

## EKS Workload Best Practice Assessment Report

### Cluster: `{CLUSTER}` | Region: `{REGION}`

**Assessment Date**: {DATE}
**K8s Version**: {K8S_VERSION} | **EKS Platform**: {PLATFORM_VERSION}
**Scope**: {SCOPE_DESCRIPTION} (e.g., "All namespaces excluding system" or "namespace: production, staging")
**Nodes**: {NODE_COUNT} nodes across {AZ_COUNT} AZs ({INSTANCE_TYPES})
**Workloads Assessed**: {WORKLOAD_COUNT} Deployments, {STATEFULSET_COUNT} StatefulSets, {DAEMONSET_COUNT} DaemonSets

---

### Compliance Scorecard

*(Insert scorecard from scorecard-template.md here)*

---

### Dimension 1: Workload Configuration

| # | Check Item | Status | Affected Workloads | Finding |
|---|------------|--------|--------------------|---------|
| WL-01-hi | **Resource requests set** | PASS / FAIL / WARN / N/A | ns/deployment-name, ... | Actual observation with values |
| WL-02-hi | **Resource limits set** | ... | ... | ... |

### Dimension 2: Security

| # | Check Item | Status | Affected Workloads | Finding |
|---|------------|--------|--------------------|---------|
| SEC-01-hi | **Pod Security Admission enforced** | PASS / FAIL / WARN / N/A | namespace-list | Actual observation |
| SEC-02-hi | ... | ... | ... | ... |

### Dimension 3: Observability

| # | Check Item | Status | Finding |
|---|------------|--------|---------|
| OBS-01-hi | **Container Insights enabled** | PASS / FAIL / WARN / N/A | Actual observation |

### Dimension 4: Networking

| # | Check Item | Status | Affected Workloads | Finding |
|---|------------|--------|--------------------|---------|
| NET-01-md | **Service type appropriate** | PASS / FAIL / WARN / N/A | ns/service-name | Actual observation |

### Dimension 5: Storage

| # | Check Item | Status | Affected Workloads | Finding |
|---|------------|--------|--------------------|---------|
| STR-01-md | **PVC with appropriate StorageClass** | PASS / FAIL / WARN / N/A | ns/pvc-name | Actual observation |

### Dimension 6: EKS Platform Integration

| # | Check Item | Status | Finding |
|---|------------|--------|---------|
| EKS-01-hi | **EKS Addon versions current** | PASS / FAIL / WARN / N/A | Actual observation |

### Dimension 7: CI/CD & GitOps

| # | Check Item | Status | Finding |
|---|------------|--------|---------|
| CICD-01-md | **Deployment strategy defined** | PASS / FAIL / WARN / N/A | Actual observation |

### Dimension 8: Image Security

| # | Check Item | Status | Affected Images | Finding |
|---|------------|--------|-----------------|---------|
| IMG-01-hi | **ECR image scanning enabled** | PASS / FAIL / WARN / N/A | repo/image:tag | Actual observation |

---

### Infrastructure Layer Results (from aws-best-practice-research)

*(If infrastructure layer assessment was included, insert the merged results here.
Use the same table format as the aws-best-practice-research assessment output.)*

---

### Per-Workload Detail

For each workload, summarize its check results:

#### `{NAMESPACE}/{WORKLOAD_NAME}` ({KIND})

| Dimension | Pass | Fail | Warn | N/A |
|-----------|------|------|------|-----|
| Workload Config | n | n | n | n |
| Security | n | n | n | n |
| Networking | n | n | n | n |
| ... | ... | ... | ... | ... |

**Key Issues**:
- {ISSUE_1}: {Description and remediation}
- {ISSUE_2}: {Description and remediation}

*(Repeat for each workload)*

---

### Critical Issues (Must Fix)

List all FAIL items where Priority = High. For each:

1. **{CHECK_ID}: {Check Item Name}** — {Description of issue and actual value observed}.
   **Affected**: {list of workloads}
   **Remediation**: {Specific action, whether it requires restart, example YAML patch}

---

### Recommendations

Group remediation actions by urgency:

**Immediate** (can fix in-place, no downtime):
- Item 1...
- Item 2...

**Short-term** (may require rolling restart or maintenance window):
- Item 1...
- Item 2...

**Medium-term** (architecture changes, new tooling):
- Item 1...
- Item 2...

---

### Data Sources

| Source | URL | Used For |
|--------|-----|----------|
| EKS Best Practices Guide - Reliability | https://docs.aws.amazon.com/eks/latest/best-practices/reliability.html | WL, NET dimensions |
| EKS Best Practices Guide - Security | https://docs.aws.amazon.com/eks/latest/best-practices/security.html | SEC, IMG dimensions |
| K8s Official Docs - Pod Security Standards | https://kubernetes.io/docs/concepts/security/pod-security-standards/ | SEC dimension |
| ... | ... | ... |

---

## Formatting Rules

1. **Status badges**: Use emoji prefix for visual distinction:
   - `🟢 PASS` — meets recommendation
   - `🔴 FAIL` — does not meet recommendation
   - `🟡 WARN` — partially meets or cannot fully verify
   - `⚪ N/A` — check does not apply
2. **Findings**: Always include actual observed values, not just "not configured".
   Good: "`resources.requests.memory: 128Mi, resources.limits.memory: 256Mi` — requests set but ratio is 1:2"
   Bad: "Resources configured"
3. **Affected workloads**: List as `namespace/name` format
4. **Critical issues**: Only list items that are both FAIL and Priority=High
5. **Per-workload detail**: Only include workloads that have at least one FAIL item
6. **Language**: Follow the user's conversation language
