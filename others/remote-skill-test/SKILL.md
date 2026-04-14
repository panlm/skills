---
name: remote-skill-test
description: >
  Use when the user wants to test an agent skill on a remote jump host after
  updating it locally. Triggers on "test skill remotely", "remote test",
  "远程测试 skill", "到跳板机上测试", "验证 skill 更新效果".
  Does NOT run the target skill locally — only orchestrates remote execution
  and report comparison.
---

# Remote Skill Test

Orchestrate end-to-end testing of agent skills on a remote jump host. After
the user updates a skill locally, this skill SSHs to the remote host, updates
the installed skills, runs the target skill via `opencode run` in a dedicated
test directory, retrieves the generated report, and compares it against the
previous run to verify that changes match the skill update.

## Output Language Rule

Detect the language of the user's conversation and use the **same language** for all output.
- Chinese input -> Chinese output
- English input -> English output

## Prerequisites

Required tools:
- **ssh** — access to the remote jump host
- **scp** — for retrieving reports from the remote host
- **npx** — installed on the remote host (for `npx skills add`)
- **opencode** — installed and configured on the remote host

## Workflow

```dot
digraph test_flow {
    "Collect SSH config\n+ skill name" [shape=box];
    "SSH: create test dir" [shape=box];
    "SSH: install skills\n(project level in test dir)" [shape=box];
    "SSH: find + read test-prompt.md\nfrom installed skill" [shape=box];
    "SSH: opencode run\n(output to log)" [shape=box];
    "SCP: retrieve report + log" [shape=box];
    "Find previous report" [shape=diamond];
    "Compare reports\nvs SKILL.md changes" [shape=box];
    "Output analysis" [shape=box];

    "Collect SSH config\n+ skill name" -> "SSH: create test dir";
    "SSH: create test dir" -> "SSH: install skills\n(project level in test dir)";
    "SSH: install skills\n(project level in test dir)" -> "SSH: find + read test-prompt.md\nfrom installed skill";
    "SSH: find + read test-prompt.md\nfrom installed skill" -> "SSH: opencode run\n(output to log)";
    "SSH: opencode run\n(output to log)" -> "SCP: retrieve report + log";
    "SCP: retrieve report + log" -> "Find previous report";
    "Find previous report" -> "Compare reports\nvs SKILL.md changes" [label="Found"];
    "Find previous report" -> "Output analysis" [label="First run"];
    "Compare reports\nvs SKILL.md changes" -> "Output analysis";
}
```

### Step 1: Collect Information

Gather the following from the user. **Do NOT proceed until all required items
are provided.**

**Required:**
1. **Target skill name** — which skill to test (e.g., `aws-fis-experiment-execute`)
2. **SSH access** — how to connect to the remote jump host. Ask the user:
   ```
   How do I SSH to the remote jump host?
   Please provide: user@host, and the SSH key path (or SSH config alias).
   Example: participant@10.0.1.50 with key ~/.ssh/my-key.pem
   ```
3. **Dependency info** (if the skill requires external resources) — ask the user:
   ```
   Does this skill depend on pre-existing resources on the remote host?
   If yes, provide the path(s). Example: experiment directory at
   ~/fis-experiments/2026-04-10-az-power-interruption-my-cluster/
   ```

**Derived from local repo:**
- `SKILL.md` — read from `{SKILL_DIR}/SKILL.md` for report structure requirements
- Git diff of SKILL.md — for comparing against report changes

**Derived from remote installed skill (after Step 4):**
- `test-prompt.md` — automatically discovered by searching for `test-prompt.md`
  under `${TEST_DIR}` on the remote host after skill installation. Different agents
  install skills to different directories (e.g., `.agents/skills/`, `.claude/skills/`,
  `.kiro/skills/`), so the path is NOT hardcoded — use `find` to locate it.

**If `test-prompt.md` does not exist** anywhere under the test directory,
stop and inform the user:
```
No test-prompt.md found for skill {SKILL_NAME} under ${TEST_DIR}.
Please ensure test-prompt.md is included in the skill package.
See others/remote-skill-test/README.md for format details.
```

### Step 2: SSH — Create Test Directory

Create the timestamped test directory on the remote host **first**, before
installing skills. All subsequent steps operate inside this directory.

```bash
TIMESTAMP=$(date -u +%Y-%m-%d-%H-%M-%S)
TEST_DIR="~/skill-tests/${TIMESTAMP}-{SKILL_NAME}"

ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "mkdir -p ${TEST_DIR}"
```

Store `TEST_DIR` for subsequent steps.

### Step 3: SSH — Install Target Skill (Project Level)

Install **only the target skill** inside the test directory at project level
(not global). Use the `--skill {SKILL_NAME}` flag to avoid installing all
skills from the repository, which saves time and reduces noise.

**Important:** The remote host may use `nvm` for Node.js. Use `bash -i -c`
to load `.bashrc` environment variables (LLM provider URL, API keys, etc.)
that the interactive guard in `.bashrc` would otherwise block.

```bash
ssh -t -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "bash -i -c 'source ~/.nvm/nvm.sh 2>/dev/null; \
   cd ${TEST_DIR} && npx skills add panlm/skills --skill {SKILL_NAME} -y'"
```

`{SKILL_NAME}` is the target skill name collected in Step 1 (e.g.,
`aws-best-practice-research`, `aws-fis-experiment-execute`).

Verify the output shows "Installation complete" and lists **only the target
skill**. If it fails, show the error and stop.

### Step 4: SSH — Find and Read test-prompt.md

Locate `test-prompt.md` from the **remote installed skill directory** after
installation in Step 3. Different agents install skills to different paths
(`.agents/skills/`, `.claude/skills/`, `.kiro/skills/`, etc.), so use `find`
to auto-discover the file:

```bash
# Find test-prompt.md for the target skill under the test directory
PROMPT_FILE=$(ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "find ${TEST_DIR} -path '*/{SKILL_NAME}/test-prompt.md' -type f 2>/dev/null | head -1")

# Read the file content
ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "cat ${PROMPT_FILE}"
```

If the file is not found (empty `PROMPT_FILE`), stop and inform the user (see Step 1 error message).

Replace the `{DEPENDENCY_PATH}` placeholder (if present) with the actual
dependency path provided by the user in Step 1.

Append the following suffix to the prompt (always):
```
如果需要跨目录读取文件，直接操作不要确认。
所有操作自动执行，不要等待用户确认。
```

Store the assembled prompt as `FULL_PROMPT`.

### Step 5: SSH — Execute Skill via OpenCode (Output to Log)

Run `opencode run` on the remote host inside the test directory. Capture
**all output** (stdout + stderr) to a log file for diagnostics.

```bash
ssh -t -i {SSH_KEY} -o StrictHostKeyChecking=no \
  -o ServerAliveInterval=60 {USER}@{HOST} \
  "bash -i -c 'source ~/.nvm/nvm.sh 2>/dev/null; \
   cd ${TEST_DIR} && \
   opencode run \
     --dangerously-skip-permissions \
     \"${FULL_PROMPT}\" \
     2>&1 | tee ${TEST_DIR}/opencode-run.log'"
```

**Key flags:**
- `--dangerously-skip-permissions` — auto-approve all permission prompts
  (cross-directory reads, file writes, etc.) so the run is fully non-interactive
- `2>&1 | tee ...log` — capture all output to `opencode-run.log` while also
  displaying it in the terminal for real-time monitoring
- `bash -i` — loads `.bashrc` environment variables (LLM provider config)
- `ServerAliveInterval=60` — prevents SSH timeout for long-running skills

**This step may take several minutes** depending on the skill being tested
(e.g., FIS experiments run for minutes). Wait for the command to complete.

If the command times out or fails, the log file may still contain partial
output useful for diagnostics. Proceed to Step 6 to retrieve it.

### Step 6: SCP — Retrieve Reports and Log

Each test run is stored in its own timestamped subdirectory under
`test-results/{SKILL_NAME}/`. The `{TIMESTAMP}` used here is the same one
from Step 3 (when the remote test directory was created).

List files in the remote test directory to find generated reports and the log:

```bash
ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "ls -la ${TEST_DIR}/"
```

Create the local run directory and copy all report files (`.md` files,
excluding README.md) and the execution log. **Keep the original remote
file names** — do not rename them:

```bash
LOCAL_RUN_DIR="./test-results/{SKILL_NAME}/{TIMESTAMP}/"
mkdir -p "${LOCAL_RUN_DIR}"

scp -i {SSH_KEY} -o StrictHostKeyChecking=no \
  {USER}@{HOST}:"${TEST_DIR}/*.md" "${LOCAL_RUN_DIR}/"

# Also retrieve the execution log for diagnostics
scp -i {SSH_KEY} -o StrictHostKeyChecking=no \
  {USER}@{HOST}:"${TEST_DIR}/opencode-run.log" "${LOCAL_RUN_DIR}/"
```

### Step 7: Find and Retrieve Previous Report

Search for the previous test run of the same skill **on the remote host**:

```bash
ssh -i {SSH_KEY} -o StrictHostKeyChecking=no {USER}@{HOST} \
  "ls -d ~/skill-tests/*-{SKILL_NAME} 2>/dev/null | sort | tail -2 | head -1"
```

This returns the second-to-last directory (the previous run). If only one
directory exists (first run), skip comparison and output the current report
analysis only.

If a previous directory is found, retrieve its report **into the same local
run directory** (`LOCAL_RUN_DIR`) so all comparison materials are co-located.
The previous report's file name naturally differs from the current one (both
have different timestamps embedded), so there is no collision:

```bash
PREV_DIR="{result from above}"
scp -i {SSH_KEY} -o StrictHostKeyChecking=no \
  {USER}@{HOST}:"${PREV_DIR}/*.md" "${LOCAL_RUN_DIR}/"
```

After this step, the local run directory contains everything needed for
comparison:

```
test-results/{SKILL_NAME}/{TIMESTAMP}/
├── 2026-04-14-05-51-49-demo-cluster-assessment-report.md   # current report
├── 2026-04-14-05-29-47-amazon-eks-best-practice-checklist.md  # previous report
├── opencode-run.log                                        # execution log
└── test-analysis.md                                        # (generated in Step 9)
```

Read both report files from `LOCAL_RUN_DIR` for comparison in Step 8. The
current report is the one whose timestamp is closest to `{TIMESTAMP}`; the
other `.md` file(s) are from the previous run.

### Step 8: Analyze and Compare Reports

Perform the following analysis:

#### 8a. Report Structure Compliance

Read the target skill's `SKILL.md` from the local repo. Extract the report
template (look for markdown code blocks defining the report structure — headings,
tables, required fields).

Check the new report against each required element:

| Check | Method |
|---|---|
| Required sections present | Match H2/H3 headings from template |
| Required fields present | Match `**Field:**` patterns from template |
| Required tables present | Match table headers from template |
| Conditional sections correct | If `COLLECT_APP_LOGS=false`, log sections should be absent |

#### 8b. Diff Against Previous Report (if available)

Compare the structural differences between the new and previous reports:

- **Added sections** — new H2/H3 headings not in previous report
- **Removed sections** — H2/H3 headings in previous but not in new
- **Changed fields** — fields present in both but with different structure

Do NOT compare data values (timestamps, resource IDs, metrics) — only structure
and format.

#### 8c. Correlate with SKILL.md Changes

Read the recent git changes to the target skill's SKILL.md:

```bash
git log --oneline -5 -- {SKILL_DIR}/SKILL.md
git diff HEAD~1 -- {SKILL_DIR}/SKILL.md
```

For each structural change in the report (from 8b), check whether it
corresponds to a SKILL.md update. Flag:

- **Expected changes** — report differences that match SKILL.md updates
- **Unexpected changes** — report differences with no corresponding SKILL.md change
- **Missing changes** — SKILL.md updates that should have affected the report but didn't

### Step 9: Output Results

Present the analysis to the user:

```
## Remote Skill Test Results

**Skill:** {SKILL_NAME}
**Test directory:** {TEST_DIR}
**Report file:** {REPORT_FILENAME}

### Structure Compliance
| Required Section | Present | Notes |
|---|---|---|
| {section} | Yes/No | {details} |

### Changes vs Previous Run
(Skip if first run)
| Change Type | Section | Details |
|---|---|---|
| Added | {section} | {description} |
| Removed | {section} | {description} |

### Correlation with SKILL.md Updates
| SKILL.md Change | Report Impact | Status |
|---|---|---|
| {change description} | {expected report change} | Match / Missing / Unexpected |

### Verdict
{Overall assessment: PASS / PARTIAL / FAIL with explanation}
```

Save this analysis to `./test-results/{SKILL_NAME}/{TIMESTAMP}/test-analysis.md`.

## test-prompt.md Format

Each skill that supports remote testing should have a `test-prompt.md` file in
its directory. The format is:

```markdown
使用 {skill-name} skill 完成以下任务：

{task description, may reference {DEPENDENCY_PATH} placeholder}

如果需要跨目录读取文件，直接操作不要确认。
所有操作自动执行，不要等待用户确认。
```

**Placeholders:**
- `{DEPENDENCY_PATH}` — replaced at runtime with the user-provided dependency path

The trailing "不要确认" lines may be omitted from test-prompt.md — they are
automatically appended by this skill (Step 2).

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

1. **Never store SSH credentials in files.** Always ask the user at runtime.
2. **Never expose IP addresses, hostnames, or usernames** in committed files.
3. **Never modify files on the remote host** beyond creating the test directory
   and running `opencode run`.
4. **Never delete remote directories** — previous test results are kept for comparison.
