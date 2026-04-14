[English](README.md) | [中文](README_CN.md)

# Remote Skill Test

An agent skill that automates end-to-end testing of other agent skills on a remote jump host. After updating a skill locally, this skill SSHs to the remote host, updates the installed skills, runs the target skill in a dedicated test directory, retrieves the generated report, and compares it against the previous run.

## Problem Statement

Testing agent skills after local edits currently requires a manual workflow:

- **Manual deployment** — SSH to the jump host, `npx skills add` to update, navigate to the right directory.
- **Manual execution** — Open OpenCode, type the prompt, interact with confirmations.
- **Manual comparison** — Find the previous report, visually diff structure and content, mentally map changes back to SKILL.md edits.

This is tedious and error-prone, especially during iterative skill development.

## What This Skill Does

1. **Collects SSH config and target skill name** from the user (no credentials stored in files).
2. **Reads `test-prompt.md`** from the target skill's directory in the local repo.
3. **SSHs to the remote host** and runs `npx skills add panlm/skills` to update skills.
4. **Creates a timestamped test directory** on the remote host: `~/skill-tests/{timestamp}-{skill-name}/`.
5. **Executes the target skill** via `opencode run` with the assembled prompt (including dependency paths and auto-confirm directives).
6. **Retrieves the generated report** via `scp` back to `./test-results/{skill-name}/`.
7. **Finds the previous run's report** by searching `~/skill-tests/*-{skill-name}/` directories.
8. **Compares reports** — checks structure compliance against SKILL.md template, diffs structural changes between runs, and correlates with recent SKILL.md git changes.
9. **Outputs analysis** — compliance table, change summary, and verdict (PASS / PARTIAL / FAIL).

## Design Decisions

1. **Generic framework, not FIS-specific.** Works with any skill that has a `test-prompt.md`. The prompt template defines what the skill does; this skill only orchestrates execution and comparison.

2. **SSH config asked at runtime.** No IP addresses, usernames, or key paths are stored in any committed file. The skill asks the user every time (or the user can provide an SSH config alias).

3. **test-prompt.md as the contract.** Each testable skill maintains its own `test-prompt.md` with a prompt template. The `{DEPENDENCY_PATH}` placeholder is replaced at runtime with user-provided paths. Auto-confirm directives are appended automatically.

4. **Timestamped directories with skill name.** Remote test directories use `{timestamp}-{skill-name}` format, making it trivial to find the previous run for the same skill and compare reports.

5. **Structure comparison, not data comparison.** Reports from different runs will have different timestamps, resource IDs, and metrics. The comparison focuses on structural compliance (sections, fields, tables) and correlates structural changes with SKILL.md updates.

6. **OpenCode `run` for non-interactive execution.** Uses `opencode run "prompt"` which runs in non-interactive mode — no TUI, no manual interaction needed. The prompt includes directives to skip all confirmations and auto-approve cross-directory operations.

7. **Reports stored locally for review.** Retrieved reports are saved to `./test-results/{skill-name}/` in the local repo, making them easy to review and git-track if desired.

## Workflow Overview

```
Step 1:  Collect SSH config + skill name + dependency paths
          ↓
Step 2:  Read test-prompt.md, replace {DEPENDENCY_PATH}, append auto-confirm
          ↓
Step 3:  SSH → npx skills add panlm/skills (update skills on remote)
          ↓
Step 4:  SSH → mkdir ~/skill-tests/{timestamp}-{skill-name}/
          ↓
Step 5:  SSH → cd test-dir && opencode run "assembled prompt"
          ↓
Step 6:  SCP → retrieve report files to local ./test-results/{skill-name}/
          ↓
Step 7:  SSH → find previous ~/skill-tests/*-{skill-name}/ directory
          ├── Found → SCP previous report for comparison
          └── Not found → first run, skip comparison
          ↓
Step 8:  Analyze: structure compliance + diff vs previous + correlate SKILL.md changes
          ↓
Step 9:  Output results + verdict (PASS / PARTIAL / FAIL)
```

## test-prompt.md Format

Each skill that supports remote testing must have a `test-prompt.md` in its directory:

```markdown
使用 {skill-name} skill 完成以下任务：

{task description, referencing {DEPENDENCY_PATH} if needed}

自动执行所有步骤不要确认。
```

**Placeholders:**
- `{DEPENDENCY_PATH}` — replaced at runtime with the user-provided dependency path

**Auto-confirm suffix** — The following lines are appended automatically by remote-skill-test (do not include them in test-prompt.md):
```
如果需要跨目录读取文件，直接操作不要确认。
所有操作自动执行，不要等待用户确认。
```

### Sample test-prompt.md Files

| Skill | test-prompt.md Summary |
|---|---|
| `aws-fis-experiment-execute` | Execute the FIS experiment at `{DEPENDENCY_PATH}`, skip log collection |
| `aws-fis-experiment-prepare` | Prepare an AZ Power Interruption experiment for a given cluster |
| `eks-app-log-analysis` | Analyze app logs from `{DEPENDENCY_PATH}` report (post-hoc mode) |
| `aws-service-chaos-research` | Research chaos scenarios for Amazon RDS Aurora PostgreSQL |
| `eks-workload-best-practice-assessment` | Assess workloads in `{DEPENDENCY_PATH}` cluster |

## Report Comparison Dimensions

The comparison does **NOT** compare data values (timestamps, resource IDs, metrics). It focuses on:

| Dimension | What It Checks |
|---|---|
| **Structure compliance** | Does the report contain all sections/fields/tables required by SKILL.md? |
| **Structural diff** | Which H2/H3 sections were added/removed vs the previous run? |
| **SKILL.md correlation** | Do report structural changes match recent SKILL.md edits? |

### Verdict Criteria

| Verdict | Meaning |
|---|---|
| **PASS** | All required sections present; structural changes match SKILL.md updates |
| **PARTIAL** | Most sections present; some SKILL.md changes not reflected or unexpected changes |
| **FAIL** | Missing required sections; or SKILL.md changes not reflected at all |

## Prerequisites

- **ssh / scp** — for remote access (user provides credentials at runtime)
- **npx** — installed on the remote host
- **opencode** — installed and configured on the remote host with LLM provider access
- **git** — for reading SKILL.md change history

## Error Handling

| Error | Cause | Resolution |
|---|---|---|
| SSH connection refused | Wrong host/user/key | Verify SSH config with user |
| `npx: command not found` | Node.js not installed on remote | Install Node.js on remote host |
| `opencode: command not found` | OpenCode not installed on remote | Install OpenCode on remote host |
| `test-prompt.md` not found | Skill has no test prompt | Create test-prompt.md in the skill directory |
| `opencode run` timeout | Skill execution takes too long | Increase SSH timeout; check remote logs |
| No report generated | Skill failed or prompt was wrong | Check opencode session output on remote |
| No previous report found | First run for this skill | Skip comparison, output compliance check only |

## Safety Rules

| Rule | Description |
|---|---|
| **No stored credentials** | SSH config asked at runtime, never committed to files |
| **No sensitive data in repo** | IP addresses, hostnames, usernames never appear in committed files |
| **No remote modifications** | Only creates test directories and runs `opencode run` |
| **No remote deletions** | Previous test results are always preserved for comparison |

## Usage Examples

```
"Test the aws-fis-experiment-execute skill remotely"
"远程测试 aws-fis-experiment-prepare skill"
"到跳板机上验证 execute skill 的更新效果"
"Run remote test for eks-workload-best-practice-assessment"
```

## Directory Structure

```
others/remote-skill-test/
├── SKILL.md          # Main skill definition (agent instructions)
├── README.md         # This file (English)
└── README_CN.md      # Chinese documentation
```

## Limitations

- Requires OpenCode installed and configured on the remote host with valid LLM provider API keys.
- `opencode run` runs non-interactively — skills that genuinely require human judgment during execution may not produce correct results.
- SSH timeout may be too short for long-running skills (e.g., FIS experiments that take 10+ minutes). Use `ssh -o ServerAliveInterval=60` if needed.
- Report comparison is structural only — it cannot assess whether the report *content* (insights, recommendations) improved in quality.
- First run for a skill has no previous report to compare against — only structure compliance is checked.
