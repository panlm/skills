# Output Template

Use this exact structure when generating the best-practice checklist.
Replace `{SERVICE}` with the actual AWS service name.

**Language**: All table headers, descriptions, and text must be in the same language as
the user's conversation. The template below uses English as an example — translate
all content (including category titles, column headers, and descriptions) if the
conversation is in another language.

---

## {SERVICE} Best Practice Checklist (HA/DR/Security)

### Category 1: High Availability Architecture

| # | Check Item | Description | Source | Priority |
|---|------------|-------------|--------|----------|
| HA-01-hi | **Item name** | What to check, specific thresholds, conditions | Source tag | High |
| HA-02-md | ... | ... | ... | Medium |

### Category 2: Disaster Recovery

| # | Check Item | Description | Source | Priority |
|---|------------|-------------|--------|----------|
| DR-01-hi | **Item name** | What to check, specific thresholds, conditions | Source tag | High |
| DR-02-md | ... | ... | ... | Medium |

### Category 3: Failover Planning

| # | Check Item | Description | Source | Priority |
|---|------------|-------------|--------|----------|
| FP-01-hi | **Item name** | What to check, specific thresholds, conditions | Source tag | High |
| FP-02-md | ... | ... | ... | Medium |

### Category 4: Security Configuration

| # | Check Item | Description | Source | Priority |
|---|------------|-------------|--------|----------|
| SEC-01-hi | **Item name** | What to check, specific thresholds, conditions | Source tag | High |
| SEC-02-md | ... | ... | ... | Medium |

### Category 5: Others

| # | Check Item | Description | Source | Priority |
|---|------------|-------------|--------|----------|
| OT-01-md | **Item name** | What to check, specific thresholds, conditions | Source tag | Medium |
| OT-02-lo | ... | ... | ... | Low |

---

### Source Annotations

| Abbreviation | Source |
|--------------|--------|
| WA-REL | Well-Architected Lens - Reliability Pillar |
| WA-SEC | Well-Architected Lens - Security Pillar |
| WA-PE | Well-Architected Lens - Performance Efficiency Pillar |
| WA-OE | Well-Architected Lens - Operational Excellence Pillar |
| WA-CO | Well-Architected Lens - Cost Optimization Pillar |
| Security Hub [{Service}.N] | AWS Security Hub CSPM control |
| re:Post | AWS re:Post knowledge center article |
| Official Docs | Service user guide |
| AWS Blog | AWS official blog post |
| Whitepaper | AWS whitepaper |

### Key Reference Links

- [Link 1 title](URL)
- [Link 2 title](URL)
- ...

List the 5-10 most important documentation pages used to compile this checklist.

---

## Formatting Rules

1. **Check item names** should be bold and concise (e.g., "Enable Multi-AZ Auto Failover")
2. **Descriptions** should include:
   - What specifically to check
   - Specific values/thresholds when available (e.g., ">= 2 replicas", ">= 25%")
   - Conditions when the check applies (e.g., "only if cluster mode enabled")
3. **Source tags** use the abbreviation table above. Multiple sources separated by " / "
4. **Priority** assignment:
   - **High**: Data loss risk, no encryption, no authentication, no backup, no HA
   - **Medium**: Non-optimal configuration, missing DR, missing monitoring
   - **Low**: Performance optimization, cost tags, non-latest instance types
5. Each category should have at minimum 3 items, typically 5-15 items
6. Total checklist should have 30-50 items for a well-documented service
