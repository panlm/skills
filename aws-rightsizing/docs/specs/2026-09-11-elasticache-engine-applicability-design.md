# ElastiCache 判据必须先分引擎：Memcached 不发布 Redis 的两个主判据指标

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`。**指标名、机型、条数是原值。**

**日期**：2026-09-11
**状态**：待 review
**触发**：`2026-09-10-burstable-credit-not-applicable-design.md` 的后续项 C，
也是「仅子集发布的指标先判适用性」通则的第三个已知成员。
**这是三轮排期的第三轮**（第一轮 EC2 规格不足出口、第二轮信用余额下限，均已合并）。

## 问题陈述

### P1：`eval_elasticache` 的输入里没有 `engine`，两个主判据指标却是 Redis 独有

`references/core.py` 的 `eval_elasticache()` 消费的输入字段是
`cheaper_candidate_exists` / `db_mem_used_pct_max` / `engine_cpu_p95` /
`evictions_p95` / `evictions_sum` / `has_replica` / `mem_gib` /
`repl_lag_max` / `repl_lag_p95` / `reserved_memory_pct` / `rid` / `type` / `vcpu`
—— **没有 `engine`**。

而两个**主判据**指标都只有 Redis / Valkey 发布：

| 指标 | 发布方 | `core.py` 的处理 |
|---|---|---|
| `EngineCPUUtilization` | Redis / Valkey（单线程引擎特有） | 缺失 ⇒ `metric-missing`，**fail-closed** |
| `DatabaseMemoryUsagePercentage` | 同上（`maxmemory` 的百分比） | 同上 |

**Memcached 是多线程的，两个指标都不发布。** 喂一个 Memcached 集群进去 ⇒
永久 `metric-missing`，而给出的说明是：

> `EngineCPUUtilization` 缺失。注意不可用 `CPUUtilization` 替代——
> Redis 单线程，整机 CPU 含后台线程，会系统性误判

**这句话对 Memcached 是错的**：Memcached 多线程，`CPUUtilization` 恰恰**是**它的
正确 CPU 指标。所以报告不仅给不出结论，还会指导客户去补一个不可能存在的指标，
并附带一条与该引擎相反的技术断言。这与上一轮修掉的
`CPUSurplusCreditsCharged` 是同一类缺陷 —— 把「不适用」当「缺失」。

### P2：这一轮是**潜在**缺陷，没有实测危害

两支验证机队的 ElastiCache 节点**全部是 redis**（分别 64/64 与 42/42），
所以该路径一次都没被触发过。`SKILL.md` 的验证状态表也早已写明
「**未实测**：Memcached、Valkey、Serverless、非集群模式」。

**但代码里没有任何东西排除 Memcached。** 现状是「碰巧没遇到」，
不是「已经挡住」。客户下一个账号里出现一个 Memcached 集群，报告就会输出
上面那段错误指引。

### P3：Valkey 与 Memcached 必须分开处理，不能一起排除

`Valkey` 是 Redis 协议兼容的单线程引擎，**`EngineCPUUtilization` 与
`DatabaseMemoryUsagePercentage` 都发布**。所以它的**指标侧**与 Redis 同构，
现有判据对它成立。

`SKILL.md` 把 Valkey 列进「未实测」，指的是**取价侧**的问题
（RERUN-NOTES 记录过 Valkey 与 Redis 共用逐字相同的 `usagetype`，
`unique_by` 会取到 Valkey 价、对 Redis 集群低估 20%）—— 那是采集侧的取价键问题，
已由 `(instanceType, operation)` 复合键解决，与本轮的指标适用性无关。

**把 Valkey 一起排除会白丢一整个引擎的降配路径**，方向与上一轮修的缺陷相同。

## 预期收益（不粉饰）

| 变化 | 实测条数 | 说明 |
|---|---:|---|
| Memcached 集群 ⇒ `excluded` 且说明正确 | **0** | 两支机队全 redis，本轮零行为变化 |
| `engine` 缺失 ⇒ `metric-missing` | **0** | 同上（补齐字段后所有行都有 engine） |

**不粉饰的部分：**

- **本轮在现有数据上一行都不变**，`route1` / `route2` / 桶 B / 采集侧四条口径与
  分母逐值不变。价值全在「下一个账号里出现 Memcached 时不输出错误指引」。
- **不为 Memcached 新增判据。** 它的 CPU 用 `CPUUtilization`、内存用
  `BytesUsedForCache` 对上限，都**未实测**。发明一套未验证的判据比排除它更糟 ——
  `SKILL.md` 的既有纪律是「新增指标前必须实测确认刻度与维度集」。
  排除是诚实的当前边界，不是偷懒。
- **`excluded` 不丢成本。** 托管行的 `cur_cost_mo` 由采集侧填、`core.py` 的托管
  判据从不设它（与 `db.serverless` 的 `excluded` 早退同一先例），所以该服务
  不会从分母消失。这一点必须验证，它是记录过的坑。

## 设计

### C1：新增输入字段 `engine`，在两个主判据之前分流

| 字段 | 必填 | 取值 | 缺失后果 |
|---|---|---|---|
| `engine` | ElastiCache 必填 | `raw/inventory/elasticache.json` 每个节点的 `engine` 字段原值（小写，实测 `"redis"`）。同一复制组内取任一节点即可 —— 引擎是复制组级属性 | `metric-missing`（无法判定两个主判据是否适用，不得假定 Redis） |

分流规则：

```
engine in {redis, valkey}  ⇒ 现有判据不变
engine == memcached        ⇒ excluded（本版本不评估：两个主判据指标该引擎不发布）
engine 缺失                 ⇒ metric-missing（fail-closed）
其他取值                    ⇒ excluded（未知引擎，同样不评估，理由写明取值）
```

### C2：分流点放在哪

放在 `evictions` 与 `repl_lag` 两条**否决项之后**、`cheaper_candidate_exists`
短路**之前**。三条依据：

- **`Evictions` 对 Memcached 同样发布**（两个引擎都有淘汰），所以那条否决项
  对它有效，不该被引擎分流跳过 —— 「这个缓存正在淘汰键」是有效阻断，
  与能不能降配无关。
- `ReplicationLag` 已由 `has_replica` 分流，Memcached 无副本概念 ⇒
  `has_replica=false` ⇒ 放行，不冲突。
- 放在 `cheaper_candidate_exists` **之前**：`excluded` 是「本版本不评估」的
  结论，比「没有更便宜候选」更靠前 —— 后者暗示评估过了。

### C3：`excluded` 的说明必须写明「不评估」而不是「缺指标」

现行 Memcached 会拿到「`EngineCPUUtilization` 缺失，注意不可用 `CPUUtilization`
替代」。新文案要说清三件事：该引擎结构性不发布这两个指标、本版本不为它发明判据、
以及**它的正确指标是什么**（供人工评估用），但明确标注那是未实测的方向。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | C1/C2/C3 的引擎分流 |
| `references/cli-recipes.md` | `engine` 的输入契约行 + 取值来源 |
| `references/metrics-catalog.md` | ElastiCache 一节的 `EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage` 两行标注「仅 Redis/Valkey 发布」 |
| `SKILL.md` | ElastiCache 一节补引擎分流；「仅子集发布」通则清单里这两项由「尚未分流」改为「已分流」 |
| `references/sample-solve.md` | ElastiCache 样例输入补 `engine`（该 fixture 被测试解析） |
| `tests/test_managed_dispatch.py` | 既有 elasticache fixture 补 `engine="redis"`；新增一条分流测试 |
| `tests/test_csv_contract.py`、`tests/test_fail_closed_contracts.py` | 同样补 fixture |
| `docs/README.md` | specs / plans 索引 |

### 测试影响

**回归 fixture 不受影响** —— `regression-fleet.json` 只有 EC2 资源，无 ElastiCache 行。

既有 elasticache fixture 一律补 `engine="redis"`，**等价于改动前的行为**，
逐条保住原测试意图。新分流由新测试用 `memcached` / 缺失 / 未知取值覆盖。

新测试必须带反向半：`redis` 与 `valkey` 都要断言**照常**走到降配路径
（否则分不清「分流生效」与「整个函数短路了」）。

## 验证方式

1. 9 个测试文件全绿；`test_regression_fleet.py` 锚定值逐值不变。
2. 新测试五态：`redis` / `valkey` 照常、`memcached` ⇒ `excluded`、
   `engine` 缺失 ⇒ `metric-missing`、未知取值 ⇒ `excluded`。
3. **`excluded` 行不丢成本**：断言 `eval_elasticache` 的 Memcached 早退**不设**
   `cur_cost_mo`（该字段由采集侧填），与 `db.serverless` 的行为一致 ——
   若判据自己塞了一个值或清空了它，整个服务会从分母消失。
4. 真实回放：两支机队全 redis ⇒ 13 组与 11 组的 verdict **逐行不变**，
   四条口径与分母逐值不变。
5. `SKILL.md` 三条自检 `CLEAN`。

## 明确不做

- **不为 Memcached 新增判据**（理由见「预期收益」）。
- **不排除 Valkey**（理由见 P3）。
- **不改 `Evictions` 与 `ReplicationLag` 的处理**（它们对 Memcached 同样适用 /
  已由 `has_replica` 分流）。
- **不动 ElastiCache Serverless** —— `describe-cache-clusters` 不返回它，
  这条输入路径上不会出现。
- **不重跑已交付的两份报告**（沿用既有决定）。

## 后续

- **第四轮（F）：窗口内规格变更 / 覆盖度盲区。** 整套判据假定资源规格在窗口内
  不变，无一处校验；检测信号是「某指标的 `n` 明显低于同资源其他指标的 `n`」。
  实测两支机队命中 2 台 RDS（信用序列 178/720 而核心指标 720/720），
  两台目前都被 `FreeableMemory` 独立否决，所以尚未产出错误建议。
- 本轮之后，「仅子集发布」通则的五个已知成员全部完成适用性分流。
  下次新增指标时按那张清单比对。
