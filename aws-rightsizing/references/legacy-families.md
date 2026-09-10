# legacy 机型族排除清单（第一道过滤）

核实日期：2026-09-03 · CPU 型号来自 pricing API `physicalProcessor`（客观可验证）

## 为什么用 CPU 微架构而不是"发布年份"

发布年份没有任何 API 提供，只能靠文档或记忆。CPU 微架构则直接来自
pricing API 的 `physicalProcessor` 字段，是客观数据。Intel/AMD 微架构的发布年份
是公开且稳定的，因此"微架构 → 年代"这条链完全可验证。

## 排除清单及年代证据

| 族 | 物理 CPU | 微架构 | 微架构年份 | 用途分类 |
|---|---|---|---|---|
| t1 | Variable | 前 Xeon 命名 | ~2010 | Micro instances |
| m1 | Intel Xeon Family | 未标明代次 | ~2007–2010 | General purpose |
| m2 | Intel Xeon Family | 未标明代次 | ~2010 | Memory optimized |
| c1 | Intel Xeon Family | 未标明代次 | ~2010 | Compute optimized |
| cr1 | Intel Xeon E5-2670 | Sandy Bridge | 2012 | Memory optimized |
| g2 | Intel Xeon E5-2670 | Sandy Bridge | 2012 | GPU instance |
| m3 | Intel Xeon E5-2670 v2 | Ivy Bridge | 2013 | General purpose |
| c3 | Intel Xeon E5-2680 v2 | Ivy Bridge | 2013 | Compute optimized |
| r3 | Intel Xeon E5-2670 v2 | Ivy Bridge | 2013 | Memory optimized |
| i2 | Intel Xeon E5-2670 v2 | Ivy Bridge | 2013 | Storage optimized |
| c4 | Intel Xeon E5-2666 v3 | Haswell | 2014 | Compute optimized |
| m4 | Intel Xeon E5-2676 v3 | Haswell | 2014 | General purpose |
| d2 | Intel Xeon E5-2676 v3 | Haswell | 2014 | Storage optimized |
| x1 | Intel Xeon E7-8880 v3 | Haswell | 2014 | Memory optimized |
| t2 | Intel Xeon Family | 未标明代次 | ~2014 | General purpose |
| r4 | Intel Xeon E5-2686 v4 | Broadwell | 2016 | Memory optimized |
| i3 | Intel Xeon E5-2686 v4 | Broadwell | 2016 | Storage optimized |
| g3 | Intel Xeon E5-2686 v4 | Broadwell | 2016 | GPU instance |
| p2 | Intel Xeon E5-2686 v4 | Broadwell | 2016 | GPU instance |
| **a1** | **AWS Graviton Processor** | **Graviton1** | **2018** | General purpose |
| cc2 / cg1 / hs1 | — | — | — | 已完全退役，东京 pricing 数据中查不到 |

## 当代族对照（允许作为候选）

| 族 | 物理 CPU | 微架构 | 年份 |
|---|---|---|---|
| t3 | Intel Skylake E5 2686 v5 | Skylake | 2017 |
| t3a | AMD EPYC 7571 | Naples（EPYC 一代） | 2018 |
| m6g / c6g / r6g / t4g | AWS Graviton2 | Graviton2 | 2019 |
| m6i / c6i / r6i | Intel Xeon 8375C | Ice Lake | 2021 |
| m6a / r6a | AMD EPYC 7R13 | Milan | 2021 |
| c7g / m7g / r7g | AWS Graviton3 | Graviton3 | 2022 |
| m7i / c7i / r7i | Intel Xeon Scalable | Sapphire Rapids | 2023 |
| c7a / m7a / r7a | AMD EPYC 9R14 | Genoa | 2023 |
| m8g / c8g | AWS Graviton4 | Graviton4 | 2024 |
| m8i | Intel Xeon Scalable | Granite Rapids | 2025 |

**最老的当代族（t3, Skylake 2017）比最新的 legacy 族（a1, Graviton1 2018）
还早**——所以单看年份分不开，判据必须是"同角色是否已被取代"（见下节）。

`a1` 该排除的理由是它被 `m6g` 取代：两者同为 arm64 通用型，Graviton2 全面替代
Graviton1，且 AWS 已不再扩展 a1 产品线。同时 `a1.large` 单价是同规格组最低
（$0.0642，比 `m6g.large` 低 35%），不显式排除必被"最便宜够用"选中。

## 为什么这道过滤必须在跨分类之前

价格证据（东京 OD，同规格组内相对最便宜者）：

| 族 | $/hr | 相对同组最便宜 |
|---|---|---|
| **a1.large** | **0.0642** | **100%（最便宜）** |
| m6g.large | 0.0990 | 154% |
| m7g.large | 0.1054 | 164% |
| **i3.large** | **0.1830** | **100%（最便宜）** |
| i4i.large | 0.2010 | 110% |
| m4.large | 0.1290 | 104%（vs m5/m6i 的 100%） |
| t2.large | 0.1216 | 141%（vs t4g.large 100%） |

`a1` 与 `i3` 在各自组内**单价最低**，不先排除就一定会被"最便宜够用"选中。
`m4` 只贵 4%，价格过滤同样拦不住。
`t2` 反而更贵，价格过滤已能排除，列入仅为保险。

跨 region 稳定性：a1 在 ap-northeast-1 与 us-east-1 均为同组最便宜；
i3 在两地均低于 i4i。故本清单在所有 region 都必需。

## 过滤顺序（不可调换）

```
1. legacy 族清单        ← 本文件，先剔除过老机型
2. 机型用途分类          ← 在剩余机型中，允许 GP/Compute/Memory 三类互跨
3. region 级可用性       ← 目标机型必须在目标 region 可提供
4. 规格与硬约束          ← vCPU / 内存 / EBS 基线 / 本地盘 / 同架构
5. 价格升序取第一        ← 最便宜够用
```

第 1 步必须在第 2 步之前：先剔除老机型，再在"干净"的机型池里允许跨分类。
否则跨分类会把 a1 / i3 这类最便宜的老机型拉进来。

## 排除判据：同角色存在更新代次，才排除

**不是"属于某代 Graviton/Xeon 就排除"，而是"同角色已被更新代次取代才排除"。**
清单里每一族都必须能指出取代它的族；指不出，就不该排除。

已按此判据核过全表，"←" 右侧为取代它的族：

| 被排除 | 取代者 | 角色 |
|---|---|---|
| t1 ← t2/t3 | | x86 突增型 |
| t2 ← t3 / t3a | | x86 突增型 |
| **a1 ← m6g** | Graviton2 全面替代 Graviton1 | arm64 通用 |
| m1 / m2 / m3 ← m5 / m6i | | 通用 |
| c1 / c3 / c4 ← c5 / c6i | | 计算优化 |
| m4 ← m5 / m6i | | 通用 |
| r3 / r4 ← r5 / r6i | | 内存优化 |
| cr1 / x1 ← x2idn / x2iedn | | 内存优化（高内存） |
| i2 / i3 ← i4i / i7i | | 存储优化 |
| d2 ← d3 / d3en | | 存储优化 |
| g2 / g3 ← g6 | | GPU |
| p2 ← p5 | | GPU |
| cc2 / cg1 / hs1 | 已完全退役，无对应型号 | — |

### Graviton2 不列入清单

`m6g` / `c6g` / `r6g` / `t4g` / `g5g` / `im4gn` / `is4gen` 及其 d/n 变体
**均不排除**。虽然 Graviton3(2022)、Graviton4(2024) 已发布，但 Graviton2
仍是在售的当代产品线，且价格显著低于 G3/G4，是有效的降配目标。

代价（回归 fixture 实测，`tests/fixtures/regression-fleet.json`，aggressive）：
若整代排除 Graviton2，路线一从 **$527.15 降至 $497.36**、
路线二从 **$668.85 降至 $595.62**，且 `m6g.large → m7g.large`、
`r6g.medium → r7g.medium` 这类替换只是把便宜的换成略贵的，无实际收益。

（这四个数改过两轮。2026-09-04 加 `max_mem_reduction_ratio` 内存降幅地板时，
路线二那一对由 $551.97 → $498.16 重测为 $534.01 → $480.20，路线一未变。
2026-09-09 采样量改成置信度分档后，fixture 里两台低样本实例不再被拒绝、
改为带 `confidence=low` 出建议，四个数**全部**重测为现值。
注意排除 Graviton2 后的降幅不是一个常数偏移：整代排除会同时排掉那两台的
目标机型 `r6g.large` 与 `m6g.large`，它们改选别的候选，所以两条路线各自重测。
基线迁移的完整对账见 `tests/test_regression_fleet.py` 的 `EXPECTED` 上方注释。）

### 突增型角色的特殊性

x86 突增型**到 t3/t3a 就停了，不存在 t4/t5**；arm64 突增型**只有 t4g，不存在 t5g**。

| 架构 | 突增型族 | 后继 |
|---|---|---|
| x86_64 | t2 / t3 / t3a | t2 被 t3/t3a 取代；t3/t3a 无后继 |
| arm64 | t4g | 无后继 |

所以突增型角色里只有 `t2` 可排除，`t3` / `t3a` / `t4g` 三族虽然芯片都不新
（Skylake 2017 / Naples 2018 / Graviton2 2019），但**无可替代，必须保留**。

命名坑：`t4g` 的 `4` 不是 Intel 线的第 4 代，而是 Graviton 线自己的编号，
`g` 后缀才是标识。不能按数字大小理解代次关系。

## 可用性只做 region 级，不做 AZ 级

用 `describe-instance-type-offerings --location-type region` 取集合。

实测三个来源在 ap-northeast-1 完全一致、两两差集为 0：

| 来源 | 数量（观测值 @2026-09-04） |
|---|---|
| `describe-instance-type-offerings --location-type region` | 1198 |
| `describe-instance-types`（region 级） | 1198 |
| 各 AZ offerings 的并集 | 1198 |

**"三者一致"是稳定结论，"1198"是观测值**（分类见 `cli-recipes.md §0.1`）。
两次实测都一致而计数变了：2026-09-03 三者各 1154、差集 0；
2026-09-04 三者各 1198、差集仍全为 0。所以用哪个来源取集合都行，
但**数量对不上不说明取错了来源**。

**AZ 级会更严但按需求不采用**：实测 `ap-northeast-1d` 比 region 少 112 个机型，
`t3a.micro` 在 `ap-northeast-1c` 完全不提供。若启用 AZ 级约束，同一台
`t3.medium` 在 1a 会得到 `t3a.micro`，在 1c 则降级为 `t3.micro`。
本版本按 region 判定，允许实例在 AZ 间迁移。

## 已知局限

本清单是**人工策展的策略清单**，不是从权威接口推导的完整集合。
两个 `currentGeneration` 字段均不可用作依据：

| 来源 | 判定 |
|---|---|
| `describe-instance-types.CurrentGeneration` | m6i/r6i=false（当代却判否）；t2/i3/x1=true（过老却判是） |
| pricing API `currentGeneration` | m4=Yes、c4=Yes（2014 年机型判为当代） |

两者对 1145 个共同型号有 80 处不一致。前者不随 region 变化
（ap-northeast-1 vs us-east-1，0/1145 不一致），故其不可靠是语义性的。

维护建议：定期用 pricing API 的 `physicalProcessor` 扫描全部候选族，
凡微架构早于 Skylake（2017）的族即为清单补充候选。
