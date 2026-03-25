# Audit Output Template

Use this structure when generating the live audit report. Replace `{SERVICE}` with the
actual AWS service name and `{RESOURCE_ID}` with the resource identifier.

---

## Live Audit Report: `{RESOURCE_ID}` ({REGION})

### Resource Summary

| Property | Value |
|----------|-------|
| Resource ID | `{RESOURCE_ID}` |
| Engine / Service | {ENGINE} {VERSION} |
| Node Type / Instance Class | {NODE_TYPE} |
| Topology | {TOPOLOGY_DESCRIPTION} |
| Multi-AZ | {ENABLED/DISABLED} |
| Auto Failover | {ENABLED/DISABLED} |
| Encryption At Rest | {ENABLED/DISABLED} |
| Encryption In Transit | {ENABLED/DISABLED} |
| Authentication | {AUTH_METHOD or NONE} |

Add service-specific properties as needed. The goal is to give a quick overview of the
resource before the detailed per-item audit.

---

### Category N: {Category Name}

| # | Check Item | Status | Finding |
|---|------------|--------|---------|
| XX-01-hi | **Item name** | 🟢 PASS / 🔴 FAIL / 🟡 WARN / ⚪ N/A | What was observed, including actual values |
| XX-02-md | ... | ... | ... |

Repeat for all 5 categories.

---

### Audit Summary

| Category | Pass | Fail | Warn | N/A |
|----------|------|------|------|-----|
| HA Architecture | n | n | n | n |
| Disaster Recovery | n | n | n | n |
| Failover Planning | n | n | n | n |
| Security Configuration | n | n | n | n |
| Others | n | n | n | n |
| **Total** | **n** | **n** | **n** | **n** |

---

### Critical Issues (Must Fix)

List all FAIL items where Priority = High. For each:

1. **{CHECK_ID}: {Check Item Name}** — {Description of the issue and the specific value observed}.
   **Remediation**: {Specific action to fix, including whether it requires resource recreation}.

---

### Recommendations

Group remediation actions by urgency:

**Immediate** (can fix in-place, no downtime):
- Item 1...
- Item 2...

**Short-term** (may require maintenance window or resource recreation):
- Item 1...
- Item 2...

**Medium-term** (optimization, monitoring improvements):
- Item 1...
- Item 2...

---

## Formatting Rules

1. **Status badges**: Use emoji prefix for visual distinction:
   - `🟢 PASS` — green, meets recommendation
   - `🔴 FAIL` — red, does not meet recommendation
   - `🟡 WARN` — yellow, cannot fully verify or partially meets
   - `⚪ N/A` — white, check does not apply
2. **Findings**: Always include the actual observed value, not just "not configured".
   Good: "`SnapshotRetentionLimit: 0` — automatic backups are disabled"
   Bad: "Backups not configured"
3. **Critical issues**: Only list items that are both FAIL and Priority=High
4. **Recommendations**: Be specific about which items can be fixed in-place vs. require recreation
5. **Language**: Follow the same language as the conversation (Chinese, English, etc.)
