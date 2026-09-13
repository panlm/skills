# 托管服务初选目标：真实回放门禁结果

对账号 `123456789012` / `ap-east-1` 的归档 `raw/` 数据离线重放
（12 RDS + 11 Redis 复制组 + 8 MSK 集群）。**无任何 AWS API 调用** ——
输入只有归档数据与本 skill 的 `references/`。

适配方式：取归档 `solver-in`（它已含托管行的全部旧字段），补本轮新增的
`candidates` / `cur_usd` / `arch` / RDS 的 CPU 与存储字段 / `engine` /
`has_replica`，再喂 `references/core.py`。候选池按
`cli-recipes.md` §7.4 的三套复合键从归档价目文件重建。

## 逐条对账（34 项断言，全 PASS）

| 断言 | aggressive | conservative |
|---|---|---|
| RDS downsize 行数 | 9 ✓ | 9 ✓ |
| RDS `verdict` 分布 | `downsize-candidate` 9 / `blocked` 2 / `upsize-candidate` 1 ✓ | 同 ✓ |
| RDS 路线一 / 路线二 | $261.34 / $875.27 ✓ | $261.34 / $875.27 ✓ |
| ElastiCache downsize 组数 | 5 ✓ | 5 ✓ |
| ElastiCache 路线一 / 路线二 | $0 / $1,235.89 ✓ | $0 / $1,158.51 ✓ |
| MSK downsize / 路线一 / 路线二 | 0 / $0 / $0 ✓ | 同 ✓ |
| MSK 全部 `已合理配置` | 8/8 ✓ | 8/8 ✓ |
| MSK 跨架构成因命中 | 2 ✓ | 2 ✓ |
| MSK 价目地板成因命中 | 6 ✓ | 6 ✓ |
| 存储触 0 被报出 | 1 ✓ | 1 ✓ |
| `DBLoad` 峰值反转命中 | 4 ✓ | 4 ✓ |
| 托管行 `confidence == high` | 0 ✓ | 0 ✓ |
| 阶梯最底档告警命中 | 3 ✓ | 3 ✓ |

改动前这三行对头条的贡献是 **$0**（`nb_save_mo` / `b_save_mo` 恒空）。

## 与 spec 初稿的偏差（都是初稿写错、实测更正）

1. **RDS 路线二 $875.27，不是 $635.10。** 我把口径记成了「burst 列求和」，
   而 `route2_max` 是 **Σ max(nb, b) 逐条取更省者**。`db-sit-06` 的
   nb（$261.34）比 b（$21.17）更省，故按 nb 计入。
2. **峰值反转命中 4 台，不是 2 台。** 我只核了 2 vCPU 的那几台，漏了两台
   8 vCPU 的（`Maximum` p95 = 7.0 ⇒ 14 > 8）。后两台最终是 `blocked`，
   注记仍要留 —— 阻断被解决后读者会回到这一行。
3. **conservative 的阶梯最底档告警是 3 台，不是 2 台。** `redis-uat-04`
   在 conservative 下换成 `cache.t4g.medium`，但另三台仍落最底档。

## 回放暴露、单元测试没抓到的两个顺序缺陷

**① 两台 `kafka.m7g.large` 判成 `metric-missing`。** 缺的是
`RequestHandlerAvgIdlePercent`，而 `EnhancedMonitoring=DEFAULT` 不发布它。
客户读到这句会去开 enhanced monitoring —— 而全区唯一更便宜的 broker 机型是
x86、跨架构为硬约束禁止项，那条建议**结构性不可能产出**。
可行性探针原本只在 `eval_rds` 里提前了，`eval_msk` / `eval_elasticache` 的
仍在末尾。修复后 8/8 报出具体成因。

**② 磁盘写满那台（`FreeStorageSpace` `Minimum` 最小值 0 GiB）只报了
「降配会 OOM」。** 存储判据排在 `FreeableMemory` 之后，于是从没跑到 ——
而按它自己的措辞它「优先级高于本行任何降配讨论」。已前移。

两条都补了单元测试（`test_storage_exhaustion_outranks_the_oom_block`、
`test_every_msk_row_names_its_specific_cause`）。

## EC2 基线未动

`tests/test_regression_fleet.py` 在改动前后各跑一次，14 passed，
`route1_nb` / `route2_max` 逐分相同。该 fixture 是 EC2 独占的 13 行，
本轮不碰 EC2 路径，任何变动都会是回归。

## 安全自检

`SKILL.md` 自带的三条 grep 全部 `CLEAN`：只读、无账单 API、
`update-kubeconfig` 均写入临时 kubeconfig。

## 测试总数

165 passed（改动前 121）。新增 44 条：选型 helper 与三个服务各自的 fit 边界、
候选池为空的五种成因、向后兼容（三条不同的旧路径）、PI 排除与量化、
CPU 轴与峰值口径、三个新出口的逐出口 blocker 保序、`FreeStorageSpace`、
峰值反转、托管回归基线、两个新真值源的守卫。

## 复算脚本

`replay-20260913/adapt_and_replay.py` 在私有工作区的归档目录下，
**不在本仓库**（产出根 `report_output/` 已在 `.gitignore`，跑 skill 产生的
报告含真实账号与资源 ID）。
