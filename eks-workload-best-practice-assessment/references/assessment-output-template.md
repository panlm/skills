# Assessment Output Template — Structured Assessment Report

Use this structure for the structured per-dimension assessment report.
This is a more concise format than the full detailed report, focused on
dimension-by-dimension results with clear status tracking.

**Language**: All content must match the user's conversation language.

---

## EKS Workload Assessment Report: `{CLUSTER}` ({REGION})

### Cluster Summary

| Property | Value |
|----------|-------|
| Cluster Name | `{CLUSTER}` |
| Region | `{REGION}` |
| K8s Version | {K8S_VERSION} |
| EKS Platform Version | {PLATFORM_VERSION} |
| Node Count | {NODE_COUNT} across {AZ_COUNT} AZs |
| Instance Types | {INSTANCE_TYPES} |
| Namespaces Assessed | {NAMESPACE_LIST} |
| Total Workloads | {WORKLOAD_COUNT} |
| Assessment Date | {DATE} |

---

### Dimension N: {Dimension Name}

| # | Check Item | Status | Finding |
|---|------------|--------|---------|
| XX-01-hi | **Item name** | 🟢 PASS / 🔴 FAIL / 🟡 WARN / ⚪ N/A | What was observed, including actual values |
| XX-02-md | ... | ... | ... |

*(Repeat for all 8 dimensions)*

---

### Assessment Summary

| Dimension | Pass | Fail | Warn | N/A | Score |
|-----------|------|------|------|-----|-------|
| Workload Configuration | n | n | n | n | n% |
| Security | n | n | n | n | n% |
| Observability | n | n | n | n | n% |
| Networking | n | n | n | n | n% |
| Storage | n | n | n | n | n% |
| EKS Platform Integration | n | n | n | n | n% |
| CI/CD & GitOps | n | n | n | n | n% |
| Image Security | n | n | n | n | n% |
| **Total** | **n** | **n** | **n** | **n** | **n%** |

Score calculation: `PASS / (PASS + FAIL + WARN) * 100` (N/A excluded from calculation)

---

### Critical Issues (Must Fix)

List all FAIL items where Priority = High:

1. **{CHECK_ID}: {Check Item Name}** — {Description of issue and actual value observed}.
   **Remediation**: {Specific action to fix, whether it requires restart}.

---

### Recommendations

**Immediate** (no downtime):
- Item 1...

**Short-term** (rolling restart or maintenance window):
- Item 1...

**Medium-term** (architecture changes):
- Item 1...

---

## Formatting Rules

1. **Status badges**: Use emoji prefix:
   - `🟢 PASS` — meets recommendation
   - `🔴 FAIL` — does not meet
   - `🟡 WARN` — partially meets / cannot fully verify
   - `⚪ N/A` — not applicable
2. **Findings**: Always include actual observed values
3. **Score**: Percentage of PASS among applicable items (PASS + FAIL + WARN)
4. **Critical issues**: Only FAIL + High priority items
5. **Language**: Same as user's conversation
