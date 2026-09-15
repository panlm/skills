# aws-rightsizing 设计文档

判据行为要改时,**先动 `specs/`,再动 `SKILL.md` / `references/core.py`**。
`core.py` 的每次行为变更都应能在某份 spec 里找到对应段落 —— 测试里
`EXPECTED` 基线的「旧值不删 + 写明成因 + 逐条对账」纪律,是这条流程的下游产物。

- `specs/` —— design:问题陈述、裁定、验证方式
- `plans/` —— 由 spec 派生的逐任务实现计划

## 面向客户的说明

| 文件 | 内容 |
|---|---|
| [method-explained.html](./method-explained.html) | **判据说明（客户可读）**:按服务分章讲"降配建议是怎么算出来的" —— EC2 / EBS / RDS / Redis / MSK / EKS 各自的第一判据、需求反推公式、否决项顺序、候选池为空的六种成因、四条汇总口径,含一个页内交互计算器。数字来自一次**脱敏**的真实运行样例（账号与资源名为占位符,指标值与金额为原值）。改判据后必须同步它,三处由 `tests/test_method_explained.py` 钉住(预设表 / 计算器 / 服务章节),散文部分要人工过 |

`SKILL.md` 与 `references/` 是给 agent 看的执行指令;`specs/` 与 `plans/` 是给维护者看的裁定记录;
本节这一份是给**客户**看的 —— 三者内容重叠但读者与写法不同,不要互相复制。

## specs

| 文件 | 内容 |
|---|---|
| [2026-09-03-utilization-based-rightsizing-design.md](./specs/2026-09-03-utilization-based-rightsizing-design.md) | 初版设计:基于资源利用率做机型配置优化的整体方案 |
| [2026-09-04-run2-findings-design.md](./specs/2026-09-04-run2-findings-design.md) | 第二轮真实运行反馈的设计与裁定 |
| [2026-09-09-sampling-guard-and-veto-persistence-design.md](./specs/2026-09-09-sampling-guard-and-veto-persistence-design.md) | 采样守卫从「拒绝线」改「置信度分档线」;三条否决项改判持续态 |
| [2026-09-10-burstable-credit-not-applicable-design.md](./specs/2026-09-10-burstable-credit-not-applicable-design.md) | EC2 突发候选:信用指标在非突发机型上是「不适用」不是「缺失」,fail-closed 让突发路线永久不可达 |
| [2026-09-10-ec2-underprovisioned-verdict-design.md](./specs/2026-09-10-ec2-underprovisioned-verdict-design.md) | EC2 verdict 只有两个出口,把「规格不足」输出成「已合理配置」;规格不足按持续项判,不用峰值项。附「仅子集发布」指标的通则 |
| [2026-09-10-credit-floor-and-veto-applicability-design.md](./specs/2026-09-10-credit-floor-and-veto-applicability-design.md) | `CPUCreditBalance` 在四个服务节声明为 blocker 却无判据消费,被限流的实例因此隐形;`ReplicationLag` 的 fail-open 改按副本存在性分流 |
| [2026-09-11-elasticache-engine-applicability-design.md](./specs/2026-09-11-elasticache-engine-applicability-design.md) | ElastiCache 的两个主判据指标仅 redis/valkey 发布,Memcached 此前得到指向不存在指标的 `metric-missing` 且说明与该引擎相反 |
| [2026-09-11-window-uniformity-design.md](./specs/2026-09-11-window-uniformity-design.md) | 判据假定规格在窗口内不变却一处未校验;用「部分指标短覆盖」这个已有信号标注,只标注不校正 |
| [2026-09-13-managed-target-selection-design.md](./specs/2026-09-13-managed-target-selection-design.md) | 三条托管判据判出「可以降」却不说降到哪;候选池被压成布尔值扔掉。RDS 主判据缺失即整行消失,而 PI 在部分实例类上结构性不支持。附 `max_mem_reduction_ratio` 在 ElastiCache 内存阶梯上不可满足、RDS CPU 峰值项须改判持续态 |

## plans

| 文件 | Goal |
|---|---|
| [2026-09-04-skill-consolidation.md](./plans/2026-09-04-skill-consolidation.md) | 消灭"同一事实多处复述"与"schema 与实现不符":阈值只留一份机器可读真值、CSV 契约与 `core.py` 输出对齐、补 EKS requests |
| [2026-09-04-run2-findings.md](./plans/2026-09-04-run2-findings.md) | 修掉两次真实端到端运行暴露的 5 个判据缺陷、10 个契约缺口、7 个采集配方缺陷、6 项文档卫生问题,使同一机队在任何 agent runtime 下产出可比报告 |
| [2026-09-09-sampling-guard-and-veto-persistence.md](./plans/2026-09-09-sampling-guard-and-veto-persistence.md) | 样本不足时照样出降配建议(降置信度而非拒绝);三条「曾出现过一次」的否决项改判持续状态 |
| [2026-09-10-burstable-credit-not-applicable.md](./plans/2026-09-10-burstable-credit-not-applicable.md) | 让 `evaluate()` 先判信用指标是否适用于当前机型再判是否缺失,恢复非突发机型的突发降配路线;回归 fixture 改用真实输入 |
| [2026-09-10-ec2-underprovisioned-verdict.md](./plans/2026-09-10-ec2-underprovisioned-verdict.md) | 给 `evaluate()` 补第三个 verdict 出口:需求量超当前规格 ⇒ `upsize-candidate`,按持续项判;附「仅子集发布」指标的通则 |
| [2026-09-10-credit-floor-and-veto-applicability.md](./plans/2026-09-10-credit-floor-and-veto-applicability.md) | 消费 `CPUCreditBalance` 下限让被限流的实例可见;`eval_rds` 分支重排;`ReplicationLag` 缺失按副本存在性分流 |
| [2026-09-11-elasticache-engine-applicability.md](./plans/2026-09-11-elasticache-engine-applicability.md) | `eval_elasticache` 先判 `engine` 再判两个 Redis 独有指标;Memcached ⇒ `excluded`,Valkey 留在 Redis 路径 |
| [2026-09-11-window-uniformity.md](./plans/2026-09-11-window-uniformity.md) | `_coverage_note()` 在四个判据的每条出口留注记;`partial_coverage` 为可选字段,既有 fixture 不改 |
| [2026-09-13-managed-target-selection.md](./plans/2026-09-13-managed-target-selection.md) | 托管服务判出「可以降」时给出初选目标机型与月省;RDS 加 CPU 并行第二判据(峰值项改判持续态)、`upsize` 出口、`FreeStorageSpace` 耐久度、`DBLoad` 峰值反转校验 |
| [2026-09-13-managed-target-selection-replay.md](./plans/2026-09-13-managed-target-selection-replay.md) | 上条的真实回放门禁结果:34 项断言逐条对账、三处 spec 初稿算错的数字、回放暴露而单元测试没抓到的两个顺序缺陷 |
| [2026-09-13-managed-target-selection-two-fleet-diff.md](./plans/2026-09-13-managed-target-selection-two-fleet-diff.md) | 两支机队(776 / 322 判据行)新旧产出三方对照:EC2 路径逐字段未动、托管头条从 \$0 到 24-30%、3 处 verdict 变化(净 −2 假阳性 +1 真实欠配)、第二机队抓出的引擎相关文案缺陷与 Aurora 取价碰撞 |
| [2026-09-14-doc-drift-and-test-gate.md](./plans/2026-09-14-doc-drift-and-test-gate.md) | 托管选型上线后的文档扫尾:托管节省的头条口径、托管行 confidence 只有 `low` 或留空、样例结语、被空行切断的易错项表、两份 README;门禁补结构性守卫 —— 缺 `__main__` runner 的文件在 `python3 <file>` 下退出码 0 而执行 0 条断言,手写 runner 清单漏掉新函数同理,实测 58 条断言从未在门禁里跑过;并把公开 repo 的隐私规则变成闸门（扫全 repo 拦账号 ID / 本机路径 / 实例 ID / access key）—— 那条规则此前只有文字,4 个 commit 因此把一个真实账号 ID 写进了 spec/plan/注释/docstring,已重写本地历史清除 |

## 脱敏

这批文档从私有工作区迁入,**当前版本已脱敏,不带原始 git 历史**。

账号 ID 一律 `123456789012`;真实集群/复制组名换成 `msk-<env>-NN` / `redis-<env>-NN`
占位名(条数、环境分布、彼此区分度保留);本机绝对路径改 `~/` 开头。
**指标值、点数、金额、机型是原值** —— 它们是结论的证据。

文中引用的 `~/Downloads/<account>-<region>-<date>/` 复算脚本与原始产出
**不在本仓库**,只存在于私有工作区。产出根 `report_output/` 已在仓库根
`.gitignore` 里 —— 跑 skill 产生的报告含真实账号与资源 ID,不要提交。
