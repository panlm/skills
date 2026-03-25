# Output Template

Use this structure when generating the chaos testing report. Replace `{SERVICE}`,
`{REGION}`, and other placeholders with actual values.

**Language**: All table headers, descriptions, and text must be in the same language as
the user's conversation. The template below uses English as an example — translate
all content (including section titles, column headers, and descriptions) if the
conversation is in another language (e.g., Chinese).

---

## {SERVICE} HA Chaos Testing Report — {REGION} Region

### 1. Executive Summary

Provide a 3-5 sentence overview covering:
- Target service, its HA architecture (Multi-AZ, cluster mode, replication topology, etc.)
- Target region and FIS native support status (how many FIS actions available)
- Which FIS Scenario Library composite scenarios are relevant
- Key testing recommendation

If the report covers **multiple services**, use a summary table:

| Service | Resource Name | HA Architecture | FIS Native Support |
|---|---|---|---|
| **{SERVICE_1}** | `{RESOURCE_ID}` | {HA_DESCRIPTION} | {N} FIS actions |
| **{SERVICE_2}** | `{RESOURCE_ID}` | {HA_DESCRIPTION} | 0 FIS actions |

Followed by a brief paragraph highlighting key findings across all services.

---

### 2-N. Per-Service Sections

For **each service**, create a numbered section (Section 2, 3, 4, ...) with the
following sub-sections. If only one service is being tested, use Section 2 only.

#### {N}. {SERVICE} — {RESOURCE_ID}

##### FIS Native Fault Injection Scenarios

Use this sub-section when FIS has native actions for the service.

**IMPORTANT — Scenario Library deduplication:** Before building this table, check
each FIS action against the Scenario Library composite scenarios in the report.
If an action already appears as a sub-action there (e.g., `aws:rds:failover-db-cluster`
is a sub-action of AZ Power Interruption), you MUST append a note to the
"HA Verification Purpose" cell:

> "(Also sub-action of AZ Power Interruption — see Scenario Library section)"

**All actions covered:** If EVERY FIS action for this service is a Scenario Library
sub-action (e.g., ElastiCache has only `replicationgroup-interrupt-az-power` which
is covered by AZ Power Interruption), OMIT this entire sub-section and replace with:

> All FIS native actions for {SERVICE} are covered by Scenario Library composite
> scenarios. See the Scenario Library and Cross-Cutting section for details.

**Otherwise**, list the remaining actions in this table:

| # | Test Scenario | FIS Action | Description | HA Verification Purpose |
|---|---|---|---|---|
| 1 | {scenario name} | `aws:{service}:{action}` | {what the action does} | {what resilience property it validates} |

Group scenarios by failure domain when there are many:
1. **Instance/Task Level** — individual resource failure
2. **Storage Level** — disk/volume failure or degradation
3. **Network Level** — connectivity disruption
4. **AZ Level** — availability zone failure simulation

##### Service Built-in Fault Injection

Use this sub-section for service-native fault injection methods (not FIS).

| # | Method | Command/API | What It Simulates |
|---|---|---|---|
| 1 | {method name} | `{CLI command or API call}` | {what it simulates} |

Known built-in capabilities to check:
- **Aurora MySQL/PostgreSQL**: `ALTER SYSTEM CRASH`, `ALTER SYSTEM SIMULATE READ REPLICA FAILURE`
- **RDS Multi-AZ**: `reboot-db-instance --force-failover`
- **ElastiCache**: `test-failover` API
- **DynamoDB**: On-demand backup/restore testing

##### Testing Methods (No Native FIS Actions)

Use this sub-section instead of "FIS Native Fault Injection Scenarios" when the service
has **no native FIS actions**. Include a note explaining this.

> **Note:** AWS FIS does not currently have dedicated actions for {SERVICE} in {REGION}.
> The following approaches use indirect FIS actions, AWS APIs, and manual methods.

###### Indirect FIS Fault Injection

| # | Test Scenario | Method | What It Validates |
|---|---|---|---|
| 1 | {scenario} | `{FIS action or method}` | {what it validates} |

###### AWS API / Console Methods

| # | Test Scenario | Method | What It Validates |
|---|---|---|---|
| 1 | {scenario} | `{CLI/API/Console method}` | {what it validates} |

##### Environment Observations

Brief bullet-point notes about the actual resource configuration discovered during
research. Include:
- Key configuration details (engine, instance type, topology)
- Important observations or warnings
- Architecture notes that affect testing strategy

---

### Scenario Library and Cross-Cutting Section

After all per-service sections, include this section. **Scenario Library composite
scenarios have the highest priority** — they represent AWS's own curated resilience
testing recommendations and simulate realistic multi-service failure patterns.
Cross-cutting actions are supplementary and optional.

#### {N+1}. Scenario Library and Cross-Cutting

For each relevant Scenario Library scenario discovered in Step 2, create a dedicated
sub-section. The most common scenarios are listed below, but include **any** scenario
from the Scenario Library that is relevant to the target service(s).

##### AZ-Level Composite Scenario: Power Interruption

> **AZ Availability: Power Interruption** is a pre-built FIS Scenario Library composite
> experiment that simulates a complete AZ power failure. It orchestrates multiple actions
> simultaneously to create realistic AZ-level fault impact.

###### Environment-Relevant Sub-Actions

| # | Sub-Action | FIS Action | Impact on Environment |
|---|---|---|---|
| 1 | {sub-action name} | `{action}` | {impact on the environment} |

List only the sub-actions that are relevant to the user's environment. Map each
sub-action to the specific resources it would affect (e.g., "Stops EKS nodes in the
affected AZ, triggering Pod rescheduling").

###### Required Resource Tags

| Resource Type | Tag Key | Tag Value | Description |
|---|---|---|---|
| {resource type} | `AzImpairmentPower` | `{value}` | {description} |

###### Why This Scenario Matters Most

Brief paragraph explaining why this composite scenario provides the most realistic
resilience validation. Key point: real AZ failures affect compute, network, and
database simultaneously — testing services individually cannot validate end-to-end
resilience under concurrent failures.

###### Default Duration
- Interruption phase: **30 minutes**
- Recovery phase: **30 minutes**

##### Other Scenario Library Scenarios

If additional Scenario Library scenarios are relevant (e.g., AZ Application Slowdown,
Cross-AZ Traffic Slowdown, Cross-Region Connectivity), add a sub-section for each
following the same structure: description, relevant sub-actions table, resource tags,
and duration.

##### Cross-Cutting Actions — Optional

> Cross-cutting actions are optional supplementary scenarios for testing infrastructure-level
> fault impact on services indirectly.

| # | Test Scenario | FIS Action | Applicable Services |
|---|---|---|---|
| 1 | {scenario} | `{action}` | {which services are affected} |

Cross-cutting actions to include when relevant:
- `aws:network:disrupt-connectivity` — any VPC-based service (simulates AZ network failure)
- `aws:network:disrupt-vpc-endpoint` — PrivateLink services
- `aws:fis:inject-api-internal-error` — AWS API failures (any AWS service control plane)
- `aws:fis:inject-api-throttle-error` — API throttling (any AWS service API calls)
- `aws:fis:inject-api-unavailable-error` — graceful degradation (any AWS service control plane)
- `aws:ec2:stop-instances` / `terminate-instances` — EC2-based services
- `aws:network:route-table-disrupt-cross-region-connectivity` — cross-region DR
- `aws:ssm:send-command` — custom fault injection scripts

**When to include**: only when the user's service runs on EC2, uses VPC networking,
or the user explicitly requests infrastructure-level failure testing. **Skip** when
the user is focused only on service-native failures.

---

### {N+2}. Recommended Test Priority

| Priority | Scenario | Target Service | Reason |
|---|---|---|---|
| **P0 Must Test** | {scenario} | {service} | {why it's critical} |
| **P1 High** | {scenario} | {service} | {why it's important} |
| **P2 Medium** | {scenario} | {service} | {good to have} |
| **P3 Optional** | {scenario} | {service} | {edge case or advanced} |

Priority guidelines:
- **P0**: FIS Scenario Library composite scenarios directly affecting the service; failover / primary failure (impacts RTO)
- **P1**: AZ-level failure, network isolation (multi-AZ resilience); service-specific critical tests
- **P2**: Performance degradation, replica failure (read availability)
- **P3**: API throttling, cross-region DR, cross-cutting actions (advanced scenarios)

**Dedup with Scenario Library:** Do NOT list a FIS action as a separate priority item
if it is already covered as a sub-action of a Scenario Library composite scenario
listed in this same table. For example, if "AZ Power Interruption" is listed as P0
and it already includes `aws:rds:failover-db-cluster` as a sub-action, do NOT add
a separate P0 row for `aws:rds:failover-db-cluster`. The Scenario Library composite
scenario entry already covers it.

---

### {N+3}. Implementation Best Practices

#### Stop Conditions (Safety Guardrails)

| Service | Metric | Alarm Threshold | Description |
|---|---|---|---|
| {SERVICE} | `{CloudWatch metric}` | {threshold} | {description} |

#### Steady State Definition

- **{SERVICE}**: {metrics that define normal operation}

#### DNS / Connection Handling

- **{SERVICE}**: {service-specific reconnection considerations}

#### Blast Radius Control

1. {guidance on starting small}
2. {guidance on progressive escalation}
3. {guidance on AZ isolation}

---

### {N+4}. Reference Materials

| # | Type | Title | Link |
|---|---|---|---|
| 1 | {Docs/Blog/Well-Architected} | {title} | {URL} |

Only include URLs from actual search results or documentation pages read.
Never fabricate links.

---

### {N+5}. Next Steps

Suggest 3-4 actionable next steps tailored to the service(s), for example:
1. Generate a complete FIS experiment template (JSON) for {scenario}
2. Design CloudWatch alarms to use as FIS experiment Stop Conditions
3. Verify {service-specific config} configuration
4. Start execution with the simplest P0 scenario

---

## Formatting Rules

1. **Section numbering** is sequential across the entire report (1, 2, 3, ..., N)
2. **Per-service sections** each get their own numbered section with service name and resource ID
3. **Table consistency**: All tables within the same sub-section type use identical column headers
4. **FIS Action IDs** always in backtick code format: `aws:service:action`
5. **CLI commands** in backtick code format
6. **Service names** in bold when used as labels
7. **Priority labels** in bold: **P0 Must Test**, **P1 High**, **P2 Medium**, **P3 Optional**
8. **Environment observations** use bullet points, keep concise
9. **Scenario Library and Cross-Cutting section**: Scenario Library composite scenarios always come first as the primary content; cross-cutting actions are explicitly marked as optional and come after
10. **Language**: Follow the same language as the conversation throughout
