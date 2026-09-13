# 托管服务初选目标：两支机队的新旧产出对比

对两份归档交付（tar.gz）重放并逐行对比。两支机队都在 `ap-east-1`、
同一采集窗口（30 个完整业务本地日 / 720 小时点）。

| | 机队 A | 机队 B |
|---|---|---|
| 判据行总数 | 776 | 322 |
| RDS | 15（含 1 台 PostgreSQL、2 台 Multi-AZ、2 台 burstable、1 台 PI 未开） | 12（全 MySQL，1 台 Multi-AZ） |
| ElastiCache | 13 组 / 64 节点 | 11 组 / 42 节点 |
| MSK | 6 集群 | 8 集群 |
| 托管按需月额 | $11,398.38 | $8,772.33 |
| 全量共同分母 | $39,423.29 | $21,758.56 |

## 归因纪律：三方对照，不是两方

归档产出来自 commit `d9aef59`，而**该 commit 不在本仓库历史里**
（脱敏迁入时不带原始 git 历史）。所以「归档 vs 现在」里混着中间若干 commit
的效果，不能整段记在本轮账上。对比因此做三方：

```
归档 core-out   ← commit d9aef59，不可复现代码
main            ← 本轮之前的 HEAD，同一份适配输入
本分支          ← 同一份适配输入
```

**只有 main → 本分支 之差属于本轮。** 归档 → main 之差属于
`2026-09-10` / `2026-09-11` 那四个 commit（burstable 信用适用性、信用地板、
EC2 欠配 verdict、窗口覆盖注记）。

## EC2 路径：main 与本分支逐字段完全一致

| 机队 | profile | 比对行数 | 结果 |
|---|---|---:|---|
| A | aggressive / conservative | 29 / 29 | 全部一致 |
| B | aggressive / conservative | 4 / 4 | 全部一致 |

归档的 EC2 `core-in` 原样分别喂两个版本，输出字典逐字段相等。
这在真实数据上证明「本轮不碰 EC2 路径」。

（归档 → main 的 EC2 侧**有**漂移：机队 A 路线二 $2,620.40 → $3,001.02，
机队 B $87.30 → $114.17，29 / 4 行逐字段不同。那是上述四个 commit 的效果。）

## 托管侧：main 全部 $0，本分支给出金额

`main` 在两支机队、两个 profile、四个组合下 **route1 与 route2 全部为 $0** ——
这不是巧合，是「判据不选目标 ⇒ 两列恒空 ⇒ 求和为 0」的必然结果。

| 机队 / profile | 托管 route1 | 托管 route2 | 占托管月额 |
|---|---:|---:|---:|
| A / aggressive | $659.34 | $3,374.21 | 29.6% |
| A / conservative | $659.34 | $2,855.18 | 25.0% |
| B / aggressive | $261.34 | $2,111.16 | 24.1% |
| B / conservative | $261.34 | $2,033.78 | 23.2% |

## 头条口径的变化

路线二 = `main` 的 EC2 部分 + 本分支的托管部分：

| 机队 / profile | 归档头条 | 新头条 | 倍数 |
|---|---:|---:|---:|
| A / aggressive | $2,620.40（6.65%） | $6,375.23（16.17%） | 2.4x |
| A / conservative | $2,071.87（5.26%） | $5,253.67（13.33%） | 2.5x |
| B / aggressive | $87.30（0.40%） | $2,225.33（10.23%） | **25.5x** |
| B / conservative | $27.88（0.13%） | $2,089.99（9.60%） | **75.0x** |

机队 B 的倍数极大是因为它的 EC2 侧几乎没有可降的（$87.30 / 0.40%），
而托管层占了它按需月额的 40%（$8,772 / $21,759）。
**旧报告在这支机队上等于什么都没说** —— 头条 0.40%，而 24% 的托管节省
因为「判据不选目标」而结构性不进头条。旧报告里那句
「托管服务候选未自选目标，因此不进入四条头条节省」逐字描述了这个后果。

## verdict 变化：只有三行，方向都对

跨两支机队、两个 profile，`main → 本分支` 的 verdict 变化共 3 处：

**① 一台 `db.m6g.xlarge` 从「已合理配置」变 `upsize-candidate`**（机队 B，两个 profile）

| 判据 | 数值 | main | 本分支 |
|---|---|---|---|
| DBLoad p95 | 2.328 vs `0.5 × 4 vCPU` = 2.0 | 已合理配置（差 0.328 跨阈值） | — |
| CPU 持续 p95 | **69.64%** ⇒ 按目标 60/40% 反推需 5 / 7 vCPU，现有 4 | 判据不看 | `upsize-candidate` |

**② 两组 Redis 从 `downsize-candidate` 变「已合理配置」**
（机队 A conservative 一组、机队 B aggressive 一组）

两组的 main 输出都带着 `_FIT_UNVERIFIED`：
「更便宜候选是否装得下当前需求未经校验……」。本分支做了校验，结论是
「更便宜的候选都装不下当前需求（最接近的是 `cache.t4g.small`）」。

**这两行是被删掉的假阳性，不是丢失的收益。** 它们在旧报告里是
「downsize-candidate，实际可省 $0」—— 正是 `core.py` 注释里记的那个实测形态
（一个 `cache.t4g.medium` 复制组 `cheaper_candidate_exists=true`，
但内存已用到 maxmemory 的 59.24%，同架构下更便宜的两个候选都装不下）。

净效果：**−2 条假阳性降配建议，+1 条真实欠配发现。**

## 新判据在两支机队的命中

| 判据 | A/ag | A/co | B/ag | B/co |
|---|---:|---:|---:|---:|
| 候选池为空：跨架构成因 | 3 | 3 | 2 | 2 |
| 候选池为空：价目地板成因 | 6 | 6 | 10 | 10 |
| 候选池为空：内存装不下 | 0 | 1 | 1 | 0 |
| PI 不支持实例类被排除 | 1 | 1 | 0 | 0 |
| `FreeStorageSpace` 触 0 / 耐久度 | 0 | 0 | 1 | 1 |
| `DBLoad` 峰值反转 | 3 | 3 | 4 | 4 |
| 目标落在阶梯最底档 | 7 | 6 | 3 | 3 |

七条判据每一条都在真实数据上命中过，没有一条是空转的。

## 机队 A 独有的三个形态（机队 B 没有，因此第一轮没验到）

1. **PostgreSQL**（1 台 `db.m6g.xlarge`）。选出 `db.m6g.large`（route1，
   省 $176.66）与 `db.t4g.large`（route2，省 $191.99）。
   按引擎取价的复合键 `(databaseEngine, deploymentOption)` 因此得到验证。
2. **`db.t4g.small` 且 PI 未开**。该实例类**结构性不支持** PI，所以
   `DBLoad` 永远不会有。本分支给出的说明是「该实例类结构性不支持
   Performance Insights……换用支持 PI 的实例类才能拿到第一判据」，
   而不是笼统的「db.load.avg 缺失」。
   该行最终仍是 `metric-missing`，但原因换成了 `CPUCreditBalance` 缺失 ——
   两个独立缺口，各自说清。
3. **`cache.m7g.large`**（另一个 Graviton 族）。选出 `cache.m6g.large`
   作 route1 目标（省 $26.72），证明同架构筛选不是只认 `m6g`/`t4g`。

## 本轮由第二支机队抓出的缺陷

**内存反推的 blocker 文案假定了 MySQL。** 那台 PostgreSQL 被告知去下调
`innodb_buffer_pool_size`，而 InnoDB 是 MySQL 专有。RDS 行不带 `engine` 字段，
故改为引擎中立并同时列出 MySQL 的 `innodb_buffer_pool_size` 与 PostgreSQL 的
`shared_buffers`。已加回归测试 `test_memory_derivation_blocker_is_engine_neutral`。

**Aurora 取价碰撞。** 重建候选池时碰撞守卫报错：
`('Aurora PostgreSQL', 'Single-AZ') db.r6g.xlarge: 0.896 vs 0.689` ——
同一 `(instanceType, engine, deploymentOption)` 上有 `InstanceUsage` 与
`InstanceUsageIOOptimized` 两档。`usagetype` 必须进筛选，且区域前缀后紧邻：
Single-AZ 用 `-InstanceUsage:`、Multi-AZ 用 `-Multi-AZUsage:`（2 倍单价）。
`cli-recipes.md` §7.4 的表已写明这条。

## 归档 → main 的既有漂移（不属本轮，但值得知道）

机队 A 的一台 `db.t4g.medium` 从 `downsize-candidate` 变 `metric-missing`，
原因是 `CPUCreditBalance 缺失，无法排除信用已耗尽` —— 来自 `2026-09-10` 的
信用地板 commit。含义是：**旧交付对一台无法排除信用耗尽的 burstable 实例
给出了降配建议**。归档的采集侧没有 `credit_balance_min` / `credit_balance_max`
字段，重采才能解除。

## 未做

**没有重新渲染完整的 markdown 报告。** 报告的组装（约 40 个分节，含 EBS /
EKS / VPC / 快照 / ELB）是 agent 驱动步骤而非 `core.py` 的输出；本轮的差异
全部落在托管三节与第 1 节头条，其余分节的输入未变。
要出完整报告需按 `report-template.md` 重跑组装步骤。

复算脚本 `compare-20260913/compare_old_new.py` 在私有工作区，**不在本仓库**。
