# 消费 `CPUCreditBalance` 下限 + 两条 ElastiCache 否决项的适用性

> **本文已脱敏。** 账号 ID 一律写作 `123456789012`；EC2 实例 ID 换成 `i-B01`…`i-B04`，
> RDS 实例换成 `mysql-<env>-NN`、Redis 复制组换成 `redis-<env>-NN` 占位名
> （**台数、机型、彼此的区分度都保留**）。**指标值、点数、金额、机型全是原值** ——
> 它们是结论的证据。占位名不对应任何真实资源。

**日期**：2026-09-10
**状态**：待 review
**触发**：`2026-09-10-burstable-credit-not-applicable-design.md` 留下的后续项。
**这是三轮排期里的第二轮**（第一轮 = EC2 规格不足出口，已合并；第三轮 = ElastiCache
分不出 Redis 与 Memcached）。排查本轮时又发现第四类缺陷，见「后续」的 F。

## 问题陈述

### P1：`CPUCreditBalance` 在四个服务节被声明为 blocker，`core.py` 一处都没消费

`references/metrics-catalog.md` 里四处都把它写成判据：

| 节 | 用途列现写 |
|---|---|
| EC2 | `blocker / floor（是否触底）` |
| RDS | `blocker（db.t* 是否触底）` |
| ElastiCache | `blocker（cache.t* 是否触底）` |
| MSK | `blocker（broker 为 T 机型时出现）` |

同文件的 stat 扫描表还给它打了 ✅「下限型判据要 Minimum」。而 `core.py` 消费的
信用字段**只有 `surplus_credits`**（枚举过全部 `res.get(...)` 键，无一处读余额）。

这是一条**假承诺**：同一份文件在别处诚实标注了「无判据消费」
（`CPUCreditUsage` / `CPUSurplusCreditBalance` / EBS 的 `*Ops`），
唯独 `CPUCreditBalance` 的四行声称有消费者。

数据是采了的（实测 EC2 侧 32 行、RDS 侧 32 行 `CPUCreditBalance`），
只是从没组装进 solver 字段。

### P2：现行否决项漏掉了「被限流」这一整类，而它方向危险

`CPUSurplusCreditsCharged > 0` 是个**窄**信号，只在两个条件同时成立时为真：
实例处于 unlimited 模式，**且**透支的信用超期未偿还。两种常见情形它都看不见：

- **standard 模式**：余额触底只会被**限流到基线**，不产生 surplus 计费。
- **unlimited 模式但 24 小时内偿还**：透支过但未被计费。

两种情形下实例都已经把持续需求跑到超出基线，而**限流会把 `CPUUtilization` 压住**
—— 于是持续负载看起来极低，solver 看到的是一台安静的机器。

实测（账号 `123456789012` / `ap-east-1`）：

| 资源 | 机型 | `CPUCreditBalance`/`Minimum` 的最小值 | 上限 | 占上限 | `CPUSurplusCreditsCharged` | 现判定 |
|---|---|---:|---:|---:|---:|---|
| `i-B01` | t3.xlarge | **0.00** | 2304 | **0.00%** | 0.00（四档全 0） | 已合理配置 |
| `i-B02` | t3.medium | 490.00 | 576 | 85.07% | 0.00 | 已合理配置 |
| `i-B03` | t3.medium | 572.39 | 576 | 99.37% | 0.00 | downsize |
| `i-B04` | t3.medium | 575.50 | 576 | 99.91% | 0.00 | downsize |
| `mysql-stg-01` | db.t4g.medium | 575.34 | 576 | 99.89% | 0.00 | downsize-candidate |
| `mysql-stg-02` | db.t4g.small | 572.32 | 576 | 99.36% | 0.00 | metric-missing |

`i-B01` 的信用**跑到了零**，而它的 `CPUUtilization` p95 只有 **1.62%**
（`max` 99.46%）—— 正是被限流的形态。它同时是第一轮 P4 登记的那台：
`required_vcpu` 7 > 现有 4，但持续项规则抓不到它，因为持续值被限流压住了。
**本轮就是为了让它被看见。**

`i-B01` 的上限 2304 = 4 vCPU × 0.40 × 1440，与 `baseline-pct.json` 的
`t3.xlarge = 0.4` 吻合，可作为该静态表未过期的交叉验证。

**观测到的分离度极大**：触底的两位数是 **0.00%–0.14%**，健康的是
**85.07%–99.91%**，中间没有任何观测点。所以门限取值不敏感。

### P3：判据不能只按「当前机型是否 burstable」一刀切

实测两台**当前机型为 `db.m6g.xlarge`（非突发）**的 RDS 却有信用序列：

| 资源 | 当前机型 | `CPUUtilization` / `DBLoad` / `FreeableMemory` 覆盖 | `CPUCreditBalance` 覆盖 | 余额最小值 | 上限 |
|---|---|---:|---:|---:|---:|
| `mysql-pt-01` | db.m6g.xlarge (4 vCPU) | **720 / 720** | **178 / 720** | **0.79** | 576 |
| `mysql-pt-02` | db.m6g.xlarge (4 vCPU) | **720 / 720** | **178 / 720** | **0.70** | 576 |

对照全窗口都是突发机型的 `mysql-stg-01`（db.t4g.medium）：四项**全部 720/720**。

三条证据指向同一个解释：**这两台在窗口内改过规格。**
① 核心指标满覆盖 ⇒ 实例整窗口存在；② 信用序列只覆盖 178/720（24.7%）
⇒ 只有那段时间它有信用；③ 上限 576 对应**2 vCPU × 20% 基线**的机型，
而当前是 4 vCPU —— 上限与当前规格不匹配。余额在那段时间跑到 0.7，
很可能正是扩容的原因。

所以 `_rds_is_burstable(当前机型)` 作为**双向**判别式是不安全的：
「当前非突发 ⇒ 序列缺失属不适用」成立，但**「当前非突发 ⇒ 不可能有序列」不成立**。

**本轮对这种形态不产出否决项**，只产出一条说明：那份余额测自**另一个规格**，
拿它否决当前规格没有依据；而「窗口内混合了两个规格的采样」是一个更大的问题，
属第四轮（见「后续」的 F）。

### P4：`Evictions` 与 `ReplicationLag` 的缺失处理不对称，两者都没判适用性

`references/core.py` 的 `eval_elasticache()`：

```python
ev_persist, ev_max = _persistent(res, "evictions_p95", "evictions_sum")
if ev_persist is None:
    _verdict(out, "metric-missing", "Evictions 缺失")     # fail-closed
    return out
...
lag_persist, lag_max = _persistent(res, "repl_lag_p95", "repl_lag_max")
if lag_persist is not None and lag_persist >= t["redis_repl_lag_max_s"]:   # fail-open
```

- `Evictions` 每个节点都发布 ⇒ fail-closed **正确**。
- `ReplicationLag` **只在存在副本时才有意义** ⇒ 缺失时放行有道理。

但放行是**无条件**的：`core.py` 没有任何依据区分「单节点，不适用」与
「复制组，采集失败」。后者一旦发生，这条否决项**静默消失**，而该 skill 已记录
「维度名写错时 `list-metrics` 与 `get-metric-data` 都只返回空、不报错」。

**本账号数据上未成灾**：13 个复制组的 `repl_lag_p95` 全部有值（连唯一的单节点组
`redis-stg-01` 也报 0.0）。属**潜在**缺口 —— 但补门槛的代价接近零，见 C4。

### P5：`count` 不足以判定有无副本

`eval_elasticache` 的输入有 `count`（节点数），拿它当「有无副本」的代理在本账号
数据上恰好成立（唯一的无副本组也正好是单节点），但**规则上不成立**：
`3 分片 × 1 节点`（`count=3`、无副本）是合法的 cluster-mode 配置，
按 `count > 1` 会把它误判成「该有副本却缺指标」⇒ 假的 `metric-missing`。

实测 13 个复制组的分片×成员形态：

| 形态 | 组数 | 有副本 |
|---|---:|---|
| 3 分片 × 2 成员 | 5 | 是 |
| 3 分片 × 3 成员 | 2 | 是 |
| 1 分片 × 3 成员 | 5 | 是 |
| 1 分片 × 1 成员 | 1 | **否** |

**副本存在性可从现有 inventory 零成本推出**：节点 id 编了分片与成员号
（`<rg>-<NNNN>-<MMM>`），按 `(rg, NNNN)` 分组后**任一分片的成员数 > 1 即有副本**。
不需要新增 API 调用（`describe-replication-groups` 不必引入）。

## 预期收益（不粉饰）

| 变化 | 实测条数 | 方向 |
|---|---:|---|
| EC2 信用触底 ⇒ `upsize-candidate`（原「已合理配置」） | **1**（`i-B01`，$170.53/mo） | 纠正错误的肯定断言 |
| RDS 信用触底 ⇒ `upsize-candidate` | 0（本账号无当前突发机型触底者） | —— |
| 当前非突发却有信用序列 ⇒ 加一条说明 blocker | **2**（`mysql-pt-01/02`） | 让规格变更可见 |
| `ReplicationLag` 缺失且有副本 ⇒ `metric-missing` | 0（本账号 13 组全有值） | 关上潜在缺口 |
| 四个服务节的 `metrics-catalog` 用途列订正 | 4 行 | 消除假承诺 |

**不粉饰的部分：**

- **本轮不产生任何节省额**，`route1` / `route2` / 桶 B / 采集侧四条口径与分母
  **逐值不变**。`upsize-candidate` 落 `excluded` 且不带节省额（第一轮已确立）。
- **唯一的行为改变只有 1 行**（`i-B01`）。收益不在数量，在于它是**方向危险**的
  那一类：被限流的机器看起来最闲，最容易被推荐再降一档。
- **ElastiCache 与 MSK 侧不新增信用判据。** 两者的输入里没有 burstable 形态字段，
  为未实测的引擎/机型发明判据不划算。本轮把这两节的用途列改成诚实的
  「无判据消费」，而不是伪造一个消费者。
- **`ReplicationLag` 那道门本账号上一条都不会触发。** 它的价值是关上一个
  「一旦发生就无声」的缺口，不是当下的产出。
- **不解决「窗口内混合两个规格的采样」**（F，第四轮）。本轮只让它可见。

## 设计

### C1：新增两个输入字段与一个阈值键

| 字段 | 必填 | 取值 | 缺失后果 |
|---|---|---|---|
| `credit_balance_min` | T 机型必填 | agg 的 `CPUCreditBalance` / `Minimum` / **`full-window`** 档的 `min` | 当前机型为 T 系列时 fail-closed（同 `surplus_credits`）；非突发机型留空即正确 |
| `credit_balance_max` | 同上 | 同一行的 `max` | 同上 |

**必须取 `full-window` 档**：这是**下限型**指标，`biz-hours` 会漏掉夜间批处理
把信用耗尽的低点 —— 该 skill 的易错项表已为 `freeable_mem_min_gib` 记过同一个坑。

阈值键 `credit_balance_floor_pct` 进 `references/thresholds.json` 两个 profile。
形状与既有的 `rds_freeable_mem_floor_pct` 同构（都是「下限占某个基数的百分比」）。
**具体取值只写在 JSON 里，本文不复述**（`tests/test_no_duplicated_constants.py`
的约束）；选值依据是 P2 那张表的分离度：触底 0.00%–0.14%，健康 85.07%–99.91%。

**判据用「占窗口内观测到的最大余额的百分比」，不用「占信用上限」**：
上限 = `vcpu × baseline_pct × 1440`，其中 RDS 的 baseline 百分比**不在本 skill 的
静态资产里**（`baseline-pct.json` 只覆盖 EC2 机型）。用观测最大值自归一化，
两个服务共用一套算法，且不引入第二张静态表。

`credit_balance_max == 0` 需单独兜住（整窗口余额恒为 0 ⇒ 彻底耗尽 ⇒ 触底成立），
否则会除零。

**被否决的更简方案：判 `credit_balance_min == 0`。** 它能抓住 `i-B01`（恰为 0.00），
不需要新阈值键。不采用的理由：`Minimum` 是逐小时最小值，真实耗尽时它**通常**
落到 0 但不保证 —— 实测 `mysql-pt-01/02` 的最小值是 0.79 / 0.70 而非 0。
把判据建在「恰好等于 0」上，会让一台余额在 0.3 附近徘徊的饿死实例逃掉，
而这正是本轮要抓的那类。

### C2：EC2 侧消费余额下限，产出 `upsize-candidate`

在 `evaluate()` 里，与既有的 `surplus_credits` 分支并列，且**同样先判适用性**：

```
当前机型为 T 系列（cs["burst"]）：
    credit_balance_min 缺失            ⇒ 抑制突发候选（同 surplus_credits 的既有行为）
    余额触底                            ⇒ verdict = upsize-candidate（当前规格已不足）
当前机型非突发：
    credit_balance_min 存在            ⇒ 加一条「窗口内规格变更过」blocker，不否决
    缺失                                ⇒ 不适用，什么都不做
```

**优先级**：信用触底与第一轮的「持续项超」是**同一个结论**（当前规格已不足）的
两条独立证据，都产出 `upsize-candidate`。两者同时成立时 blocker 两条都写 ——
它们解释的是不同的事实，不可互相替代。信用触底须排在**持续项之前**判定：
被限流的实例持续值必然偏低，先判持续项会让它落进「已合理配置」。

### C3：RDS 侧同构

`eval_rds()` 里 `surplus_credits` 那两个分支之后，加余额触底判定，
适用性同样由 `_rds_is_burstable(res["type"])` 决定，产出 `upsize-candidate`
（与既有的 surplus 超额出口一致）。非突发却有序列时加同一条说明 blocker。

### C4：`ReplicationLag` 的缺失改为按副本存在性分流

新增输入字段：

| 字段 | 必填 | 取值 | 缺失后果 |
|---|---|---|---|
| `has_replica` | ElastiCache 必填 | 由 inventory 的节点 id `<rg>-<NNNN>-<MMM>` 按 `(rg, NNNN)` 分组，**任一分片成员数 > 1** 即 `true` | fail-closed：无法判定副本形态 ⇒ `metric-missing`（不得假定无副本，那会让否决项静默消失） |

```
has_replica 为 true 且 repl_lag 持续值缺失  ⇒ metric-missing（该发布却没有 ⇒ 采集缺口）
has_replica 为 false                        ⇒ 不适用，放行（现行行为）
has_replica 缺失                            ⇒ metric-missing（fail-closed）
```

`Evictions` 的 fail-closed **不动** —— 它每个节点都发布，缺失是真缺失。
本轮在该分支加一句注释写明这个不对称是**有依据的**，不是漏改。

**不用 `count` 做代理**（理由见 P5）。`count` 保持原用途（乘 `cur_cost_mo`
与两个 `*_save_mo`）不变。

### C5：`metrics-catalog.md` 四行用途列订正

- EC2 / RDS：改成实际判据（余额触底 ⇒ `upsize-candidate`，取 `full-window` 的
  `Minimum`，且**仅 `t*` / `db.t*` 适用**）。
- ElastiCache / MSK：改成诚实的**「无判据消费」**，与该文件已有的
  `CPUCreditUsage` / `CPUSurplusCreditBalance` 写法一致。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | C2 EC2 余额判据；C3 RDS 余额判据；C4 `has_replica` 分流 + `Evictions` 不对称的注释 |
| `references/thresholds.json` | C1 新增 `credit_balance_floor_pct`（两个 profile） |
| `references/cli-recipes.md` | C1 两个信用字段 + C4 `has_replica` 的输入契约行（含「非突发机型留空即正确、不要补 0」，沿用上一轮的措辞） |
| `references/metrics-catalog.md` | C5 四行 |
| `references/thresholds.md` | 新阈值键的语义与选值依据（**不复述数值**） |
| `SKILL.md` | EC2 / RDS 两节补余额触底出口；「仅子集发布」通则的成员清单标注 `CPUCreditBalance` 已消费 |
| `references/report-template.md` | `upsize-candidate` 的 EC2 侧依据补「或信用余额触底」 |
| `tests/test_thresholds.py` | 新键的双向覆盖由既有断言自动纳入（core.py 读了、JSON 里有） |
| `tests/test_fail_closed_contracts.py` | 新增 EC2 侧四条（触底 / 健康 / 非突发有序列 / T 系列缺失） |
| `tests/test_managed_dispatch.py` | 新增 RDS 侧三条 + ElastiCache `has_replica` 三条 |
| `tests/fixtures/regression-fleet.json` | 见下 |

### 测试影响

**回归 fixture 需要加两个字段，且锚定值必须不变。** 该 fixture 的 13 台里
1 台是 `t3.medium`（burstable），12 台非突发。按 C1 的契约：
突发那台填真实的 `credit_balance_min` / `credit_balance_max`（健康值，
不得触底 —— 否则会改变它的 verdict 与锚定总额），12 台非突发**留空**。

**处置纪律**：`route1_nb` / `route2_max` / `MEM_FLOOR_OFF_ROUTE2` /
`WITHDRAWN_ROUTE2_20260904` / `verdicts` / `buckets` **任一变化都视为实现错误**。
本轮的意图是新增一条判据，不是改动既有 13 台的结论。

`test_no_duplicated_constants.py` 的**双向**键覆盖会自动把
`credit_balance_floor_pct` 纳入门禁：core.py 读了它、JSON 里有它，两边缺一即红。

新增的每条测试都要有「反向半」：触底那条要证明同一台机器给健康余额时
**不**判 `upsize-candidate`；`has_replica` 那条要证明 `false` 时放行、`true` 时阻断。

## 验证方式

1. 9 个测试文件全绿；`test_regression_fleet.py` 锚定值逐值不变。
2. 每条新测试的反向半都成立。
3. 真实数据回放（数据在仓库外，不得提交）：
   - `i-B01` 由「已合理配置」变 `upsize-candidate`，blocker 写明余额触底；
   - `mysql-pt-01/02` 多一条「窗口内规格变更过」blocker，**verdict 不变**
     （它们仍被 `FreeableMemory` 否决成 `blocked`）；
   - 其余 T 系列实例（`i-B02`/`i-B03`/`i-B04`/`mysql-stg-01`/`mysql-stg-02`）
     结论**不变**；
   - 13 个 Redis 复制组结论**不变**（全部有 `repl_lag`，`has_replica` 推导
     12 true / 1 false）；
   - `route1` / `route2` / 桶 B / 采集侧四条口径与分母**逐值不变**。
4. `credit_balance_floor_pct` 从 `thresholds.json` 临时改成一个极端值时，
   `i-B01` 的结论必须随之翻转 —— 证明该键是**活的**，不是孤儿键
   （沿用 `MEM_FLOOR_OFF_ROUTE2` 那条测试的手法）。
5. `SKILL.md` 三条自检打印 `CLEAN`。

## 明确不做

- **不为 ElastiCache / MSK 新增信用判据**（理由见「预期收益」）。
- **不引入 `describe-replication-groups`** —— 副本存在性从现有 inventory 推出。
- **不用「占信用上限的百分比」做判据** —— 需要 RDS 的 baseline 静态表，本 skill 没有。
- **不产出升配的目标机型**（沿用第一轮的边界）。
- **不解决窗口内规格变更导致的采样混合**（F，第四轮）；本轮只让它可见。
- **不改 `Evictions` 的 fail-closed。**
- **不重跑已交付的两份报告**（沿用既有决定）。

## 后续

- **第三轮（C）：** `eval_elasticache` 输入里没有 `engine` 字段，
  `EngineCPUUtilization` / `DatabaseMemoryUsagePercentage` 是 Redis/Valkey 独有且
  都 fail-closed ⇒ Memcached 集群永久 `metric-missing`，且给出的说明
  （「Redis 单线程，整机 CPU 含后台线程」）对 Memcached 是错的。
  **好消息：`engine` 已在 inventory 里**（实测每个节点都带 `"engine": "redis"`），
  只是没组装进 solver 输入，所以这一轮很便宜。
- **第四轮（F）：窗口内规格变更 / 覆盖度盲区。** 整套判据假定资源规格在窗口内
  不变，无一处校验。`required_vcpu = ceil(cur_vcpu × sus_cpu% / target)` 拿**当前**
  核数去乘一部分测自**另一个规格**的利用率。实测 `mysql-pt-01/02` 约 25% 的采样
  测在 2 核上、75% 在 4 核上，全部按 4 核处理。方向：先小后大 ⇒ 混合 p95 虚高
  ⇒ 低估节省（保守）；先大后小则相反，是危险方向。
  检测信号现成：**某指标的 `n` 明显低于同资源其他指标的 `n`**。
  实测扫描两支机队，命中 2 台 RDS（4 个资源-指标对）；另有 2 个 ALB 的
  `ActiveConnectionCount` 覆盖不足，但那已由 `cli-recipes.md §2.6` 的覆盖度门槛
  正确处理，不算缺陷。**这两台目前没产出错误建议**（都被 `FreeableMemory`
  独立否决），所以 F 的优先级低于本轮，但它的影响面是全服务的。
