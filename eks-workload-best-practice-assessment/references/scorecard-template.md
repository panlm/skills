# Scorecard Template — Compliance Scorecard

Use this template for the compliance scorecard summary.
This is the highest-level view, designed for quick assessment of overall posture.

**Language**: All content must match the user's conversation language.

---

## EKS Workload Best Practice Scorecard

**Cluster**: `{CLUSTER}` | **Region**: `{REGION}` | **K8s**: {K8S_VERSION} | **EKS**: {PLATFORM_VERSION}
**Assessment Date**: {DATE} | **Scope**: {SCOPE_DESCRIPTION}

---

### Overall Score: {OVERALL_SCORE}% ({OVERALL_RATING})

| Dimension | Score | Pass | Fail | Warn | N/A | Rating |
|-----------|-------|------|------|------|-----|--------|
| Workload Configuration | n% | n | n | n | n | {RATING} |
| Security | n% | n | n | n | n | {RATING} |
| Observability | n% | n | n | n | n | {RATING} |
| Networking | n% | n | n | n | n | {RATING} |
| Storage | n% | n | n | n | n | {RATING} |
| EKS Platform Integration | n% | n | n | n | n | {RATING} |
| CI/CD & GitOps | n% | n | n | n | n | {RATING} |
| Image Security | n% | n | n | n | n | {RATING} |
| **Infrastructure Layer** | n% | n | n | n | n | {RATING} |
| **Overall** | **n%** | **n** | **n** | **n** | **n** | **{RATING}** |

---

### Rating Scale

| Rating | Score Range | Description |
|--------|------------|-------------|
| 🟢 EXCELLENT | >= 90% | Meets almost all best practices |
| 🔵 GOOD | 80% - 89% | Minor improvements recommended |
| 🟡 FAIR | 70% - 79% | Several areas need attention |
| 🟠 NEEDS WORK | 60% - 69% | Significant gaps in best practices |
| 🔴 POOR | < 60% | Critical issues require immediate action |

---

### Top 3 Priorities

1. **{DIMENSION_1}** ({SCORE_1}%) — {BRIEF_DESCRIPTION_OF_MAIN_ISSUES}
2. **{DIMENSION_2}** ({SCORE_2}%) — {BRIEF_DESCRIPTION_OF_MAIN_ISSUES}
3. **{DIMENSION_3}** ({SCORE_3}%) — {BRIEF_DESCRIPTION_OF_MAIN_ISSUES}

---

### Quick Stats

- **Critical Issues**: {COUNT} items require immediate attention
- **Workloads at Risk**: {COUNT} workloads have High-priority FAILs
- **Version Notes**: {Any version-specific observations, e.g., "Cluster on K8s 1.28 — PSA available but not enforced"}

---

## Calculation Rules

1. **Dimension Score**: `PASS / (PASS + FAIL + WARN) * 100` — N/A items excluded
2. **Overall Score**: Weighted average of dimension scores:
   - Workload Configuration: weight 1.5 (most impactful)
   - Security: weight 1.5 (most critical)
   - Observability: weight 1.0
   - Networking: weight 1.0
   - Storage: weight 1.0
   - EKS Platform Integration: weight 1.0
   - CI/CD & GitOps: weight 0.75
   - Image Security: weight 1.0
   - Infrastructure Layer (if included): weight 1.0
3. **Infrastructure Layer row**: Only present if `aws-best-practice-research` was invoked
4. **Top 3 Priorities**: The 3 dimensions with lowest scores
5. **Rating**: Based on score range in the rating scale table above
6. **Language**: Same as user's conversation language
