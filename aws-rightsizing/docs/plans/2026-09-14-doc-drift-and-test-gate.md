# 托管选型上线后的文档漂移与门禁空洞 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉托管服务目标选型上线后遗留的 6 处文档漂移，并堵上「测试门禁静默跳过
56 条断言」这个空洞。

**Architecture:** 零判据变更 —— `references/core.py` 与两份回归 fixture 一个字节不动。
本轮只做两类事：把文档里与实现不符的断言改成实现的实际行为（实现是真值源），
以及给门禁加一条**结构性守卫**，让「文件里的每条断言都真的在门禁里跑过」
可被机器检查，而不是靠人记得给新文件补 runner。

**Tech Stack:** Python 3（`ast` + `subprocess`，无第三方依赖 —— 本机默认 python3
没有 pytest，门禁必须在纯 stdlib 下成立）；Markdown。

**Spec:** 无独立 spec。依据是 `docs/plans/2026-09-13-managed-target-selection-two-fleet-diff.md`
（本轮改的六处文案都是那份改动的扫尾）与 2026-09-14 的第三次独立回放
（同两支机队归档数据，逐值复现该文档全部数字，另发现本 plan 列出的 7 项）。
`docs/README.md` 的流程要求「判据行为要改时先动 specs/」—— 本轮不改判据行为，
故不新增 spec。

## Global Constraints

- **本 repo 公开。** 任何文件都不得出现真实账号 ID、真实资源名、本机绝对路径；
  引用机队一律「机队 A / 机队 B」，路径一律 `~/` 开头。
- **不主动 `git commit` / `git push`。** 每个任务止于「验证通过」，
  提交时机由用户决定（提交时用 `--no-verify`）。
- **改完 `SKILL.md` 或 `references/` 必须同步 `README.md` 与 `README_CN.md`。**
- **严禁改系统目录下的 skill 副本**（`~/.claude/skills/` 等），只改本 repo。
- **`references/core.py`、`tests/fixtures/*.json` 本轮不得改动。** 任务 6 的验证
  就是证明这一点：两份回归基线逐值不变，且归档回放的头条金额逐分不变。
- 文档里**不写会漂移的计数**（测试条数、文件数）——`docs/README.md` 的 A 类观测值
  纪律；本轮删掉的两处旧计数就是它的反例。

---

### Task 1: 门禁守卫（新增测试）

**Files:**
- Create: `tests/test_gate_covers_every_test.py`
- Test: 同上（本任务的产物就是测试）

**Interfaces:**
- Consumes: 无
- Produces: `tests/test_gate_covers_every_test.py` 里的两个模块级函数
  `test_every_file_reports_running_all_of_its_tests()` 与
  `test_this_guard_itself_runs_under_the_gate()`；后续任务不引用它们，
  只需保证门禁循环仍是 `for t in tests/test_*.py; do python3 "$t" || exit 1; done`。

**契约（这条守卫要钉住的东西）：** 每个 `tests/test_*.py` 在
`python3 <file>` 下必须①退出码 0，②stdout 出现 `n/n passed`，
③`n` 等于该文件模块级 `test_*` 函数的个数。三条缺一，门禁就可能在「全绿」
的外观下跳过断言。

- [ ] **Step 1: 写下会失败的测试**

```python
"""门禁必须真的执行每个测试文件里的每条断言。

`SKILL.md` 的门禁是 `for t in tests/test_*.py; do python3 "$t" || exit 1; done`。
没有 `__main__` runner 的文件在这条命令下**退出码 0 而执行 0 条断言** ——
本机默认 python3 不带 pytest，`python3 tests/test_x.py` 只是 import 一遍模块，
断言全在未被调用的函数体里。实测三个文件（`test_rds_criteria` /
`test_managed_target_selection` / `test_regression_managed`）因此从未在门禁里跑过，
而门禁逐个打印成功、退出码 0。

runner 用手写清单枚举 `test_*` 是同一漏洞的细粒度版本：新增的函数不写进清单
就永远不跑，门禁照样全绿。所以本守卫不查「有没有 runner」，
查的是「runner 报告跑了几条」与「文件里定义了几条」是否相等。
"""
import ast
import pathlib
import re
import subprocess
import sys

TESTS = pathlib.Path(__file__).resolve().parent
SELF = pathlib.Path(__file__).resolve()
COUNT_RE = re.compile(r"(\d+)/(\d+) passed")


def _module_level_test_functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.name for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]


def _peer_files():
    return sorted(p for p in TESTS.glob("test_*.py") if p.resolve() != SELF)


def test_every_file_reports_running_all_of_its_tests():
    bad = []
    for p in _peer_files():
        want = len(_module_level_test_functions(p))
        r = subprocess.run([sys.executable, str(p)],
                           capture_output=True, text=True)
        m = COUNT_RE.search(r.stdout)
        if r.returncode != 0:
            bad.append(f"{p.name}: 退出码 {r.returncode}（门禁会中断）")
        elif m is None:
            bad.append(f"{p.name}: 定义了 {want} 条 test_*，门禁下没有打印 "
                       f"`n/n passed` ⇒ 一条都没执行（缺 __main__ runner）")
        elif int(m.group(2)) != want:
            bad.append(f"{p.name}: runner 只枚举了 {m.group(2)} 条，"
                       f"文件里定义了 {want} 条")
        elif int(m.group(1)) != want:
            bad.append(f"{p.name}: {m.group(1)}/{want} 通过")
    assert not bad, ("门禁没有覆盖到下列文件的断言：\n  " + "\n  ".join(bad))


def test_this_guard_itself_runs_under_the_gate():
    """守卫自己也必须被门禁执行，否则它是一条自我豁免的规则。"""
    assert COUNT_RE.pattern in SELF.read_text(encoding="utf-8")
    src = ast.parse(SELF.read_text(encoding="utf-8"))
    assert any(isinstance(n, ast.If) and ast.unparse(n.test).startswith("__name__")
               for n in src.body), "本文件缺 __main__ runner"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"✓ {test_fn.__name__}")
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
```

- [ ] **Step 2: 跑它，确认按预期失败**

Run: `cd aws-rightsizing && python3 tests/test_gate_covers_every_test.py`
Expected: FAIL，且失败文案逐个点名三个文件
（`test_managed_target_selection.py: 定义了 22 条 …`、
`test_rds_criteria.py: 定义了 28 条 …`、
`test_regression_managed.py: 定义了 6 条 …`），
另一条 `test_this_guard_itself_runs_under_the_gate` PASS。
**必须看到这个失败**——它证明守卫抓的是真问题而不是恒真断言。

- [ ] **Step 3: 给三个文件补 runner（最小实现）**

三个文件末尾各加下面这段（**不写手写清单**，按定义顺序自动枚举，
新增函数自动进门禁；`globals()` 是插入序 = 定义序）：

```python
if __name__ == "__main__":
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"✓ {test_fn.__name__}")
        except Exception as e:
            print(f"✗ {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
```

三个文件都已 `import sys`（它们用 `sys.path.insert` 找 `references/`），
不需要新增 import；若某个文件没有，补 `import sys`。

- [ ] **Step 4: 跑守卫，确认转绿**

Run: `cd aws-rightsizing && python3 tests/test_gate_covers_every_test.py`
Expected: `2/2 passed`，退出码 0。

- [ ] **Step 5: 跑全量门禁，确认 13 个文件逐个打印 `n/n passed`**

```bash
cd aws-rightsizing && for t in tests/test_*.py; do
  printf '%-46s' "$t"; python3 "$t" | tail -1
done
```
Expected: 每行末尾 `n/n passed` 且 n 与该文件的函数数一致；
`test_rds_criteria.py` 28/28、`test_managed_target_selection.py` 22/22、
`test_regression_managed.py` 6/6 —— 这 56 条是本任务前从未跑过的。

- [ ] **Step 6: 在 `SKILL.md` 的门禁段写明失效模式**

`SKILL.md` 的「改动 `core.py` 或任何 `references/*.json` 后必须跑测试」
代码块之后，把逐文件清单那段改写为：不写文件计数，逐条列出每个文件防什么
（含本轮前漏列的四个：`agg.jq` 的 `full-window` 档、托管初选目标、
RDS 判据、托管回归基线），并加一句：

> 门禁的通过标准是**每个文件都打印 `n/n passed`**。只看退出码不够：
> 缺 `__main__` runner 的文件在 `python3 <file>` 下退出码 0 而执行 0 条断言
> （本机默认 python3 无 pytest），实测有三个文件、共 56 条断言这样被跳过。
> `tests/test_gate_covers_every_test.py` 现在守住这条：它要求每个文件报告的
> 条数与文件里定义的 `test_*` 个数相等，手写 runner 清单漏掉新函数同样会被抓到。

---

### Task 2: 托管节省的头条口径与 confidence（三处文案对齐实现）

**Files:**
- Modify: `SKILL.md`（汇总口径禁止项一行；RDS 托管小节的 confidence 一行）
- Modify: `references/report-template.md`（托管小节第 2 条）

**Interfaces:**
- Consumes: `references/report-template.md` 的「托管服务的目标机型（进头条，须标 confidence）」
  与「汇总口径」两节是真值源，本任务只让另外两处不再与它们矛盾。
- Produces: 无代码接口。

- [ ] **Step 1: 改 `SKILL.md` 的禁止项**

现文（与同文件「托管节省进头条的路线一/二」及 `report-template.md`
「这条取代了旧裁定」直接矛盾）：

```
- 不得把托管服务候选小计并进头条数字。
```

改为：

```
- 不得把托管服务小计当成第五条口径，也不得在四条口径之外再加一次——
  托管行的 `nb_save_mo` / `b_save_mo` **已经在路线一/二里面**，
  摘要要做的是单列一行「其中托管服务（目标待人工确认）$X」把它从 EC2 侧拆出来
  （定义在 `report-template.md` 的托管小节第 3 条）。
```

- [ ] **Step 2: 改两处 confidence 断言**

`core.py` 的托管分派处（`dispatch()` 内，注释写着「托管行的 confidence：
**只设 `low`**，不设上两档」）只在 `sample_n < min_biz_hours_points` 时写
`confidence = "low"`，其余留空。归档回放实测：31 行托管里 23 行留空、8 行 `low`，
`medium` 一次没出现。所以：

`SKILL.md` 里 `只有 `medium` / `low`，永不 `high`。` 改为：

```
  只有 `low`（样本量低于门限时）或**留空**，永不 `medium` / `high`——
  上两档由 `evaluate()` 的「有无内存数据」决定，托管侧没有那个轴。
```

`references/report-template.md` 托管小节第 2 条同改，并让它与同文件
派生列清单里的「**托管判据行留空**」一致（那一处本来就是对的）。

- [ ] **Step 3: 验证两处不再矛盾**

```bash
cd aws-rightsizing
grep -n "medium.*low\|留空" SKILL.md references/report-template.md | grep -i 托管
grep -n "托管服务小计\|其中托管服务" SKILL.md references/report-template.md
```
Expected: 三个文件位置的表述一致；无「不进头条」类残留。

- [ ] **Step 4: 跑门禁**

Run: `cd aws-rightsizing && for t in tests/test_*.py; do python3 "$t" >/dev/null || echo "FAIL $t"; done`
Expected: 无输出（`test_no_duplicated_constants.py` 会检查散文是否复述阈值常量，
本步没有引入数字，应照常通过）。

---

### Task 3: `sample-solve.md` 的托管结语

**Files:**
- Modify: `references/sample-solve.md`（托管样例的结语两行）

**Interfaces:**
- Consumes: 同文件上方的字段表已经写了 `candidates` / `cur_usd` / `arch`，
  本任务只修尾部与之矛盾的结语。
- Produces: 无。

- [ ] **Step 1: 确认样例输出仍然成立（改文案前先验事实）**

样例输入的托管行**没有** `candidates`，所以当前实现走兼容路径、不出目标 ——
即样例的输出块（`db-EX-01 verdict=downsize-candidate …`）没有过期，
过期的只有那句「三个托管判据都没有候选机型选型」。先证明这一点：

```bash
cd aws-rightsizing && python3 tests/test_sample_reproduces.py | tail -1
```
Expected: `1/1 passed`（该测试用样例输入跑 `core.py` 并断言四个 verdict 分支可达）。

- [ ] **Step 2: 改结语**

现文：

```
三个托管判据都**没有候选机型选型**，只输出结论与 `blockers`：node type 的价格与
规格映射在采集侧，且降配需变更窗口，候选由人工在变更方案里定。
```

改为：

```
**本样例的托管行没有 `candidates`**，所以走的是兼容路径：只输出结论与
`blockers`，两列目标恒空。给了 `candidates` + `cur_usd` + `arch`，同一份判据会
选出初选目标与月省（`nonburst` / `burst` / `nb_save_mo` / `b_save_mo`），
并必带一条「目标为本 skill 初选、须人工确认」的 blocker ——
口径与代价见 `report-template.md` 的「托管服务的目标机型」一节。
人工的角色是**审核初选**，不是选型。
```

- [ ] **Step 3: 验证**

```bash
cd aws-rightsizing && grep -n "没有候选机型选型" references/sample-solve.md; \
  python3 tests/test_sample_reproduces.py | tail -1
```
Expected: grep 无命中；`1/1 passed`。

---

### Task 4: `SKILL.md` 两处结构缺陷

**Files:**
- Modify: `SKILL.md`（易错项速查表尾部的空行；测试文件清单段）

**Interfaces:**
- Consumes: Task 1 Step 6 已改写测试清单段；本任务只处理表格空行与残留计数。
- Produces: 无。

- [ ] **Step 1: 合回被切断的表格行**

「假定资源规格在窗口内不变」那一行与上一行之间有一个空行，
Markdown 因此把它渲染成一张**没有表头**的独立表格。删掉那个空行，
让它回到易错项速查表内（该行是表的最后一行，其后仍是空行 + `## references`）。

- [ ] **Step 2: 确认表格结构完整**

```bash
cd aws-rightsizing && python3 - <<'PY'
import re, pathlib
lines = pathlib.Path("SKILL.md").read_text(encoding="utf-8").splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("## 易错项速查"))
end = next(i for i, l in enumerate(lines[start:], start) if l.startswith("## references"))
block = lines[start:end]
blanks = [i for i, l in enumerate(block) if l.strip() == ""]
rows = [l for l in block if l.startswith("|")]
print(f"表内行数 {len(rows)}，块内空行位置 {blanks}")
assert blanks and max(blanks) == len(block) - 1, "表中间仍有空行 ⇒ 表会被切断"
PY
```
Expected: 打印行数，且断言通过（唯一的空行在 `## references` 之前）。

- [ ] **Step 3: 跑门禁**

Run: `cd aws-rightsizing && python3 tests/test_no_duplicated_constants.py | tail -1`
Expected: `7/7 passed`。

---

### Task 5: README 同步（repo 硬规则）

**Files:**
- Modify: `../README.md`（`aws-rightsizing` 行）
- Modify: `../README_CN.md`（`aws-rightsizing` 行）

**Interfaces:**
- Consumes: 无
- Produces: 无

- [ ] **Step 1: 改两份 README 的 `aws-rightsizing` 行**

两处都要改，且改法对应：
① 删掉 `guarded by 100 tests` / `由 100 个测试守护` —— 计数已漂移（当前 167 条），
且它是 A 类观测值，写在散文里必然再漂；
② 补上本轮之前就已上线、但 README 从未提过的能力：托管服务（RDS / ElastiCache /
MSK）判「可以降」时给出**初选目标机型与月省**，须人工审核。

英文改为（整行替换 `guarded by …` 那句）：

```
All verdict logic lives in a single deterministic `references/core.py` — including
first-pass target instance classes for RDS / ElastiCache / MSK, flagged for human
review — and is guarded by a per-file regression gate over a desensitized
real-fleet baseline.
```

中文对应改为：

```
全部判据集中在确定性的 `references/core.py`，含 RDS / ElastiCache / MSK 的初选目标
机型（须人工审核），并由逐文件回归门禁守护，含一份脱敏真实机队的基线。
```

- [ ] **Step 2: 验证两份 README 已同步且不含旧计数**

```bash
cd "$(git rev-parse --show-toplevel)"
grep -c "100 tests\|100 个测试" README.md README_CN.md
grep -n "aws-rightsizing" README.md README_CN.md | grep -c "core.py"
```
Expected: 第一条两个文件都 `0`；第二条 `2`。

---

### Task 6: 收尾验证（证明零判据变更）

**Files:**
- Modify: `docs/README.md`（plans 表加本 plan 一行）

**Interfaces:**
- Consumes: 前五个任务的产物
- Produces: 无

- [ ] **Step 1: 全量门禁**

```bash
cd aws-rightsizing && for t in tests/test_*.py; do
  printf '%-46s' "$t"; python3 "$t" | tail -1
done
```
Expected: 13 个文件全部 `n/n passed`，无 `✗`。

- [ ] **Step 2: 证明判据行为未变**

```bash
cd "$(git rev-parse --show-toplevel)" && \
  git diff -- aws-rightsizing/references/core.py aws-rightsizing/tests/fixtures/
```
Expected: fixtures 无输出；`core.py` **只允许一处注释改动**（Task 7 的脱敏），
不得有任何语句变化。行为未变由两条证据支撑，不靠"文件未动"：
`test_regression_fleet` / `test_regression_managed` 逐值通过，
以及 Step 4 的归档回放产出逐字节相同。

（本 plan 的 Global Constraints 原写「`core.py` 本轮不得改动」。
Task 7 的隐私修复优先级高于这条自设约束 —— 隐私规则是 repo 硬规则，
而该约束的**目的**是「判据行为不变」，注释改动不触碰它。
约束与现实不一致时改约束的措辞，不是悄悄绕过验证。）

- [ ] **Step 3: 三条安全自检**

按 `SKILL.md` §6 的三条 grep 跑，全部须打印 `CLEAN`。

- [ ] **Step 4: 归档回放复算（可选但推荐）**

若私有工作区仍有两支机队的归档目录，重跑一次离线回放，
断言两个 profile 的头条金额与 `2026-09-13-managed-target-selection-two-fleet-diff.md`
表里的四个数逐分相同（机队 A `$6,375.23` / `$5,253.67`，
机队 B `$2,225.33` / `$2,089.99`）。回放脚本不在本仓库。

- [ ] **Step 5: 把本 plan 加进 `docs/README.md` 的 plans 表**

```
| [2026-09-14-doc-drift-and-test-gate.md](./plans/2026-09-14-doc-drift-and-test-gate.md) | 托管选型上线后的六处文档漂移（托管节省的头条口径、托管行 confidence 只有 low、样例结语、被空行切断的表格、两份 README）；门禁新增结构性守卫：缺 `__main__` runner 的文件在 `python3 <file>` 下退出码 0 而执行 0 条断言，实测 56 条从未跑过 |
```

- [ ] **Step 6: 不提交**

按 repo 规则，**不主动 `git commit` / `git push`**；把改动清单报告给用户，
由用户决定提交时机（提交时用 `--no-verify`）。

---

### Task 7: 脱敏（执行中发现，本 plan 之外）

**Files:**
- Modify: `references/core.py`（一处注释）
- Modify: `tests/test_managed_target_selection.py`（一处 docstring）
- Modify: `docs/plans/2026-09-13-managed-target-selection.md`
- Modify: `docs/specs/2026-09-13-managed-target-selection-design.md`（两处）

**背景。** Task 6 的隐私自查（本 plan Global Constraints 的那条）在**已提交**的
文件里扫出 5 处真实 AWS 账号 ID —— 不是本轮引入的，是 2026-09-13 那批 commit
带进来的。本 repo 公开，`CLAUDE.md` 把账号 ID 列为禁止项。

- [ ] **Step 1: 全 repo 扫，别只扫本轮改过的文件**

```bash
cd "$(git rev-parse --show-toplevel)"
# ① 12 位账号 ID（排除占位 123456789012）
grep -rnoE '\b[0-9]{12}\b' --include='*.md' --include='*.py' --include='*.json' \
     --include='*.jq' . | grep -v '123456789012'
# ② 真实资源名片段、实例 ID、ARN、本机路径
grep -rnoE 'i-0[0-9a-f]{8,}|arn:aws[^ "]{20,}|/Users/[a-z]+' \
     --include='*.md' --include='*.py' --include='*.json' --include='*.jq' .
```
Expected（修完后）：① 无输出；② 只剩 `<account-id>` / `i-0abc123def` 这类占位。

- [ ] **Step 2: 按 `docs/README.md` 的脱敏惯例改**

「实测教训（客户 <真实账号>）」→「实测教训（真实机队回放）」；
「第二支机队（`<真实账号>`，15 台 RDS 含 1 台 PostgreSQL）」→
「第二支机队（15 台 RDS，含 1 台 PostgreSQL）」。
**结论所依赖的证据（条数、金额、机型、指标值）一律保留** —— 脱敏只删身份，
不删证据。

- [ ] **Step 3: 复扫 + 跑门禁 + 回放**

Expected: Step 1 两条都干净；门禁全绿；归档回放产出与改动前逐字节相同
（证明这些只是注释）。

- [ ] **Step 4: 把规则变成闸门（否则必然复发）**

漏出去的根因不是"没规则"—— 隐私规则 commit 早于那 4 个 commit 就在 main 上了。
根因是**规则只有文字、没有检查**：批量脱敏是一次性动作，之后每个 commit 都可以
重新引入。所以新增 `tests/test_no_private_data.py`，扫全 repo
（git 跟踪 + 未忽略的未跟踪文件）拦四种形态：AWS 账号 ID（占位符
`123456789012` 等放行）、含用户名的本机绝对路径、`i-` + 17 位十六进制的真实
EC2 实例 ID、`AKIA`/`ASIA` 开头的 access key id。例外在该行加注
`privacy-exempt`。红绿验证：造一个同时含三种形态的探针文件 ⇒ 三条断言失败并
逐条给 `file:line`；删掉探针 ⇒ 5/5 通过。
`AGENTS.md` 的隐私小节同步写明「这条规则有闸门」与成因。

- [ ] **Step 5: 告知用户需要重写历史**

`CLAUDE.md` 明写：已 commit 的隐私内容**不能只做一次新 commit 掩盖**。
必须报告给用户：命中哪几个 commit、分支是否已推送、以及重写方式
（分支未推送时 `git rebase -i` / `filter-repo` 都是本地操作，代价低）。
**不代替用户执行重写** —— 那是改历史，须用户明确授权。
