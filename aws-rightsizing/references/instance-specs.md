# 实例类规格查表

核实日期：2026-09-03 · 验证 region ap-northeast-1 / us-east-1

## 映射规则 spec_lookup(class)

1. 去掉服务前缀：`db.` / `cache.` / `kafka.` → 得到候选 EC2 机型名
2. 查 `ec2 describe-instance-types --instance-types <name>`
3. 取 `VCpuInfo.DefaultVCpus`、`MemoryInfo.SizeInMiB / 1024`、
   `ProcessorInfo.SupportedArchitectures[0]`、`BurstablePerformanceSupported`
4. 步骤 2 失败 ⇒ 查下方兜底表
5. 兜底表也没有 ⇒ 该资源标注 `spec-unknown`，不产出降配建议

**架构必须从映射到的 EC2 机型读取，不得按名字推断。** `cache.c7gn` 这类名字
无法靠字面判断 x86 还是 arm64，猜错会违反同架构硬约束。

**实现注意：不要用批量 `--instance-types` 逐个试探。** 一个无效型号会让整批调用失败。
正确做法是先 `describe-instance-types`（无 `--instance-types` 参数）全量落盘一次
（观测值 @2026-09-04，A 类、会漂移，见 `cli-recipes.md §0.1`：ap-northeast-1 返回
1198 个、us-east-1 返回 1371 个，并集 1380），再本地 join。

## 映射实测结果

| 服务 | 类总数 | 映射成功 | 需兜底 |
|---|---|---|---|
| ElastiCache | 91 | 91 | 0 |
| RDS (mysql 8.4.11 / us-east-1) | 251 | 244 | 7 |

ElastiCache 全部 91 个 node type 的**名称**均可映射，但**内存不可用映射值**——见下。

### ⚠️ ElastiCache 的内存必须取 pricing API，不得用 EC2 映射值

**该属性可能为 `null`，比例还不低。** 实测 ap-northeast-1 的
`AmazonElastiCache` 价目：88 个 node type 中 **33 个（37.5%）的 `vcpu` 与 `memory`
均为 `null`**（如 `cache.c8gn.large`、`cache.m4.4xlarge`、`cache.m6g.16xlarge`），
另有条目连 `instanceType` 本身都是 `null`。

处理规则：

- 缺 `vcpu` 或 `memory` 的 node type **直接排除出候选池并计数上报**
- **不得外推**（同族其他规格的值不适用）
- **不得回退 EC2 映射值**——回退就重犯 +29% 那个错

直接 `int(attributes.vcpu)` 会崩（实测崩过一次）；取值前必须判 `null`。

映射只用于取 vCPU 与架构。**内存必须取 ElastiCache pricing API 的 `memory` 属性。**

实测偏差：

| | 值 |
|---|---|
| `cache.t3.medium` 真实内存（`AmazonElastiCache` pricing 的 `memory`） | **3.09 GiB** |
| 映射到 `t3.medium` 后取 `MemoryInfo.SizeInMiB` | **4.00 GiB** |
| 偏差 | **+29%** |

**这比"映射失败"更危险**：映射会成功、值是错的、没有任何信号提示。
而 `DatabaseMemoryUsagePercentage` 是相对**真实节点内存**的百分比，
乘错基数就算错绝对用量，进而算错 `required_gib`。

取法：

```bash
aws pricing get-products --region us-east-1 --service-code AmazonElastiCache \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
  --output json \
| jq '[.PriceList[]|fromjson|{t:.product.attributes.instanceType,
       mem:.product.attributes.memory}]|unique_by(.t)'
```

## ElastiCache node type 可用集合查询

```
aws elasticache describe-reserved-cache-nodes-offerings --region <r> \
  --query 'ReservedCacheNodesOfferings[].CacheNodeType'
```

这是唯一的程序化来源（无专门的规格 API，已实测确认）。它是 RI offerings 列表，
与"可创建的 node type"可能有细微差异，报告中如遇候选缺失需人工复核。

## RDS 可用类查询的性能约束

`describe-orderable-db-instance-options` **必须 pin `--engine-version`，且不能同步调用**。
实测：不 pin 版本时两次调用均超过 120 秒超时；pin 到 mysql 8.4.11 后响应体 1.8 MB。
原因是它返回 engine × version × class × AZ 的全组合。skill 中应放后台执行或缓存结果。

## 兜底表：无 EC2 对应物的 RDS 实例类

`db.x2g.*` 是 RDS 专有类，EC2 无同名机型。规格取自 `x2gd.*`——两者 vCPU/内存阶梯
完全一致（实测 `x2gd.large` = 2C/32G 对应 `db.x2g.large`），差异仅在 x2gd 带本地 NVMe。
架构均为 **arm64**。

| class | vcpu | gib | arch | 规格来源 |
|---|---|---|---|---|
| db.x2g.medium | 1 | 16 | arm64 | x2gd.medium |
| db.x2g.large | 2 | 32 | arm64 | x2gd.large |
| db.x2g.xlarge | 4 | 64 | arm64 | x2gd.xlarge |
| db.x2g.2xlarge | 8 | 128 | arm64 | x2gd.2xlarge |
| db.x2g.4xlarge | 16 | 256 | arm64 | x2gd.4xlarge |
| db.x2g.8xlarge | 32 | 512 | arm64 | x2gd.8xlarge |
| db.x2g.12xlarge | 48 | 768 | arm64 | x2gd.12xlarge |
| db.x2g.16xlarge | 64 | 1024 | arm64 | x2gd.16xlarge |

## burstable 基线 CPU 表（已内置，无需再查文档）

来源：`https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html`
抓取日期：2026-09-03 · 28 个型号

**这张表里的百分比是稳定事实（B 类，分类见 `cli-recipes.md §0.1`），该当断言用**——
对不上就是有人抄错了，不是"漂移了"。理由见下一节。只有**行数**会随新机型族增长，
那由「未知型号必须降级」那道防护接住。

`describe-instance-types` 只返回 `BurstablePerformanceSupported` 布尔值，
**不提供基线百分比**（已实测确认），故本表内置。

### 为什么可以内置

基线百分比是已发布机型族的固定产品特性，AWS 不会回溯修改（不会把 t3.large
的 30% 改成别的）。会变的只是**新增机型族**，所以只需防"表里没有"，
不需要防"表里的值过期"。

### 两道防护

1. **未知型号必须降级，不得外推。** 遇到表中没有的 burstable 型号，
   该型号标 `baseline-unknown` 并跳过，同时提示 operator 刷新本表。
   **禁止按同规格其它族外推**——实测 t2.2xlarge 是 17% 而 t3.2xlarge 是 40%，
   差 2.4 倍，外推会严重错估。

2. **运行时自校验（免费）。** skill 已为 T 实例采集 `CPUCreditBalance`。
   信用上限的机制是 24 小时攒入量，因此：

   ```
   cap = vcpu × baseline_pct × 1440
   → baseline_pct = observed_cap / (vcpu × 1440)
   ```

   若实例已攒满（`CPUCreditBalance` 恒定），即可反推基线并与本表比对，
   不一致则报出。本表就是自校验的，不需要额外 API 调用。

### 表的三重校验结果（2026-09-03）

| 校验 | 结果 |
|---|---|
| `cap = vcpu × pct × 1440` | 28 行全部一致 |
| `earn_per_hr = vcpu × pct × 60` | 28 行全部一致 |
| 本账号实测 `t3.medium` cap=576 反推 20% vs 文档 20% | 精确吻合 |

`CPUCreditUsage` 侧交叉验证：该实例稳态 CPU 0.9% × 2 vCPU = 0.018 vCPU
→ 预期 1.08 credits/hr；实测 0.98–2.19 credits/hr，吻合。

### 基线百分比不随规格线性增长

| 族 | nano | micro | small | medium | large | xlarge | 2xlarge |
|---|---|---|---|---|---|---|---|
| t3 / t3a / t4g | 5% | 10% | 20% | 20% | 30% | 40% | 40% |
| t2 | 5% | 10% | 20% | 20% | 30% | 22.5% | 17% |

t2 的 xlarge/2xlarge 明显低于 t3 同规格，这是禁止外推的直接依据。

### 完整表

`baseline_pct` 为**每 vCPU** 的基线利用率。
可持续容量 = `vcpu × baseline_pct`（即"基线绝对值"列）。

| 机型 | vCPU | baseline_pct/vCPU | 基线绝对值(vCPU) | earn/hr | cap |
|---|---|---|---|---|---|
| t2.nano | 1 | 5% | 0.05 | 3 | 72 |
| t2.micro | 1 | 10% | 0.1 | 6 | 144 |
| t2.small | 1 | 20% | 0.2 | 12 | 288 |
| t2.medium | 2 | 20% | 0.4 | 24 | 576 |
| t2.large | 2 | 30% | 0.6 | 36 | 864 |
| t2.xlarge | 4 | 22.5% | 0.9 | 54 | 1296 |
| t2.2xlarge | 8 | 17% | 1.36 | 81.6 | 1958.4 |
| t3.nano | 2 | 5% | 0.1 | 6 | 144 |
| t3.micro | 2 | 10% | 0.2 | 12 | 288 |
| t3.small | 2 | 20% | 0.4 | 24 | 576 |
| t3.medium | 2 | 20% | 0.4 | 24 | 576 |
| t3.large | 2 | 30% | 0.6 | 36 | 864 |
| t3.xlarge | 4 | 40% | 1.6 | 96 | 2304 |
| t3.2xlarge | 8 | 40% | 3.2 | 192 | 4608 |
| t3a.nano | 2 | 5% | 0.1 | 6 | 144 |
| t3a.micro | 2 | 10% | 0.2 | 12 | 288 |
| t3a.small | 2 | 20% | 0.4 | 24 | 576 |
| t3a.medium | 2 | 20% | 0.4 | 24 | 576 |
| t3a.large | 2 | 30% | 0.6 | 36 | 864 |
| t3a.xlarge | 4 | 40% | 1.6 | 96 | 2304 |
| t3a.2xlarge | 8 | 40% | 3.2 | 192 | 4608 |
| t4g.nano | 2 | 5% | 0.1 | 6 | 144 |
| t4g.micro | 2 | 10% | 0.2 | 12 | 288 |
| t4g.small | 2 | 20% | 0.4 | 24 | 576 |
| t4g.medium | 2 | 20% | 0.4 | 24 | 576 |
| t4g.large | 2 | 30% | 0.6 | 36 | 864 |
| t4g.xlarge | 4 | 40% | 1.6 | 96 | 2304 |
| t4g.2xlarge | 8 | 40% | 3.2 | 192 | 4608 |

机器可读副本：`references/baseline-pct.json`（`{型号: 小数比例}`）。

### burstable 候选族随当前架构而变

同架构硬约束的自然结果。`c7g → t4g` 与 `m5 → t3` 是同一类动作，都不跨 CPU 架构。

| 当前架构 | 候选族 | 规格上限 |
|---|---|---|
| `x86_64` | t3 / t3a | `burstable_max_vcpu` / `burstable_max_gib` |
| `arm64` | t4g | 同上（`t4g.2xlarge` 即该上限） |

**`t2` 不在候选族内**：它在 `legacy-families.json` 的排除清单里，
`passes_common` 的 legacy 过滤先于跨分类放行执行，整族永远进不了候选池。
上面的基线表仍保留 `t2.*` 各行——它们是产品事实，用于核对 `CPUCreditBalance`
上限，不代表可推荐。

### burstable 候选的两个容量约束（缺一不可）

```
稳态：cur_vcpu × sus_cpu%  <=  cand_vcpu × baseline_pct × (1 − headroom)
峰值：cand_vcpu            >=  ceil(cur_vcpu × peak_cpu% / ceiling_cpu_max)
```

峰值约束不可省：**突发最高只到标称 vCPU 的 100%，不能超过**。
实测踩过一次——`c7g.xlarge` 峰值 52.9% 即需 2.12 vCPU，
若只查基线会选出 `t4g.large`（标称仅 2 vCPU），物理上服务不了该峰值。


## MSK broker 型号集合

MSK **无** broker 型号列表 API（`aws kafka` 无相应操作，已实测确认）。
型号集合需由文档维护。本次未取回，标记为待补。
MSK broker 型号同样走 `kafka.<family>.<size>` → EC2 映射取规格。

## 排除类：无固定实例类的资源

| class | 处理 | 原因 |
|---|---|---|
| `db.serverless` | 排除出桶 A，不产出降配建议 | Aurora Serverless v2 按 ACU 自动伸缩，无固定 vCPU/内存，本框架的规格降配对它无意义 |

实测：`us-west-2` 的 RDS 实例中出现 `db.serverless`，映射必然失败，须走排除而非 `spec-unknown`。

## 当前机型已是 burstable 时的处理

`CPUUtilization` 在 T 机型上仍按完整 vCPU 的百分比计量，因此
`cur_vcpu × sus_cpu%` 得到的绝对持续消耗量是有效的，`required_*` 可正常计算，
不受 `baseline_pct` 未知影响。

但 non-burstable 候选常常不构成降配：例如 `t3.medium`(2C/4G) 持续 5%，
`required_vcpu` 算得 1，而最小的满足 `>=1C/>=4G` 的 non-burstable 机型
（如 `m5.large` 2C/8G）nominal vCPU 并未减少 ⇒ `delta_vcpu = 0`
⇒ 应输出"已合理配置"，**不得包装成降配建议**。

实测样本：ap-northeast-1 的某 MSK 集群使用 `kafka.t3.small`，
2 broker，`EnhancedMonitoring=PER_TOPIC_PER_PARTITION`。
