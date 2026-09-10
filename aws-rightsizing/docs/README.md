# aws-rightsizing 设计文档

判据行为要改时,**先动 `specs/`,再动 `SKILL.md` / `references/core.py`**。
`core.py` 的每次行为变更都应能在某份 spec 里找到对应段落 —— 测试里
`EXPECTED` 基线的「旧值不删 + 写明成因 + 逐条对账」纪律,是这条流程的下游产物。

- `specs/` —— design:问题陈述、裁定、验证方式
- `plans/` —— 由 spec 派生的逐任务实现计划

## specs

| 文件 | 内容 |
|---|---|
| [2026-09-03-utilization-based-rightsizing-design.md](./specs/2026-09-03-utilization-based-rightsizing-design.md) | 初版设计:基于资源利用率做机型配置优化的整体方案 |
| [2026-09-04-run2-findings-design.md](./specs/2026-09-04-run2-findings-design.md) | 第二轮真实运行反馈的设计与裁定 |
| [2026-09-09-sampling-guard-and-veto-persistence-design.md](./specs/2026-09-09-sampling-guard-and-veto-persistence-design.md) | 采样守卫从「拒绝线」改「置信度分档线」;三条否决项改判持续态 |

## plans

| 文件 | Goal |
|---|---|
| [2026-09-04-skill-consolidation.md](./plans/2026-09-04-skill-consolidation.md) | 消灭"同一事实多处复述"与"schema 与实现不符":阈值只留一份机器可读真值、CSV 契约与 `core.py` 输出对齐、补 EKS requests |
| [2026-09-04-run2-findings.md](./plans/2026-09-04-run2-findings.md) | 修掉两次真实端到端运行暴露的 5 个判据缺陷、10 个契约缺口、7 个采集配方缺陷、6 项文档卫生问题,使同一机队在任何 agent runtime 下产出可比报告 |
| [2026-09-09-sampling-guard-and-veto-persistence.md](./plans/2026-09-09-sampling-guard-and-veto-persistence.md) | 样本不足时照样出降配建议(降置信度而非拒绝);三条「曾出现过一次」的否决项改判持续状态 |

## 脱敏

这批文档从私有工作区迁入,**当前版本已脱敏,不带原始 git 历史**。

账号 ID 一律 `123456789012`;真实集群/复制组名换成 `msk-<env>-NN` / `redis-<env>-NN`
占位名(条数、环境分布、彼此区分度保留);本机绝对路径改 `~/` 开头。
**指标值、点数、金额、机型是原值** —— 它们是结论的证据。

文中引用的 `~/Downloads/<account>-<region>-<date>/` 复算脚本与原始产出
**不在本仓库**,只存在于私有工作区。产出根 `report_output/` 已在仓库根
`.gitignore` 里 —— 跑 skill 产生的报告含真实账号与资源 ID,不要提交。
