# 三处计价错误：gp2→gp3 只扣存储差价且阈值写错、专用租户规则只写在文字里、公有 IPv4 被判成取不到价

> **本文已脱敏。** 不含账号 ID、实例 ID、卷 ID；验证用的卷以「容量 + 宿主机型」描述。
> **指标值、点数、单价是原值** —— 它们是结论的证据。

**日期**：2026-10-04
**状态**：待 review
**触发**：对照外部同类 skill 时自查出 7 项缺陷，本文处理其中与计价相关的三项。
另四项（ASG 成员、ElastiCache CPU 口径、候选机型 I/O 适配、Compute Optimizer
交叉校验）各自另立 spec。

## 问题陈述

### P1：gp2→gp3 的阈值写错了维度

现文（`SKILL.md:300`，`docs/method-explained.html` 的 EBS 节、
`docs/specs/2026-09-03-utilization-based-rightsizing-design.md:388` 同句）：

> 原容量 > 334 GiB 时基线 IOPS 已超 3000，转 gp3 必须显式配 IOPS。

AWS EBS 文档（General Purpose SSD 一页）给的是：

| gp2 容量 | IOPS（3 IOPS/GiB，下限 100） | 吞吐 |
|---|---|---|
| ≤ 170 GiB | 基线 < 3000，可突发到 3000 | 最高 128 MiB/s |
| 170–334 GiB | 同上 | 可突发到 250 MiB/s |
| 334–1000 GiB | 同上 | 持续 250 MiB/s |
| > 1000 GiB | 基线 > 3000（5,334 GiB 起封顶 16,000），不再突发 | 持续 250 MiB/s |

gp3 基线 3000 IOPS / 125 MiB/s，不突发，超出部分按量另配。

所以 **334 GiB 是吞吐的分界点，不是 IOPS 的**。按原文执行有两个方向的错：
334–1000 GiB 的卷被要求去配 IOPS（白花钱，而吞吐照样从 250 掉到 125）；
170–334 GiB 的卷什么都不配（突发吞吐丢失）。真正需要另配 IOPS 的只有 > 1000 GiB 的卷。

**≤ 170 GiB 的 128 MiB/s 已与三处 AWS 官方来源核对一致**：EBS 用户指南
（General Purpose SSD）、AWS Storage Blog「Migrate your Amazon EBS volumes from gp2 to gp3
and save up to 20% on costs」、EMR 管理指南「Selecting IOPS and throughput when migrating
to gp3」。后两者给出官方迁移配置表：

| gp2 容量 | gp3 IOPS | gp3 吞吐 |
|---|---|---|
| 1–170 GiB | 3000 | 125 MiB/s |
| 170–1000 GiB | 3000 | 125 MiB/s；按实际用量调高，最高 250 MiB/s |
| > 1000 GiB | 对齐 gp2（容量 × 3），或当前卷实际驱动的最大 IOPS | 同上 |

「Monitor I/O characteristics」页有一句「a gp2 volume under 1,000 GiB with burst credits
available has … a volume throughput limit of 250 MiB/s」，是不分档的泛化举例，不作依据。
本文 C2 的「按实测、以 gp2 能力封顶」与这张官方表同构；≤ 170 GiB 封顶取 128 而非
官方表的 125，比官方略严，差 3 MiB/s（约 $0.12/月）。

### P2：节省额只算存储差价，且这个算式没有代码载体

`report-template.md` 填法表的 gp2 行：`other_save_mo` = 「gp3 与 gp2 的月额差」。
为了不降性能而另配的 IOPS / 吞吐费用没有扣，大卷与高吞吐卷的节省额偏高。

这笔费用也**无从计算**：`AWS/EBS` 命名空间整个没有采集，卷的实际 IOPS / 吞吐不可得。
而且这一行是采集侧自建行，金额由 agent 照散文现算 —— repo 自己的规律是
「有代码载体的判据一次就对；只有散文描述的判据全部出过问题」（`sample-solve.md` 开头）。

### P3：专用租户的排除规则只写在文字里；Spot 未披露

`SKILL.md:75-76` 要求 `Placement.Tenancy` 非 `default` 的实例「标 `price-unknown` 排除，
不得套用 Shared 价格」。但 `cli-recipes.md` §7.0 的字段表与 §7.2 的组装式都不带 tenancy，
`core.py` 拿不到这个字段 —— **这条规则只写在文字里**。另有两处同源漏洞：

- `evaluate()` 的 insufficient-data 分支会尽力填 `cur_cost_mo`（`core.py:194-206`），
  专用租户实例照样按共享按需价计入分母。
- EKS 节点池聚合行的「减节点 × 单节点月额」对专用租户成员同样按共享价。

排除专用租户的理由不是单价高低，而是**计费结构**：Dedicated Host 按整台主机计费，
不合并主机时，单台实例降配一分钱都省不下来，按需口径算出的比例是兑现不了的承诺。

**Spot 不是计价错误。** 本 skill 的价格口径（`SKILL.md`「价格口径」一节）是「一律按需理论值，
比例也是按需口径」，与实际账单的差异靠报告开头的强制声明披露 —— Spot 与 RI/SP 属于同一类：
实际账单按另一种价计，按需理论值照算，比例照出。缺的只是披露：强制声明只点名了 RI/SP，
而 §1 的 `describe-instances` 投影不带 `InstanceLifecycle`，报告无从标出哪些实例是 Spot。

### P4：公有 IPv4 被判成取不到价

`cli-recipes.md`「公有 IPv4 取不到价」一节断言 pricing API「三条路都取不到」，
填法表因此把未关联 EIP 行定为 `price-unknown`、`cur_cost_mo` 留空，
`report-template.md:166` 把它列进「未包含项」。

实测 pricing API 取得到：这组记录**没有 `productFamily` 属性**，按 family 查必然为空；
按 `group` 过滤即得（T2）。后果是桶 B 合计漏掉每个未关联 EIP。

## 实测依据（观测值 @2026-10-04，验证账号，全部为只读调用）

### T1：`AWS/EBS` 指标（两块 gp2 卷，80 GiB 与 100 GiB，宿主均为 `m5.large`）

- `list-metrics`：卷级 `VolumeReadOps` / `VolumeWriteOps` / `VolumeReadBytes` /
  `VolumeWriteBytes` / `BurstBalance` 的维度是 `VolumeId`；Nitro 专有的 `VolumeAvgIOPS`
  （Ops/s）、`VolumeAvgThroughput`（KiB/s）、`VolumeIOPSExceededCheck`、
  `VolumeThroughputExceededCheck` 的维度是 `VolumeId` + `InstanceId`。
- **近 24 小时、1 分钟粒度对账（2 卷 × 24 小时）**：
  - `VolumeReadOps` 每小时 `SampleCount` = 60 ⇒ 每个数据点就是 1 分钟。
  - 小时 `Maximum` == 该小时 60 个分钟 `Sum` 中的最大值；小时 `Sum` == 60 个分钟值之和。
    **0 处不符**。
  - `VolumeAvgIOPS` 小时 `Maximum` == max((读 + 写) / 60)，小时 `Average` ==
    mean((读 + 写) / 60)，逐小时差 ≤ 0.01。
- **超出 1 分钟数据的 15 天保留期之后**（20 天前的一天）：1 分钟点已为 0 个，
  `VolumeAvgIOPS` 小时 `SampleCount` 仍为 60 ⇒ 小时 `Maximum` 仍是分钟值的最大值。
- **30 天窗口、Period=3600**：`VolumeAvgIOPS` 720/720 点。
- `VolumeAvgThroughput` 与 (读 + 写字节) / 60 / 1024 对账：1440 个分钟点最大绝对差
  43.4 KiB/s（峰值 12,677.5 KiB/s，约 0.3%），成因未查明。判据只用
  `VolumeAvgThroughput` 本身，不与字节换算混用。
- **`ExceededCheck` 是秒级信号**（7 天 × 1 分钟）：

  | 卷 | IOPS 触顶分钟 | 这些分钟的分钟均值 | 其余分钟最大 | 吞吐触顶分钟 | `BurstBalance` 最低 |
  |---|---:|---:|---:|---:|---:|
  | 80 GiB | 2 / 10,080 | 397–488 IOPS | 207 IOPS | 1 | 99% |
  | 100 GiB | 2 / 10,078 | 382–417 IOPS | 118 IOPS | 2 | 99% |

  AWS 文档：分钟内**任一秒**持续超出卷的性能上限即返回 1。分钟均值远低于 gp2 的
  突发上限却触顶，说明**分钟均值掩盖了秒级突发**，实测峰值低估了真实需求。
- **30 天普查**（两个 region 全部挂在运行中实例上的 gp2 卷，14 块，宿主均为 Nitro）：

  | 量 | 分布 |
  |---|---|
  | 吞吐触顶小时数（/ 720） | 0–27；**12 / 14 块 ≥ 1 小时，0 / 14 块超过 5%** |
  | IOPS 触顶小时数（/ 720） | 0–4 |
  | 峰值吞吐（分钟均值） | 5 块 20 GiB 卷 129–130 MiB/s（即顶在 gp2 的 128 MiB/s 上）；其余 ≤ 31 MiB/s |
  | 峰值 IOPS | 同上 5 块 2,382–2,874；其余 ≤ 548 |

  另有 4 块挂在 stopped 实例上的 gp2 卷**没有任何 `AWS/EBS` 序列**（指标只在卷挂在运行中的
  实例上时发布），它们本就走删除路径、不出 gp3 行。

### T2：取价（pricing API）

| 项 | 过滤 | usagetype（us-west-2） | 单价 |
|---|---|---|---|
| gp3 另配 IOPS | `volumeApiName=gp3`，`productFamily=System Operation` | `USW2-EBS:VolumeP-IOPS.gp3` | $0.005 / IOPS-Mo |
| gp3 另配吞吐 | `volumeApiName=gp3`，`productFamily=Provisioned Throughput` | `USW2-EBS:VolumeP-Throughput.gp3` | **$40.96 / GiBps-mo** |
| gp3 存储 | `volumeApiName=gp3`，`productFamily=Storage` | `USW2-EBS:VolumeUsage.gp3` | $0.08 / GB-Mo |
| gp2 存储 | `volumeApiName=gp2`，`productFamily=Storage` | `USW2-EBS:VolumeUsage.gp2` | $0.10 / GB-Mo |
| 公有 IPv4（闲置） | `AmazonVPC`，`group=VPCPublicIPv4Address` | `USW2-PublicIPv4:IdleAddress` | $0.005 / Hrs |

- **吞吐单价的单位是 GiB/s**：$40.96 / GiBps-mo = $0.04 / MiBps-mo（描述字段原文
  「$0.04 per provisioned MiBps-month」）。直接当成每 MiB/s 的价会高估 1024 倍。
- 公有 IPv4：同一 `group` 下另有 `InUseAddress` 一条（同价）；两条都**没有
  `productFamily`**。ap-northeast-1（`APN1-` 前缀）同为 $0.005。

### T3：实例生命周期与租户

- 按需实例的 `describe-instances` 输出里**没有** `InstanceLifecycle` 键，投影后为 `null`。
  有值时取 `spot` / `scheduled` / `capacity-block`。
- `tests/fixtures/regression-fleet.json` 对应的 13 台：09-04 那次运行的原始 inventory 里
  `Placement.Tenancy` 13/13 为 `default`；2026-10-04 复查其中 12 台仍在运行，
  `InstanceLifecycle` 全为空。

## 预期收益（不粉饰）

- **EBS**：按 T1 普查，14 块卷全部不是持续触顶 ⇒ 全部走实测定档。9 块的峰值远低于
  gp3 基线 ⇒ 不另配，节省额仍是存储差价；5 块 20 GiB 卷的峰值吞吐顶在 gp2 上限 ⇒
  吞吐配到封顶的 128 MiB/s，多配 3 MiB/s，每卷约 $0.12/月；IOPS 全部在 3000 基线内。
  即**多数卷的结论基本不变**，变化集中在 > 170 GiB 且高吞吐或持续触顶的卷，以及
  > 1000 GiB 的卷。两支回归机队的 `core.py` 输入不含 EBS 行 ⇒ **回归基线数字不变**。
- **专用租户 / Spot**：两支回归机队都没有此类实例 ⇒ 基线不变。收益是防止将来含
  Dedicated Host 的机队出现省不下来的金额，以及让 Spot 实例在报告里可见。
- **EIP**：每个未关联 EIP 给桶 B 合计加 `HOURS_PER_MONTH` × $0.005 = $3.65/月。

## 设计

### C1：新增 `AWS/EBS` 采集（`cli-recipes.md` §2.7）

- **范围**：`ebs.json` 里 `type=gp2`、`state=in-use`、且宿主实例在 `ec2.json`（running）
  里的卷，派生为 `ebs-gp2-eval.json`。走删除路径的卷（未挂载 / 宿主 stopped）不采，
  沿用既有的资源级互斥规则。
- **指标与 stat**：

  | 指标 | stat | 用途 |
  |---|---|---|
  | `VolumeAvgIOPS` | `Average`、`Maximum` | IOPS 持续项与峰值项 |
  | `VolumeAvgThroughput` | `Average`、`Maximum` | 吞吐持续项与峰值项（KiB/s） |
  | `VolumeIOPSExceededCheck` | `Maximum` | 秒级 IOPS 触顶 |
  | `VolumeThroughputExceededCheck` | `Maximum` | 秒级吞吐触顶 |

  Period=3600，窗口与其他 namespace 相同（§2.0 ① 对齐到业务本地午夜）。
- **维度**：`VolumeId` + `InstanceId`，用 `mdq-dims.jq` 从 `list-metrics` 回包原样搬
  （多维度指标，不手拼）。`ty` 映射为卷 → `gp2`。
- **聚合**：`agg.jq` 的 `full-window` 档。持续 = `Average` 序列的 p95，峰值 =
  `Maximum` 序列的 max。触顶取 `ExceededCheck` 小时 `Maximum` 序列的两个量：p95（判是否
  持续触顶，见 C2）与 `mean × n`（触顶小时数；序列取值只有 0 / 1，`mean × n` 恰为
  取 1 的小时数，与 §7 求 Σ Sum 是同一个恒等式）。**不只取 `biz-hours`**：
  gp3 的配置 24 小时生效，夜间备份被限流同样是事故，沿用「峰值型取 full-window」的既有规则。
- **不采 `VolumeReadOps` / `VolumeWriteOps` 做 ÷60 换算。** 换算系数这一类错误本 skill
  犯过三次；非 Nitro 实例不发布上面四个指标，交给 C2 的对等兜底处理。
- **预检**：`list-metrics --namespace AWS/EBS --metric-name VolumeAvgIOPS` 为 0 ⇒ WARN
  （全部 gp2 卷按对等配置，节省额偏保守），写进报告缺口。

### C2：`core.gp3_plan()` —— gp3 配置与节省额由代码产出

```
gp3_plan(vol, t, price) -> dict
  vol   = {rid, size_gib, sus_iops, peak_iops, sus_kibs, peak_kibs,
           iops_exceeded_p95, iops_exceeded_hours,
           tput_exceeded_p95, tput_exceeded_hours,
           sample_n, window_points}                  # 缺失一律 None，禁止补 0；后两个可选
  t     = core.load_thresholds(profile)
  price = {gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_mibps_mo}   # 缺失为 None
```

`size_gib` 取 `ebs.json` 的 `.size`；其余 `vol` 字段取 C1 的 `full-window` 聚合。
**终审修订（2026-10-05）**：`sample_n`（full-window 档各序列点数的最小值）与 `window_points`
（`WINDOW_DAYS × 24`）用于覆盖度：`sample_n < window_points` 时追加一条覆盖不足的 blocker，
不改结论（采样量决定置信度，不决定给不给建议）。卷在窗口内新建或换过宿主时会命中。
gp2 三行的 `blockers` 照抄 `gp3_plan()` 的 `blockers`，首条即 gp3 的配置与依据。

1. **gp2 能力上限**：`iops_cap = min(16000, max(3000, 3 × size))`；
   `tput_cap = 128 if size <= 170 else 250`（MiB/s）。
2. **IOPS 与吞吐两个维度各自独立定档，按下列顺序取第一条命中的**：
   1. 持续项、峰值项、触顶序列任一缺失 ⇒ 取能力上限，依据记 `missing-parity`。
   2. **持续触顶**（触顶序列 p95 ≥ 1，即超过约 5% 的小时出现过秒级触顶）⇒ 卷常态顶着
      gp2 的上限跑，实测值被 gp2 压低了，不可信 ⇒ 取能力上限，依据记 `exceeded-parity`。
   3. 否则按实测：`need = max(ceil(持续 / (target_ebs_p95 / 100)), ceil(峰值 / (ceiling_ebs_max / 100)))`，
      `gp3 = clamp(need, gp3 基线, 能力上限)`，依据记 `measured`。这与 EC2 侧 `_required()`
      同形：持续项对目标水位、峰值项对上限水位反推。若触顶小时数 > 0（**偶发触顶**），
      blocker 写明「窗口内 N 小时出现秒级触顶；gp3 吞吐 / IOPS 可在线调高、不停机」。

   **持续态而不是「出现过一次」的理由**：与否决项的持续态口径同源（`_persistent()`，
   容忍度 `VETO_TOLERANCE_PCT`）。「出现过一次即对齐」在 T1 普查的 14 块卷里命中 12 块
   （每块 2–27 / 720 小时），会让一次备份或发布的几秒高峰决定一块卷有没有建议 ——
   170–1000 GiB 的卷对齐吞吐要多配 125 MiB/s（$5/月），而 200 GiB 卷的存储差价只有 $4/月。
   代价：偶发的那几秒，gp3 被限在所配的值上（≥ 125 MiB/s），而 gp2 当时能给到自己的上限。

   吞吐先把 KiB/s ÷ 1024 换成 MiB/s，再向上取整。
   - **上限取 gp2 能力**：迁移承诺「不比现在差」，不是升级；超出 gp2 能力的需求在 gp2 上
     本来就没有被满足，不归这一行买单。
3. **费用**：
   ```
   cur_cost_mo = size × gp2_gb_mo
   gp3_cost_mo = size × gp3_gb_mo + (gp3_iops − 3000) × gp3_iops_mo
               + (gp3_mibps − 125) × gp3_mibps_mo
   other_save_mo = round(cur_cost_mo − gp3_cost_mo, 2)
   ```
4. **出口**：
   - 四个单价任一缺失 ⇒ `verdict=price-unknown`，不出节省额。**即使这块卷不需另配，
     也要求四个单价齐全**：取价是整个 region 一次性取回的，缺一条说明取价配方坏了，
     按卷放行会让同一个坏配方只在部分行上暴露。
   - `other_save_mo <= 0` ⇒ 不出 `storage-type` 行（按「EBS 卷 其他」行填），
     blocker 写明另配的 IOPS / 吞吐吃掉了存储差价。
   - 否则出 `storage-type` 行；blockers 写明要配的 IOPS 与吞吐、各自依据。
5. **gp3 合法性断言**：`gp3_mibps <= 0.25 × gp3_iops`（gp3 的吞吐 / IOPS 比上限），
   以及另配的 IOPS 不超过 `500 × size`。在本设计的取值域内恒成立
   （3000 × 0.25 = 750 > 250；`3 × size <= 500 × size`），写成断言，防止将来改上限时越界。

**调用方式**与 `core.pod_requests()` 同形：采集侧的 python 片段 `import core`，逐卷调用，
产出 `raw/solver/ebs-gp3.json`；填法表 gp2 行的 `cur_cost_mo` / `other_save_mo` 照抄它。
**不进 `main()` 的 `resources` 数组**：卷没有机型判据，不走 verdict 链。

**取价**（`cli-recipes.md` §6.1 的非 EC2 取价表 EBS 行）：补 gp3 另配 IOPS 与吞吐两条，
过滤见 T2。**吞吐单价须断言 `unit == "GiBps-mo"` 才 ÷1024**，单位不符 ⇒ 该单价按缺失处理
（`price-unknown`）。不拼 usagetype 的 region 前缀（既有规则，前缀不能由 region 码推出）。

### C3：两个新阈值键

`thresholds.json` 两个 profile 各加 `target_ebs_p95`、`ceiling_ebs_max`，初值取同 profile
CPU 两键的值：aggressive 60 / 85，conservative 40 / 60（起点相同，以后可以分开调）。`thresholds.md` 各加一行，写明含义：
gp3 另配后，IOPS / 吞吐的持续 p95 与峰值分别不得高于配置量的这两个百分比。
散文只引用键名，不复述数值（`tests/test_no_duplicated_constants.py`）。

### C4：阈值文案改成三档

`SKILL.md:300` 与 `docs/method-explained.html` 的 EBS 节改为：

- 容量 > 170 GiB：gp2 可突发到 250 MiB/s，gp3 基线只有 125 MiB/s；
- 容量 ≥ 334 GiB：gp2 持续 250 MiB/s；
- 容量 > 1000 GiB：gp2 基线 IOPS 超过 3000。

是否另配、配多少，以 `core.gp3_plan()` 的产出为准。
`docs/specs/2026-09-03-utilization-based-rightsizing-design.md:388` 加一行勘误指向本文，
原文不改（spec 是裁定记录）。

### C5：专用租户在 `evaluate()` 里判 `price-unknown`；Spot 照算并披露

- **采集**：§1 的 `describe-instances` 投影加 `lifecycle:InstanceLifecycle`（`ten` 已有）。
  §7.0 字段表加两行：`tenancy`（取 `ten`）与 `lifecycle`（值为 `null` 表示按需）。
  §7.2 组装式输出这两个键；§7.3 必检项 ② 的字段清单加上它们 —— **漏字段在拼完
  `solver-in.json`、跑判据之前就报错**，这是 C5 默认值语义（见下）的前提。
- **判定**：

  | 条件 | 处理 |
  |---|---|
  | `tenancy` 非 `default`（`dedicated` / `host`） | `price-unknown`，原因「租户为 `<值>`：专用租户按另一种结构计费（Dedicated Host 按整台主机），本版本不取价」 |
  | `lifecycle` 非 `null`（`spot` / `scheduled` / `capacity-block`） | **照常按需取价**，blocker「购买方式为 `<值>`：金额为按需理论值，实际账单按该方式计」 |
  | 缺 `tenancy` 或 `lifecycle` 键 | **按 AWS 默认值处理**（`tenancy=default`、按需），blocker「组装未带 tenancy / lifecycle，按 AWS 默认（共享租户、按需）计价」 |

  缺键取默认值的依据：`describe-instances` 总会返回 `Placement.Tenancy`，按需实例本就不返回
  `InstanceLifecycle` —— 缺键只可能来自本 skill 自己拼的中间文件（改版前的旧 `solver-in.json`，
  或组装时漏了字段），而后者由 §7.3 必检项 ② 在跑判据前拦下。
- **两个调用点**（只对专用租户生效）：
  - insufficient-data 分支：专用租户 ⇒ **不填成本**，verdict 仍为 `insufficient-data`
    （verdict 链的优先级不变），blocker 写原因。
  - 主路径查价处：专用租户 ⇒ `price-unknown`，`burst_na` 写原因。
- **桶 B 不变**：`main()` 先跑 `is_idle()` 再按 verdict 落桶，闲置的专用租户实例照样进桶 B，
  不带金额 —— 与现有 `price-unknown` 闲置实例一致。
- **强制声明**：`report-template.md` 开头的第一段，「被 Reserved Instance 或 Savings Plan
  覆盖的资源」改为「被 Reserved Instance 或 Savings Plan 覆盖、或以 Spot 购买的资源」。
- **EKS 节点池**（填法表）：成员行对专用租户节点 `cur_cost_mo` 留空；聚合行另起一行
  「成员含专用租户」，`other_save_mo` 留空并写 blocker。Spot 节点照算（同上口径），
  成员行写 Spot blocker。成员字段来自 `ec2-eksnodes.json`，它由 `ec2.json` 派生，
  §1 改完即带这两个键。
- **回归 fixture 与样例**：`regression-fleet.json` 13 行与 `sample-solve.md` 的样例 EC2 行
  按 T3 补 `tenancy: "default"`、`lifecycle: null` —— 不补也能跑（取默认值），补上是为了
  不让默认值 blocker 污染基线里的 blockers 比对。

### C6：公有 IPv4 取价

- `cli-recipes.md`「公有 IPv4 取不到价」一节改为取价配方：
  `--service-code AmazonVPC`，过滤 `regionCode` 与 `group=VPCPublicIPv4Address`，
  在 jq 里只留 `usagetype` 以 `PublicIPv4:IdleAddress` 结尾的记录，并断言恰好 1 条
  （与 ALB 取价那道断言同形）。保留一句教训：这组记录没有 `productFamily`，按 family 查必空。
- 填法表「EIP 未关联」行：`verdict` 由 `price-unknown` 改为 `excluded`（与 NAT / ALB 闲置行
  一致），`cur_cost_mo` 填小时费月额。删掉「EIP 是 `price-unknown` 而不是 `excluded`」那条
  逐格理由，改写为单价来源。
- `report-template.md:166` 的「未包含项」去掉公有 IPv4。
- 已关联（in-use）的公有 IPv4 同样计费，但本版本不对它出建议（释放它需要改网络架构）。

## 改动清单

| 文件 | 改动 |
|---|---|
| `references/core.py` | 新增 `gp3_plan()`；`evaluate()` 加租户判定（两个调用点）与购买方式 / 缺键默认值两条 blocker |
| `references/thresholds.json` / `thresholds.md` | 两个新键，两个 profile 各一份 |
| `references/cli-recipes.md` | §1 投影；新增 §2.7 `AWS/EBS`；§6.1 EBS 取价两条 + 单位断言；公有 IPv4 一节改写；§7.0 字段表；§7.2 组装式；§7.3 必检项 |
| `references/report-template.md` | 开头强制声明加 Spot；填法表：gp2 行（金额来自 `gp3_plan()`）、新增「gp2 取不到 gp3 单价」行、EIP 行、EKS 成员行与新增的「成员含专用租户」聚合行；逐格理由；「未包含项」 |
| `references/metrics-catalog.md` | 新增 `AWS/EBS` 一节（指标、维度、单位、Nitro 限定、实测状态） |
| `references/sample-solve.md` | 样例 EC2 行补 `tenancy` / `lifecycle` |
| `SKILL.md` | EBS 一节（:300）；tenancy 规则（:75）改为指向代码；「价格口径」一节 RI/SP 那句补上 Spot；preflight 表加 `AWS/EBS` 探测；验证状态表；易错项速查加三行（吞吐单价按 GiB/s、公有 IPv4 无 productFamily、IOPS 不走 ÷60 换算） |
| `docs/method-explained.html` | EBS 段落；预设表加两个新键 |
| `docs/specs/2026-09-03-utilization-based-rightsizing-design.md` | :388 加勘误指向本文 |
| `docs/README.md` | specs / plans 索引各加一行 |
| `../README.md` / `../README_CN.md` | 描述里补一句 gp2→gp3 按实测 IOPS / 吞吐对齐 |

### 测试影响

- **新增 `tests/test_gp3_plan.py`**：measured 路径；两个维度各自的持续触顶（p95 ≥ 1）
  触发对等；偶发触顶（p95 = 0、小时数 > 0）走实测并带 blocker；指标缺失对等；170 / 171 / 334 / 1000 / 1001 / 5334 GiB 边界；节省额 ≤ 0 不出行；吞吐单位断言；
  单价缺失 ⇒ `price-unknown`；零值不被当缺失（`peak_iops = 0` 是有效值）。须带 `__main__`
  runner，报告条数等于 `test_*` 个数（`test_gate_covers_every_test.py`）。
- **`test_fail_closed_contracts.py`**：dedicated、host ⇒ `price-unknown`；Spot ⇒ 照常取价并带
  blocker；缺键 ⇒ 按默认值取价并带 blocker；insufficient-data 分支对专用租户不填成本、
  对 Spot 照填。
- **`test_csv_contract.py`**：`REQUIRED_ROWS` 加两行（gp2 取不到 gp3 单价、EKS 聚合行的
  「成员含专用租户」变体）；`test_fill_table_covers_the_new_savings_column` 的「恰好两行带
  `other_save_mo`」不变 —— 新增的两行都留空。
- **`test_regression_fleet.py`**：fixture 13 行补 `tenancy: "default"`、`lifecycle: null`
  （依据 T3），`EXPECTED` 逐值不变。
- **`test_sample_reproduces.py`**：`sample-solve.md` 样例补键后照常复现。
- **`test_method_explained.py`**：`TABLE_KEYS` 加两个新键，钉住预设表。
- **`test_no_duplicated_constants.py`**：两个新键必须被 `core.py` 读到（双向覆盖），
  散文不得复述其数值。

## 验证方式

1. 全部测试按 `SKILL.md` 的门禁循环跑，每个文件打印 `n/n passed`。
2. **真实回放**（验证账号，只读）：us-west-2 与 ap-northeast-1 的全部在用 gp2 卷跑 §2.7
   采集与 `gp3_plan()`。记录按依据（measured / exceeded-parity / missing-parity）的分布、
   改动前后的 `other_save_mo` 合计，写进 plan 的回放一节（脱敏）。
3. 两个 region 各跑一次 §6.1 的 EBS 取价与公有 IPv4 取价，确认单位断言与「恰好 1 条」断言通过。
4. 隐私闸门 `tests/test_no_private_data.py` 通过。

## 明确不做

- 不取 Spot 实际价（`describe-spot-price-history`）：Spot 按需理论价照算并披露，与 RI/SP 同口径。
- 不为专用租户取价：标 `price-unknown` 即止。
- 不处理 EKS / ASG 节点卷「原地改 gp3 会在节点替换后回到 gp2」的问题，留给子项目 B。
- 不用 `VolumeReadOps` / `VolumeWriteOps` ÷60 换算 IOPS；非 Nitro 实例走对等兜底。
- 不评估 io1 / io2 / gp3 的过度预配（列在暂缓的参考项里）。
- 不改 EC2 与托管判据的其他部分；ASG、ElastiCache CPU、I/O 适配、Compute Optimizer 另立 spec。
- 不对已关联的公有 IPv4 出建议。
- 中国区仍未验证（`partition-matrix.md`）。

## 后续

- 非 Nitro 路径**未实测**：T1 普查的 14 块在用卷宿主全是 Nitro；验证账号里两台 Xen（`c4`）
  实例处于 stopped，它们的卷走删除路径。首次遇到挂在运行中 Xen 实例上的 gp2 卷的真实运行，
  就是这条兜底的第一次验证。
- `VolumeAvgThroughput` 与字节换算约 0.3% 的差，成因未查明；判据不依赖二者相等。
- 下一个子项目 B：ASG 成员不再逐台出降配建议。同一问题的卷侧形态一并处理：验证账号里
  5 块 20 GiB gp2 卷是 EKS 节点组的节点根卷，原地改 gp3 后节点一替换就回到 gp2，
  建议须落到 launch template。
