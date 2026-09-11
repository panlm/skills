# CLI / jq 配方

核实日期：2026-09-03 · 全部命令在 ap-northeast-1 与 us-west-2 实测通过
（§2.3 RDS、§2.4 ElastiCache、§4 EKS 于 2026-09-03 在 us-west-2 首次跑通真实资源）

所有命令均为 `describe*` / `list*` / `get*`。**禁止任何 mutating 调用，
禁止 `ce:*` 及任何账单 API。** `pricing:GetProducts` 允许（读公开按需价目）。

产出根为 `report_output/<account>-<region>-<YYYYMMDD>/`，原始数据落其 `raw/` 子目录。
下文用 `$O` 表示该作用域目录、`$IV=$O/raw/inventory`、`$M=$O/raw/metrics`、
`$SP=$O/raw/specs`、`$S` 表示 skill 根目录（`references/` 的父目录）。

## §0 前置：全量机型规格落盘

不要用 `--instance-types` 批量试探——一个无效型号会让整批调用失败。

```bash
aws ec2 describe-instance-types --region $R \
  --query 'InstanceTypes[].{t:InstanceType,vcpu:VCpuInfo.DefaultVCpus,mib:MemoryInfo.SizeInMiB,burst:BurstablePerformanceSupported,arch:ProcessorInfo.SupportedArchitectures[0],ebs:EbsInfo.EbsOptimizedInfo.BaselineThroughputInMBps,net:NetworkInfo.NetworkCards[0].BaselineBandwidthInGbps,store:InstanceStorageSupported}' \
  --output json | jq '[.[] | .gib=(.mib/1024)]' > $SP/ec2-types.json
```
机型数（**观测值 @2026-09-04，会漂移，见 §0.1**）：ap-northeast-1 = 1198，
us-west-2 = 1350。**按 region 现查，不可复用。**

可用性过滤（候选必须在目标 AZ 真实可用）：
```bash
aws ec2 describe-instance-type-offerings --region $R \
  --location-type availability-zone \
  --query 'InstanceTypeOfferings[].{t:InstanceType,az:Location}' --output json \
  > $SP/offerings-az.json
```

### §0.1 哪些数字是观测值、哪些是稳定事实

本套文档里的数字分两类，**读的人必须能一眼分清**，否则两种错都会犯：把观测值
当断言（发现对不上就去改模板、或者更糟：以为采集坏了）、把稳定事实当参考值
（跳过刻度确认这类必做的核对）。

**A 类：观测值，会漂移。** 一律带「观测值 @日期」标记。**对不上属正常，
不必修模板，也不必怀疑采集**；但**必须现查，不得把这里的数字当输入用**。

| 观测项 | 出处 | 漂移原因 |
|---|---|---|
| 机型数 / `offerings` 数 | §0、§6.2 | AWS 持续上新机型，且按 region 分批放量 |
| 唯一 `(型号, operation)` 键数 | §6.1、「价目缓存」一节 | 同上，且随授权/平台组合增减 |
| 价目全量取回的体积与耗时 | §6.1、「价目缓存」一节 | 随条数增长，耗时还随网络与并发波动 |
| 各 region 之间的差集 | §6.2 | 两端都在动，差集不是稳定量 |

**漂移是实测到的，不是理论担心**：ap-northeast-1 的机型数 **2026-09-03 = 1154、
2026-09-04 = 1198**（一天 +44），同两天 us-west-2 稳在 1350、us-east-1 稳在 1371
——即**同一天不同 region 的漂移速率不同**，所以"另一个 region 没变"不能证明
本 region 没变。同两天 ap-northeast-1 的唯一 `(型号, operation)` 键数
19,534 → 19,754。

**B 类：稳定事实，该当断言用。** 不带日期标记，变了就是有人改错了：

| 稳定项 | 出处 | 为什么稳定 |
|---|---|---|
| T 系列基线百分比 | `baseline-pct.json`、`instance-specs.md` | AWS 对每个 T 型号的 CPU 基线是产品定义，随型号固定 |
| 指标刻度（0–1 与 0–100） | `thresholds.md` 刻度表、`mdq-msk.jq` | 指标的发布口径，与机型上新无关 |
| CloudWatch API 的硬限制与维度名 | §2.0、§2.5 | 接口契约 |
| 阈值 | 只在 `thresholds.json` | 唯一真值源，改它才叫改 |

**判断规则：一个数字若来自"AWS 目录当下有多少东西"，就是 A 类；
若来自"这个接口/产品是怎么定义的"，就是 B 类。**

## §1 资源清单采集

```bash
mkdir -p $IV $M $SP

aws ec2 describe-instances --region $R \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{id:InstanceId,type:InstanceType,az:Placement.AvailabilityZone,arch:Architecture,op:UsageOperation,ten:Placement.Tenancy,name:Tags[?Key==`Name`]|[0].Value,launch:LaunchTime}' \
  --output json > $IV/ec2.json

aws ec2 describe-instances --region $R \
  --filters Name=instance-state-name,Values=stopped \
  --query 'Reservations[].Instances[].{id:InstanceId,type:InstanceType,op:UsageOperation,name:Tags[?Key==`Name`]|[0].Value}' \
  --output json > $IV/ec2-stopped.json

aws ec2 describe-volumes --region $R \
  --query 'Volumes[].{id:VolumeId,type:VolumeType,size:Size,iops:Iops,tput:Throughput,state:State,attach:Attachments[0].InstanceId,az:AvailabilityZone,ct:CreateTime}' \
  --output json > $IV/ebs.json

aws ec2 describe-addresses --region $R \
  --query 'Addresses[].{id:PublicIp,alloc:AllocationId,assoc:AssociationId,iface:NetworkInterfaceId}' \
  --output json > $IV/eip.json

aws ec2 describe-nat-gateways --region $R \
  --query 'NatGateways[?State==`available`].{id:NatGatewayId,vpc:VpcId,subnet:SubnetId}' \
  --output json > $IV/nat.json

aws elbv2 describe-load-balancers --region $R \
  --query 'LoadBalancers[].{id:LoadBalancerName,arn:LoadBalancerArn,type:Type,scheme:Scheme}' \
  --output json > $IV/elb.json

aws rds describe-db-instances --region $R \
  --query 'DBInstances[].{id:DBInstanceIdentifier,type:DBInstanceClass,engine:Engine,ev:EngineVersion,multiaz:MultiAZ,storage:AllocatedStorage,st:StorageType,iops:Iops,pi:PerformanceInsightsEnabled,dbrid:DbiResourceId,status:DBInstanceStatus}' \
  --output json > $IV/rds.json

aws elasticache describe-cache-clusters --region $R --show-cache-node-info \
  --query 'CacheClusters[].{id:CacheClusterId,type:CacheNodeType,engine:Engine,ev:EngineVersion,nodes:NumCacheNodes,rg:ReplicationGroupId,status:CacheClusterStatus}' \
  --output json > $IV/elasticache.json

aws kafka list-clusters-v2 --region $R \
  --query 'ClusterInfoList[].{id:ClusterName,arn:ClusterArn,type:Provisioned.BrokerNodeGroupInfo.InstanceType,brokers:Provisioned.NumberOfBrokerNodes,mon:Provisioned.EnhancedMonitoring,vol:Provisioned.BrokerNodeGroupInfo.StorageInfo.EbsStorageInfo.VolumeSize,state:State}' \
  --output json > $IV/msk.json

aws eks list-clusters --region $R --query 'clusters' --output json > $IV/eks-names.json
```

### §1.1 五个步骤、六份派生清单（采集前必须先生成）

（**步骤数不等于文件数**：④ 一步产出 `ec2-standalone.json` 与 `ec2-eksnodes.json`
两份。原来这个标题写「五个派生清单」，按它去数文件会漏掉一份，
而漏的恰好是喂 `§4` 的那一份。）

```bash
# ① RDS: 排除 db.serverless（Aurora Serverless v2 按 ACU 伸缩，无固定规格）
jq -c '[.[]|select(.type!="db.serverless")]' $IV/rds.json > $IV/rds-eval.json

# ② ELB: CloudWatch 维度值不是 ARN 全串，是 ARN 中 loadbalancer/ 之后的部分
#    形如 app/<name>/<hash>。用 ARN 全串会返回空序列且不报错。
jq -c '[.[]|{id:(.arn|split("loadbalancer/")[1]), name:.id, type:.type}]' \
  $IV/elb.json > $IV/elb-cwdim.json

# ③ EC2: 只有 T 系列有信用指标，单独一批，避免给非 T 实例产生大量空序列噪音
#    （空序列会掩盖真正的维度错误）
jq -c '[.[]|select(.type|test("^t[0-9]"))]' $IV/ec2.json > $IV/ec2-burstable.json

# ④ EC2 按归属拆成互补的两份：独立机进 solver，EKS 节点不进（见 §4 与 §7.3 ①）。
#    前置：先跑 §4 里生成 ec2-eks-owned.json 的那条 describe-instances。
#    它只读实例标签、不碰 EKS API，可以在这里提前跑。
EKS=$(jq -c '[.[]|select(.ng!=null or .np!=null)|.id]' $IV/ec2-eks-owned.json)
jq -c --argjson e "$EKS" '[.[]|select(.id as $i|($e|index($i))|not)]' $IV/ec2.json > $IV/ec2-standalone.json
jq -c --argjson e "$EKS" '[.[]|select(.id as $i|($e|index($i)))]'      $IV/ec2.json > $IV/ec2-eksnodes.json

# 闭合断言：两份互补且无交集，否则说明标签查询与主清单不是同一时刻的快照
[ "$(( $(jq length $IV/ec2-standalone.json) + $(jq length $IV/ec2-eksnodes.json) ))" \
  = "$(jq length $IV/ec2.json)" ] || echo "FAIL: 拆分未闭合"

# ⑤ MSK: broker_ids 必须来自 list-nodes，**不得由 brokers 计数生成 1..N**
#    （理由见 mdq-msk.jq 文件头：ID 不保证连续，而维度值错了 get-metric-data
#     返回空且不报错）。两处实测处理：BrokerId 是浮点（`1.0`/`2.0`）故 awk 取整；
#     list-nodes 不保证有序（实测某 3-broker 集群返回 `2 1 3`）故 sort -n。
jq -r '.[]|select(.state=="ACTIVE")|[.id,.arn]|@tsv' $IV/msk.json |
while IFS=$'\t' read -r NAME ARN; do
  aws kafka list-nodes --region $R --cluster-arn "$ARN" \
    --query 'NodeInfoList[].BrokerNodeInfo.BrokerId' --output text \
  | tr '\t' '\n' | awk '{printf "%d\n", $1}' | sort -n \
  | jq -R 'tonumber' | jq -s --arg id "$NAME" '{id:$id, broker_ids:.}'
done | jq -s -c . > $IV/msk-nodes.json

jq -c --slurpfile n $IV/msk-nodes.json '
  ($n[0]|INDEX(.id)) as $m
  | [ .[] | . + {broker_ids: $m[.id].broker_ids} ]
  | map(select((.broker_ids|type)=="array" and (.broker_ids|length)>0))' \
  $IV/msk.json > $IV/msk-eval.json

# 闭合断言：ACTIVE 集群数须等于 msk-eval.json 条数，否则打印缺 broker_ids 的集群
[ "$(jq '[.[]|select(.state=="ACTIVE")]|length' $IV/msk.json)" \
  = "$(jq length $IV/msk-eval.json)" ] \
  || jq -r --slurpfile e $IV/msk-eval.json \
       '[.[]|select(.state=="ACTIVE")|.id] - [$e[0][].id]
        | "FAIL: 这些 ACTIVE 集群没取到 broker_ids，不得继续采集: \(.)"' $IV/msk.json
```

**④ 的两份是给不同下游用的，不是同一份的两种视图。** `ec2-standalone.json` 是
`§7.2` 组装 `solver-in.json` 的**唯一**输入；`ec2-eksnodes.json` 只喂 `§4` 的节点池
分析。指标采集（`§2.1` / `§2.2`）仍用完整的 `ec2.json`——节点的 CPU/内存序列
是节点池预订率的依据，不采会让 `§4` 没数据。

实测（验证 region us-west-2，一个 1 托管 nodegroup 的集群）：
`ec2.json` **18** 台 = `ec2-standalone.json` **13** 台 + `ec2-eksnodes.json` **5** 台
（5 台全是 `m5.large`，同一 nodegroup），交集 0，闭合断言通过。

**⑤ 是 fail-closed 的：`msk-eval.json` 是 `§2.5` 的唯一输入，取不到 `broker_ids`
的集群不进采集，而不是退化成按 `brokers` 计数生成 1..N。** `mdq-msk.jq` 自己也再
挡一次（缺 `broker_ids` 直接 `error`，退出码非 0），所以漏跑 ⑤ 会硬失败而不是
静默产出错维度。实测两条路径（验证 region us-west-2，一个 3-broker 集群）：
喂 `msk-eval.json` 出 **48** 个 query（3 broker × 2 stat × 8 项，含 2 项
`ReturnData:false` 的被加数）；把 `msk.json` 直接喂进去 ⇒
`jq: error ... 缺 broker_ids ... ["<集群名>"]`、退出码 **5**。

**只取 `state=="ACTIVE"` 的集群。** 非 ACTIVE 的集群 broker 集合本身不稳定
（正在创建 / 更新 / 删除），取到的 ID 没有采集价值。**非 ACTIVE 分支未实测**——
两个验证 region 的样本集群都是 ACTIVE；若遇到非 ACTIVE 集群，闭合断言会把它
报成"没取到 broker_ids"，按缺口处理即可。

## §2 GetMetricData 采集

### §2.0 通则（五条，每条都踩过）

**① 窗口必须对齐到业务本地午夜（按天对齐，不是"现在往前推 30 天"）。**
`Period=3600` 的桶边界对齐到 `StartTime`，**不对齐自然小时**。直接用
`date -u -v-30d`（带当前分秒）会让桶落在 `:22`、`:55` 之类的位置，5 分钟粒度的原始点
被切进不同的小时桶，再被 `agg.jq` 归入不同时段档。

```bash
# 窗口 = 过去 WINDOW_DAYS 个「完整业务日」，终点是今天的业务本地 00:00
TZ_OFFSET=28800            # 业务时区偏移秒数，UTC+8
NOW=$(date -u +%s)
END=$(( (NOW + TZ_OFFSET) / 86400 * 86400 - TZ_OFFSET ))   # 今日业务本地 00:00 的 UTC 时刻
START=$(( END - WINDOW_DAYS * 86400 ))
SS=$(date -u -r $START +%Y-%m-%dT%H:%M:%SZ)   # GNU date: date -u -d @$START
EE=$(date -u -r $END   +%Y-%m-%dT%H:%M:%SZ)
```

实测输出（UTC+8，30 天）：UTC `2026-08-03T16:00:00Z .. 2026-09-02T16:00:00Z`
= 本地 `2026-08-04T00:00+08 .. 2026-09-03T00:00+08`，恰好 30 个完整业务日。

**按天对齐比按整小时对齐强三点**：

- **整个业务日内重跑得到同一窗口** ⇒ 结果可复现、可审计。整小时对齐只在同一小时内可复现。
- **桶边界从本地午夜起步长 3600s ⇒ 全部落在业务本地整点**，`bucket()` 用的
  `%H` 判档因此精确。这一点对**非整小时偏移的时区同样成立**：UTC+5:30 时
  `END` 落在 UTC `18:30`，本地正是 `00:00`，桶边界仍是本地整点。
  （若只对齐 UTC 整小时，UTC+5:30 的桶会落在本地 `:30`，时段边界系统性偏移半小时。）
- **时段点数变成可预测的整数**，见 §3 的闭合不变式。

代价：**排除当天未走完的部分日**（最多 24 小时的最新数据）。这正是可复现性的来源。
需要包含最新几小时时另行显式指定 `EE`，但那一次的结果不可复现，须在报告注明。

未对齐的实测后果（验证 region ap-northeast-1，同一实例同一 30 天跨度，仅起点分秒不同）：

| 窗口起点 | 该实例 biz-hours `peak_cpu` |
|---|---|
| 本地午夜对齐 | **18.18%** |
| `:22` | 18.18% |
| `:55` | **10.59%** |

另一台实例同样条件下 `11.72%` → `3.86%`。**峰值决定 `required_vcpu`，
1.7–3 倍的摆动足以改变降配结论。**

**② 必须分批提交，且合并后断言无重复 Label。** 单次上限 500 个 query
**且 100,800 个数据点**；30 天 × `period=3600` ⇒ **720** 点/序列（**`EndTime` 排他**，`(END-START)/3600 = 720`）⇒
`floor(100800/720) = 140` 个序列。超限时 API 不报错，而是返回部分数据 + `NextToken`，
CLI 自动翻页并把各页结果**首尾拼接**，同一 Label 出现多次、每次只带一段时间。

实测（189 序列 × 720 点 = 136,080）：`results=378 / 唯一 Label=189 / 重复 Label=189`，
一条 CPU 序列被拆成 `n=534` 与 `n=187` 两段。后果是**静默数据损坏**：
`agg.jq` 每键产出两行、各自 p95 只基于片段；§7 的组装式按
`(指标, stat, bucket)` 建键，`from_entries` 遇到重复键**只留其中一段**——
那次的两段是 534 点与 187 点，留前者用了 74% 的数据、留后者只用 26%，
两种都不对；而聚合层那四项不变式检查**全部照样通过**。

（那次实测是在 `NetworkIn` 等四个 Sum 语义指标仍取 `Average`+`Maximum` 时做的，
故序列数比现在的 §2.1 模板多。现行模板的序列数见 §2.1 末尾。）

**提交要求（自己实现，无附带脚本）：**

1. 按 `batch = floor(100800 / 每序列点数)` 切片，30 天 `period=3600` 时为 **139**。
   逐批 `get-metric-data`，各批输出用 `jq -s '{MetricDataResults:(map(.MetricDataResults)|add),
   Messages:(map(.Messages // [])|add)}'` 合并。
2. **合并后必须断言重复 Label 数为 0**，不为 0 即减小 batch 重跑：

```bash
jq '[.MetricDataResults[].Label] | group_by(.) | map(select(length>1)) | length' raw-out.json
# 必须为 0；>0 说明仍超数据点上限，序列被拆段拼接
```

3. 同时打印下列四项自查，任一异常都要先查清再往下走：

```bash
jq '{requested_hint:"与 mdq.json 中 ReturnData != false 的条数比对（见下）",
     results:(.MetricDataResults|length),
     uniq_label:([.MetricDataResults[].Label]|unique|length),
     nonempty:([.MetricDataResults[]|select((.Timestamps|length)>0)]|length),
     max_points:([.MetricDataResults[]|(.Timestamps|length)]|max),
     messages:.Messages}' raw-out.json
```

**分母不是 `mdq.json` 的长度。** metric math 的被加数标了 `ReturnData: false`，
不回传序列。`mdq-msk.jq` 里 `CpuUser`/`CpuSystem` 就是这种——实测 MSK 32 个 query
只回 24 条结果，属正常。正确分母：

```bash
jq '[.[] | select(.ReturnData != false)] | length' mdq-msk.json
```

`results != uniq_label` ⇒ 有拆段；`nonempty == 0` ⇒ **优先怀疑维度名/维度值写错**
（该失效模式同样不报错）；`max_points` 应等于窗口应有点数（30 天 period=3600 为 **720**）。

**③ Label 必须三段** `"<rid>@<metric>|<type>|<stat>"`。`agg.jq` 按 `|` split 成
`[rid, itype, stat]`；给四段会让 `stat` 被指标名占掉，`Average`/`Maximum` 的区分全丢。
指标名编进第一段用 `@` 分隔，聚合后再 `split("@")` 拆出来。

**④ 空序列是最危险的失效模式：不报错。** 维度名或维度值写错时
`get-metric-data` 与 `list-metrics` 都只返回空，症状看起来像"该 region 没有这类资源"。
所以每次采集后必须打印非空序列数，且按下表判别：

| 现象 | 判别 | 处理 |
|---|---|---|
| 该 namespace **全部**序列为空 | 高度可疑是模板错（维度名/维度值/namespace 写错） | 用 `list-metrics --dimensions` 单点验证维度名 |
| 部分空、兄弟序列非空 | 很可能是**真实缺失** | 用 `list-metrics --metric-name X --dimensions ...` 确认该资源是否发布过该指标 |

实测判别范例：

```bash
# 维度名写错 -> 返回 []，无报错
aws cloudwatch list-metrics --region $R --namespace AWS/Kafka --metric-name CpuUser \
  --dimensions Name=ClusterName,Value=<cluster> --output json | jq -c '.Metrics'   # => []
# 正确写法（维度名带空格）
aws cloudwatch list-metrics --region $R --namespace AWS/Kafka --metric-name CpuUser \
  --dimensions "Name=Cluster Name,Value=<cluster>" --output json | jq -c '.Metrics'
```

**真实缺失的三个已实测例子**（都不是 bug，须在报告缺口里写明）：

| 空序列 | 真实原因 |
|---|---|
| RDS `DBLoad` / `CPUCreditBalance` / `CPUSurplusCreditsCharged` 对某实例为空 | 该实例未开 Performance Insights；或该实例类非 burstable，本就无信用指标 |
| MSK `RequestHandlerAvgIdlePercent` 全 broker 为空 | `EnhancedMonitoring=DEFAULT`（见 §2.5） |
| ALB `RequestCount` 整条序列不存在 | 该 LB 在**近期**零请求，指标停止发布。**这不足以判定闲置**——实测一个 `RequestCount` 序列不存在的 ALB，其 `ActiveConnectionCount` max 为 84（一直有连接）。判定须按 §2.6 的三态表，两个指标一起看 |

**`list-metrics` 与 `get-metric-data` 的时间窗不是同一个。**
`list-metrics` 只列出**最近 2 周**有数据点的指标，而 `get-metric-data`
覆盖你给的整个窗口。所以两者对同一个指标可以给出相反的答案：

实测（验证 region us-west-2，某 ALB，30 天窗口）：

```
list-metrics --namespace AWS/ApplicationELB --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=<该 LB>   =>  .Metrics 长度 0
get-metric-data 同一维度 Stat=Sum 30 天           =>  250 个点，全部非零，单小时 max 1646
                                    点的时间跨度  =>  2026-08-05 .. 2026-08-15（业务本地）
```

最新那个点距查询日（2026-09-04）**20 天**，正好落在 `list-metrics` 的 2 周窗口之外
——所以 `list-metrics` 回空，而这条序列在 30 天窗口里有四分之一的时间是活跃的。

两个后果，方向相反，都致命：

- **把「3 周前有流量、近 2 周没有」误判成「模板写错」**，进而去改一个本来正确的模板。
- 反过来，若只用 `list-metrics` 判「指标存在吗」，会把**仍有历史流量的活跃资源**
  判成从未发布该指标 ⇒ 闲置 ⇒ 建议删除。

所以：**`list-metrics` 回空不能直接当「真实缺失」。** 它只能用于本节上表那个用途
——在 `get-metric-data` **也**回空时，用它交叉核对维度名写法。
判「这个资源到底有没有数据」的唯一依据是 `get-metric-data` 在目标窗口上的回包。

**⑤ 每指标只取 `Average` 与 `Maximum`。** 不取 CloudWatch 的 `p95` stat——那是每小时内的
p95，跨小时聚合无意义。**两类例外**：

- 下限型判据的指标须**额外加** `Minimum`（RDS `FreeableMemory`、
  `FreeStorageSpace`、`CPUCreditBalance`），否则 `agg.jq` 算出的 `min`
  只是"每小时均值的最小值"，仍高于真实低点。
- **计数类（Sum 语义）指标只取 `Sum`，`Average`/`Maximum` 都不取**：
  EC2 的 `NetworkIn`/`NetworkOut`/`EBSReadBytes`/`EBSWriteBytes`（见 §2.1、§7.1）
  与 ALB 的 `RequestCount`/`ActiveConnectionCount`（见 §2.6）。
  这类指标的 `Maximum` 是"单个发布间隔内的最大值"，实测在 ALB 上恒为 0 或 1，
  完全没有判别力。

---

### §2.1 EC2 — `AWS/EC2`，维度 `InstanceId`

```bash
jq -c --argjson metrics '[
  {"ns":"AWS/EC2","mn":"CPUUtilization","dim":"InstanceId"},
  {"ns":"AWS/EC2","mn":"NetworkIn","dim":"InstanceId","stats":["Sum"]},
  {"ns":"AWS/EC2","mn":"NetworkOut","dim":"InstanceId","stats":["Sum"]},
  {"ns":"AWS/EC2","mn":"EBSReadBytes","dim":"InstanceId","stats":["Sum"]},
  {"ns":"AWS/EC2","mn":"EBSWriteBytes","dim":"InstanceId","stats":["Sum"]}]' \
  --arg idkey id --arg typekey type \
  -f $S/references/mdq-multi.jq $IV/ec2.json > $M/mdq-ec2.json

# T 系列信用指标单独一批；Id 加前缀避免与上一批冲突
jq -c --argjson metrics '[
  {"ns":"AWS/EC2","mn":"CPUSurplusCreditsCharged","dim":"InstanceId","stats":["Maximum"]},
  {"ns":"AWS/EC2","mn":"CPUCreditBalance","dim":"InstanceId","stats":["Average","Minimum"]}]' \
  --arg idkey id --arg typekey type \
  -f $S/references/mdq-multi.jq $IV/ec2-burstable.json \
  | jq -c '[.[]|.Id="b"+.Id]' > $M/mdq-ec2-credits.json

jq -s -c 'add' $M/mdq-ec2.json $M/mdq-ec2-credits.json > $M/mdq-ec2-all.json
# 按 §2 的「提交要求」分批提交 $M/mdq-ec2-all.json → $M/raw-ec2.json，并跑重复 Label 断言
```

**四个 Sum 语义指标必须显式 `"stats":["Sum"]`**（`NetworkIn` / `NetworkOut` /
`EBSReadBytes` / `EBSWriteBytes`）。`mdq-multi.jq` 的默认是 `Average`+`Maximum`，
默认值对这四个指标是错的：它们是"每发布粒度的累计字节数"，取 `Average` 后必须乘一个
取决于 SampleCount 的系数才能还原，本 skill 在这个系数上错过三次。取 `Sum` 后
Σ Sum 就是窗口内总字节数，零换算假设（见 §7.1）。**只取 `Sum`，不取 `Average`/`Maximum`**
——`ebs_need` 与 `net_mb_day` 都只需要总量。

实测序列数（用上面这份模板重新生成并计数，两个验证 region 的真实清单）：

| 机队 | 序列数 | 是否触发分批（上限 139） |
|---|---|---|
| 13 台 running + 1 台 T（ap-northeast-1） | **81** | 否 |
| 18 台 running + 3 台 T（us-west-2） | **117** | 否 |

（同样两个机队在四个 Sum 语义指标还取 `Average`+`Maximum` 时是 133 与 189，
后者正是 §2.0 ② 里触发分页拼接损坏的那次。改成只取 `Sum` 后序列数降了约 40%，
但**分批与重复 Label 断言仍然不可省**——机队更大时照样会超限。）

### §2.2 EC2 内存 / 磁盘 — `CWAgent`

**维度组合必须从 `list-metrics` 原样搬，不要硬编码。** 实测同一账号内不同实例的
`mem_used_percent` 维度集**不一致**：一台是 `[ImageId, InstanceId, InstanceType]`，
另一台只有 `[InstanceId]`。维度集取决于 agent 的 `append_dimensions` 配置，逐实例而异；
按固定三维度拼会让只发布 `InstanceId` 的那台返回空序列。

```bash
aws cloudwatch list-metrics --region $R --namespace CWAgent \
  --metric-name mem_used_percent  --output json > $M/lm-cwagent-mem.json
aws cloudwatch list-metrics --region $R --namespace CWAgent \
  --metric-name disk_used_percent --output json > $M/lm-cwagent-disk.json

# 确认本账号实际有哪几种维度组合
jq -c '[.Metrics[]|[.Dimensions[].Name]|sort]|unique' $M/lm-cwagent-mem.json

TY=$(jq -c '[.[]|{key:.id,value:.type}]|from_entries' $IV/ec2.json)

# 内存：idprefix = m
jq -c --arg mn mem_used_percent --arg idname InstanceId --argjson ty "$TY" \
   --argjson stats '["Average","Maximum"]' --arg idprefix m \
   -f $S/references/mdq-dims.jq $M/lm-cwagent-mem.json > $M/mdq-mem.json

# 磁盘：idprefix = d（**必须与内存那批不同**）
jq -c --arg mn disk_used_percent --arg idname InstanceId --argjson ty "$TY" \
   --argjson stats '["Average","Maximum"]' --arg idprefix d \
   -f $S/references/mdq-dims.jq $M/lm-cwagent-disk.json > $M/mdq-disk.json

# 合并后立刻断言 Id 无重复（不是 Label——Id 撞名会让整个调用失败）
jq -s -c 'add' $M/mdq-mem.json $M/mdq-disk.json > $M/mdq-cwagent.json
jq '[.[].Id]|group_by(.)|map(select(length>1))|length' $M/mdq-cwagent.json   # 须为 0
# 按 §2 的「提交要求」分批提交 $M/mdq-cwagent.json → $M/raw-mem.json，并跑重复 Label 断言
```

**`mdq-dims.jq` 的五个参数全部必传，`--arg idprefix` 也在内。** 漏传任何一个
都不是"取到 null"，而是 jq **编译期直接死**——实测原始报错：

```
jq: error: $idprefix is not defined at <top-level>, ...
jq: 1 compile error
```

**两批必须用不同前缀。** `mdq-dims.jq` 的 Id 形如 `<prefix><index>_<stat>`，
两批各自从 0 编号；同前缀合并后 Id 撞名，`get-metric-data` 直接报错——
**这是本 skill 唯一会硬失败的错**，其余失效模式都是静默的。
实测（同一批 mem 4 个 query + disk 54 个 query，两批都传 `m`）：重复 Id **4 个**，
提交时原样回：

```
An error occurred (ValidationError) when calling the GetMetricData operation:
The values for parameter id in MetricDataQueries are not unique.
```

改成 `m` / `d` 后同样两批合计 **58** 个 query、重复 Id **0**、唯一 Label **58**，
提交正常返回。

磁盘的维度比内存多 `device` / `fstype` / `path`，`mdq-dims.jq` 照样原样搬，
但一个实例会有多条（每挂载点一条），判断卷是否过大时须先按 `path` 选出目标文件系统。
实测同一 region 18 台 running 里内存只有 2 台发布、磁盘 27 条序列，
所以两批的 query 数差一个数量级是正常的。

### §2.3 RDS — `AWS/RDS`，维度 `DBInstanceIdentifier`

**已于 2026-09-03 在 us-west-2 首次实测跑通**（2 个 MySQL Multi-AZ 实例 + 1 个
Aurora Serverless v2，后者按规则排除）。维度名与指标名与文档一致。

```bash
jq -c --argjson metrics '[
  {"ns":"AWS/RDS","mn":"CPUUtilization","dim":"DBInstanceIdentifier"},
  {"ns":"AWS/RDS","mn":"DBLoad","dim":"DBInstanceIdentifier"},
  {"ns":"AWS/RDS","mn":"FreeableMemory","dim":"DBInstanceIdentifier","stats":["Average","Maximum","Minimum"]},
  {"ns":"AWS/RDS","mn":"FreeStorageSpace","dim":"DBInstanceIdentifier","stats":["Average","Minimum"]},
  {"ns":"AWS/RDS","mn":"CPUCreditBalance","dim":"DBInstanceIdentifier","stats":["Average","Minimum"]},
  {"ns":"AWS/RDS","mn":"CPUSurplusCreditsCharged","dim":"DBInstanceIdentifier","stats":["Maximum"]},
  {"ns":"AWS/RDS","mn":"DatabaseConnections","dim":"DBInstanceIdentifier"},
  {"ns":"AWS/RDS","mn":"ReadIOPS","dim":"DBInstanceIdentifier"},
  {"ns":"AWS/RDS","mn":"WriteIOPS","dim":"DBInstanceIdentifier"}]' \
  --arg idkey id --arg typekey type \
  -f $S/references/mdq-multi.jq $IV/rds-eval.json > $M/mdq-rds.json
# 按 §2 的「提交要求」分批提交 $M/mdq-rds.json → $M/raw-rds.json，并跑重复 Label 断言
```

三件实测要点：

- **`DBLoad` 只在开了 Performance Insights 的实例上存在。** 未开的实例这两条序列为空
  （不是 bug）。用 `describe-db-instances` 的 `PerformanceInsightsEnabled` 预判，
  未开则该实例失去第一判据，`confidence` 降 `medium` 并写进报告缺口。
- **`FreeableMemory` 必须取 `Minimum`。** 阻断判据是"窗口最小值 < 实例内存 15%"，
  用 `Average` 的 p95 或 `Maximum` 都会反向误判（空闲内存越多越安全，取错方向 =
  把危险实例判成安全）。加了 `Minimum` 后可直接从 `summary` 的 `min` 列读。
- **burstable 实例类（`db.t*`）的信用指标同样适用，且优先级高于 `DBLoad`。**
  实测某 `db.t4g.medium`：`DBLoad` p95 = 0.547 < 0.5×2vCPU **满足降配前置**，
  但 `CPUCreditBalance` 窗口最小值 = **0**（上限 576）、`CPUSurplusCreditsCharged`
  **窗口内单小时最大 = 730.6**（采 `Maximum`，不是窗口累计）⇒ 当前规格已不足，是升配候选。
  **`CPUSurplusCreditsCharged > 0` 必须作为独立否决项，不能只看 `DBLoad`。**

`FreeableMemory` 的多维度组合：实测该 namespace 还发布 `DatabaseClass` /
`EngineName` / `DBClusterIdentifier` / `Role` 等聚合维度。**只用
`DBInstanceIdentifier` 单维度**，否则会把集群级聚合序列混进来重复计数。

### §2.4 ElastiCache — `AWS/ElastiCache`，维度 `CacheClusterId`

**已于 2026-09-03 在 us-west-2 首次实测跑通**（一个 2 shard × 3 node 的 Redis 复制组
+ 一个单节点）。维度名与指标名与文档一致。

```bash
jq -c --argjson metrics '[
  {"ns":"AWS/ElastiCache","mn":"EngineCPUUtilization","dim":"CacheClusterId"},
  {"ns":"AWS/ElastiCache","mn":"DatabaseMemoryUsagePercentage","dim":"CacheClusterId"},
  {"ns":"AWS/ElastiCache","mn":"BytesUsedForCache","dim":"CacheClusterId"},
  {"ns":"AWS/ElastiCache","mn":"Evictions","dim":"CacheClusterId","stats":["Sum","Maximum"]},
  {"ns":"AWS/ElastiCache","mn":"ReplicationLag","dim":"CacheClusterId","stats":["Average","Maximum"]},
  {"ns":"AWS/ElastiCache","mn":"CPUCreditBalance","dim":"CacheClusterId","stats":["Average","Minimum"]},
  {"ns":"AWS/ElastiCache","mn":"CurrConnections","dim":"CacheClusterId"},
  {"ns":"AWS/ElastiCache","mn":"CurrItems","dim":"CacheClusterId","stats":["Maximum"]}]' \
  --arg idkey id --arg typekey type \
  -f $S/references/mdq-multi.jq $IV/elasticache.json > $M/mdq-elasticache.json
# 按 §2 的「提交要求」分批提交 $M/mdq-elasticache.json → $M/raw-elasticache.json，并跑重复 Label 断言
```

实测要点：

- **只用 `CacheClusterId` 单维度。** 该 namespace 同时发布
  `{CacheClusterId, CacheNodeId}`、`{ReplicationGroupId}`、`{NodeGroupId, ReplicationGroupId}`、
  `{Role, ReplicationGroupId}` 等组合。混用会重复计数，且 `Role=Primary/Replica`
  的聚合序列无法映射回具体节点。
- **刻度实测确认**：`EngineCPUUtilization` 与 `DatabaseMemoryUsagePercentage` 都是
  **0–100**（实测 max 0.40–0.45 与 0.436–0.445，即百分之零点四）；
  `ReplicationLag` 单位是**秒**（实测 max 0–0.009）；`Evictions` 是计数。

  **两个指标各多采一个 stat，供否决项判持续态用**：`ReplicationLag` 是 gauge
  ⇒ 加 `Average`，持续值取其 `full-window` 档 p95；`Evictions` 是计数类
  ⇒ 加 `Sum`（**不是 `Average`**——计数类取 `Average` 需要换算系数，本 skill
  在那个系数上错过三次），持续值取小时 `Sum` 的 `full-window` p95，
  它直接回答「有超过 5% 的小时发生过驱逐吗」。
  `Maximum` 仍要采：它是写进 `blockers` 的尖峰值，让维护事件保持可见。
- **`CPUCreditBalance` 上限反推 baseline 与 `baseline-pct.json` 吻合**：
  `cache.t3.medium` 实测上限 **576** = `2 vCPU × 0.20 × 1440`；
  `cache.t4g.micro` 实测 **288** = `2 × 0.10 × 1440`。该表的运行时自校验（见
  `instance-specs.md`）在 ElastiCache 侧同样成立，可用来交叉验证 baseline 表未过期。

### §2.5 MSK — `AWS/Kafka`

**已实测两个集群**（验证 region ap-northeast-1 与 us-west-2），覆盖
`EnhancedMonitoring` 的 `DEFAULT` 与 `PER_TOPIC_PER_PARTITION` 两档。

```bash
# 输入是 §1.1 ⑤ 的 msk-eval.json（带 broker_ids），**不是 msk.json**
jq -c -f $S/references/mdq-msk.jq $IV/msk-eval.json > $M/mdq-msk.json
# 按 §2 的「提交要求」分批提交 $M/mdq-msk.json → $M/raw-msk.json，并跑重复 Label 断言
```

`mdq-msk.jq` 内置三件 MSK 专有处理，逐 broker 展开（`Broker ID` 逐个取自
`broker_ids`，**不得由 `NumberOfBrokerNodes` 生成 1..N**，理由见 §1.1 ⑤）：

1. **维度名带空格**：`Cluster Name`、`Broker ID`。写成 `ClusterName` 返回空且不报错。
2. **CPU 用 metric math** `Expression: "m1+m2"` 逐点相加 `CpuUser + CpuSystem`，
   被加数 `ReturnData: false`。分别聚合再相加是错的（两序列 p95 之和 ≠ 和的 p95）。
   合成序列的 Label 用 `CpuUserPlusSystem`。
3. **同 namespace 内刻度不统一**（见 `thresholds.md`）。

**`EnhancedMonitoring` 的实测边界比原文档精确**：

| 指标 | `DEFAULT` | `PER_TOPIC_PER_PARTITION` |
|---|---|---|
| `CpuUser` / `CpuSystem` | ✅ per-broker 有 | ✅ |
| `KafkaDataLogsDiskUsed` | ✅ per-broker 有 | ✅ |
| `UnderReplicatedPartitions` | ✅ per-broker 有 | ✅ |
| `MemoryUsed` / `BytesInPerSec` | ✅ per-broker 有 | ✅ |
| **`RequestHandlerAvgIdlePercent`** | ❌ **不发布** | ✅（实测 0.999–1.002） |

即 `DEFAULT` 并非"只能出粗结论"——CPU / 磁盘 / URP 判据全都能算，
**唯一缺的是 `RequestHandlerAvgIdlePercent`**。该指标是降配前置条件，缺失
⇒ 不产出降配建议；**只有在同形态下确实存在更便宜的候选机型时**，
报告缺口才写"需把 `EnhancedMonitoring` 提到 `PER_BROKER` 并再等一个窗口"。

**但这条缺口不是无条件写的。** `core.py` 的 `eval_msk` 先查同形态下**有没有更便宜的
候选机型**（`cheaper_candidate_exists`），没有则直接判「已合理配置」、
**不再要求任何前置指标**。实测 `kafka.t3.small` 是两个 region 最便宜的 broker 机型
（次便宜的贵约 4.5 倍），而本账号 `DEFAULT` 监控的那个集群正是这种情况——
对它写这条缺口等于让客户改配置、再白等一个窗口，做完仍然不会有建议。
所以顺序是：**先看候选集，再谈补指标**（判据顺序见 `core.py` 的 `eval_msk`，
字段契约见 `sample-solve.md`）。

### §2.6 VPC — `AWS/NATGateway` + `AWS/ApplicationELB`

```bash
jq -c --argjson metrics '[
  {"ns":"AWS/NATGateway","mn":"ActiveConnectionCount","dim":"NatGatewayId"},
  {"ns":"AWS/NATGateway","mn":"BytesOutToDestination","dim":"NatGatewayId"}]' \
  --arg idkey id --arg typekey vpc \
  -f $S/references/mdq-multi.jq $IV/nat.json > $M/mdq-nat.json

# ELB 用 §1.1 生成的 elb-cwdim.json（维度值 = ARN 中 loadbalancer/ 之后的部分）
# 两个指标都是**计数类、Sum 语义**，必须显式 "stats":["Sum"]（理由见本节末）
jq -c --argjson metrics '[
  {"ns":"AWS/ApplicationELB","mn":"RequestCount","dim":"LoadBalancer","stats":["Sum"]},
  {"ns":"AWS/ApplicationELB","mn":"ActiveConnectionCount","dim":"LoadBalancer","stats":["Sum"]}]' \
  --arg idkey id --arg typekey name \
  -f $S/references/mdq-multi.jq $IV/elb-cwdim.json \
  | jq -c '[.[]|.Id="e"+.Id]' > $M/mdq-elb.json

jq -s -c 'add' $M/mdq-nat.json $M/mdq-elb.json > $M/mdq-vpc.json
# 按 §2 的「提交要求」分批提交 $M/mdq-vpc.json → $M/raw-vpc.json，并跑重复 Label 断言
```

**必须只带 `LoadBalancer` 单维度。** 实测同一个 ALB 的 `RequestCount` 有 4 种维度组合：
`{LoadBalancer}`、`{LoadBalancer, AvailabilityZone}`、`{LoadBalancer, TargetGroup}`、
`{LoadBalancer, TargetGroup, AvailabilityZone}`。带 `TargetGroup` 或
`AvailabilityZone` 会按目标组/可用区拆成多条序列，判闲置时重复计数。

闲置判据取**全窗口（三档合并）** 的 max，且要连**覆盖度**一起看：

```bash
jq -r --argjson tz $TZ_OFFSET -f $S/references/agg.jq $M/raw-vpc.json > $M/agg-vpc.json
WIN=$(( WINDOW_DAYS * 24 ))     # 全窗口应有点数，与 §3 闭合不变式的 total 同一个数
# **`select(.bucket != "full-window")` 不可省。** agg.jq 除三档外还输出一个
# full-window 行；不排除它，`n` 会被算两遍（实测 465 → 930），覆盖度看起来
# 充足 —— 正是本节警告的「偏松」失效，而这一行的下游动作是删除。
jq -r --argjson win "$WIN" '[.[] | select(.bucket != "full-window")]
       | group_by(.rid + "|" + .stat)[]
       | {k:(.[0].rid + "|" + .[0].stat), n:(map(.n)|add), max:(map(.max)|max)}
       | "\(.k) n=\(.n)/\($win) max=\(.max)"' $M/agg-vpc.json
```

（`agg.jq` 的 `.rid` 是 Label 第一段，形如 `<资源维度值>@<指标名>`，
所以上面这行是**逐资源逐指标逐 stat** 一行，不是逐资源一行。）

**覆盖度门槛查的是三档合计，不是逐档。** `quiet()` 用的 `n` 是三档相加，所以
「某一档整档为空、另两档虚高」这种形状能过门槛（合成验证：`biz-hours=400` +
`off-hours=320`、无 weekend ⇒ 判 `idle`）。固定 30 天窗口下逐档点数各有上限
（242 / 286 / 192），**数据形状正常时**合计达到 `$win` 就已迫使近乎满覆盖；
真正能抓出这种畸形形状的是 **§3 的时段点数闭合不变式**——注意它**不是**只查合计：
`§3` 是**四条等式**（`biz = 工作日数 × 11`、`off = 工作日数 × 13`、
`weekend = 周末天数 × 24`、三者之和 `= WINDOW_DAYS × 24`），且逐档打印
`expect biz=… off=… weekend=…` 与实际比对。上面那个合成形状
（`biz=400 + off=320 + weekend=0`）合计恰好 720、**只有第四条通过**，
前三条各自失败——**它被抓了三遍**。

**别只按名字理解「闭合」二字。** 「闭合」听起来像只校验"加起来等于全体"，
按那个理解会得出「合计对了就放过」的错误结论，进而以为需要另加一项逐档覆盖检查。
不需要：逐档检查已经在 `§3` 里。（此坑实测踩过一次——本节早先有一版就是这么写错的。）
**所以 `§3` 对 VPC 的 agg 同样必做**，不是只对 `summary-ec2.csv` 做
（§3 的示例用的是 EC2 的 `CPUUtilization`/`Average`，那只是示例的口径，不是适用范围）。

**分组键必须带 `.stat`。** `agg.jq` 每 (资源, 指标, stat, 时段) 一行，只按 `.rid`
分组会把多个 stat 的点数**加在一起**：NAT 按 `mdq-multi.jq` 默认采
`Average`+`Maximum` 两个 stat，实测 `n` 于是打印成 `1440/720`——覆盖度看起来
是应有点数的两倍，谁拿它跟 `$win` 比都会得出「覆盖充足」这个**偏松**的结论。
（写这一行时真踩了一次。）

**这一行只报覆盖度与极值，不下结论。** `max == 0` 单独不足以判闲置——`n` 远小于
`$win` 时那些 0 只说明该资源在窗口内没全程存在（新建 / 曾停机），不是「一直没人用」。
ALB/NLB 的完整判定见下一节；`window_profile=full-window` 的行要往
`sample_points` 里填哪个数、不足时怎么落桶，见 `report-template.md`
的 `sample_points` 定义（**全窗口档要求 `sample_points` = 上面的 `$win`**）。

#### ALB / NLB 的闲置判定是三态，不是二态

**本小节是这条判据的唯一真值源。** `thresholds.md` 的闲置判据表、
`report-template.md` 的 `bucket=idle` 说明、`metrics-catalog.md` 的 ELB 小节与
`SKILL.md` 的 VPC 小节**都只留指针、不复述条件**——
判定表与可执行实现必须待在同一屏，否则规则与实现的分歧看不见
（本仓库反复验证：「只有散文描述的判据全部出过问题」）。
这条判据里**没有任何阈值**，它是一台在「指标是否存在 / 取到多少点 / 值是多少」
上跑的状态机，所以它不属于 `thresholds.md`。
**NAT 的判据条件仍留在 `thresholds.md`**（单指标单状态，一格装得下），
但它的**覆盖度门槛与可执行实现在本节**，与 ALB 共用一份 jq——两条路径的动作都是删除，
门槛写两份必然漂移。

**`RequestCount` 一个指标判不了闲置。** 必须与 `ActiveConnectionCount` 一起看。
每个指标先归成三态，**注意「全 0」必须带覆盖度条件**：

| 单指标状态 | 定义 |
|---|---|
| **无活动** | 序列不存在，**或** 序列覆盖整窗口（`n` = 全窗口应有点数 `$win`）且 `max == 0` |
| **有活动** | `max > 0` |
| **覆盖不足** | 序列存在、`max == 0`、但 `n < $win` |

**`n > $win` 不是第四态，是损坏信号。** 满窗口序列的点数**恰好**等于 `$win`，
所以 jq 里写的是 `n >= $win`（宽一格，把浮点/边界问题挡在外面），
但真的取到 `n > $win` 时**不要当成"覆盖更充分"**：它只有两个来源——
序列被分页拼接成两段（§2 的重复 Label 断言就是查这个，**必做**），
或者 `WINDOW_DAYS` 与 `$win` 不是同一个窗口。两种都要先回 §2 查清再往下判，
否则 `quiet()` 会把一份损坏的数据判成"无活动"。

「覆盖不足」是单独一态而不是并进「无活动」：一条只覆盖 3 小时的全 0 序列什么都没证明
（新建 / 曾停机 / 发布中断都长这样），把它当证据就会把一台 3 小时前建的 LB
判成可删除。组合结论：

| `RequestCount` ↓ ＼ `ActiveConnectionCount` → | 无活动 | 覆盖不足 | 有活动 |
|---|---|---|---|
| **无活动** | 桶 B（闲置）※ | 候选，需人工确认 | 候选，需人工确认 |
| **覆盖不足** | 候选，需人工确认 | 候选，需人工确认 | 候选，需人工确认 |
| **有活动** | 活跃，不进桶 B | 活跃，不进桶 B | 活跃，不进桶 B |

※ **唯一例外**：两条序列**都不存在**也落在左上格，但那是 `no-data`
（`metric-missing`），**不进桶 B**，先按 §2.0 ④ 排除模板写错。
「候选，需人工确认」一律**不计入确定节省**。

**为什么「两条都覆盖整窗口且全 0」判闲置，而不是要求连接序列缺失。**
2026-09-04 修此处前，实现要求 `ActiveConnectionCount` **序列不存在**才判闲置，
于是「两个指标都取到、都是全窗口 0」这个证据更强的组合反而落到「候选」——
规则在自己的证据上非单调。真正的失效模式不是假设：若某代 ALB 开始发布 0 值的
`ActiveConnectionCount`，账号里每台真闲置的 LB 都会**静默**离开桶 B，头条金额下跌，
而原始数据在任何要紧的方面都没变。这与本仓库 P7 那条缺陷同形——**结论被指标的
「有没有」而不是「是多少」驱动**。两个 region 六台实测 LB 从未走到这个组合，
所以旧实现那条 `act == null` 不是实测要求，只是当年为贴合 LB ① 写出来的形状。

**实测依据**（2026-09-04 重跑，30 天窗口对齐业务本地午夜，`Stat=Sum`，
`$win = 720`；`n` 一律写成 `实际/应有`）：

| LB | region | `RequestCount` | `ActiveConnectionCount` | 判定 |
|---|---|---|---|---|
| ① | us-west-2 | n=720/720、max 0 | **序列不存在**（`list-metrics` 回 0，`get-metric-data` 回 0 点） | 桶 B |
| ② | us-west-2 | **序列不存在** | n=661/720、max 84 | **候选，需人工确认** |
| ③ | us-west-2 | n=250/720、max 1646 | n=720/720、max 2004 | 活跃 |
| ④ | us-west-2 | n=720/720、max 10397 | n=720/720、max 1035 | 活跃 |
| ⑤ | ap-northeast-1 | n=720/720、max 1195 | n=720/720、max 1336 | 活跃 |
| ⑥ | ap-northeast-1 | n=720/720、max 0 | **序列不存在** | 桶 B |

LB ② 是这条规则的全部理由：只看 `RequestCount` 会把它判成**可删除**，
而它其实一直有连接（大概是健康检查或目标端保持的长连接）。
LB ⑥ 是 LB ① 那个组合在**另一个 region** 的第二个样本（此前只有 n=1）。

**实测到的两个指标发布行为不同，这正是「覆盖不足」必须独立成态的原因**：
`RequestCount` 会把无请求的小时**发布成 0**（LB ①⑥ 都是 720/720 全 0），
而 `ActiveConnectionCount` 在无连接的小时**根本不发点**——LB ② 有连接却只有
661/720 点，缺的 59 点就是零连接的小时。所以：

- 「`ActiveConnectionCount` 存在且全 0」在现行 ALB 上近乎不可观测（本轮两个 region
  6 台 LB 一例都没有），矩阵第一行第一列的**非缺失分支未实测**，是按上面那条
  推理外推的；
- 反过来，一条**部分覆盖**的全 0 连接序列是可能出现的，它落「覆盖不足」⇒ 候选，
  fail-closed。

矩阵里下列格子在这两个 region **未观测到**，均为按同一条推理外推、**未实测**：
「无活动 × 无活动」的双非缺失分支、任何一侧为「覆盖不足」的整行整列、
以及两条序列都不存在的 `no-data`。已实测的是
「无活动 × 序列不存在」（LB ①⑥）、「序列不存在 × 有活动」（LB ②）、
「有活动 × 有活动」（LB ③④⑤）三格。

**NLB 侧一格都未实测**（两个验证 region 无 NLB），见本节末。

**两个指标必须取 `Stat=Sum`。`Maximum` 在这两个指标上恒等于 0 或 1，完全没有判别力。**
实测同样 4 个 ALB 的三种 stat：

| 指标 | 最活跃那个 LB 的 `Sum` max | 同一 LB 的 `Maximum` max | 同一 LB 的 `Average` max |
|---|---|---|---|
| `RequestCount` | 10397 | **1.0** | 0.956 |
| `ActiveConnectionCount` | 1035 | **0.0** | 12.5 |

`ActiveConnectionCount` 的 `Maximum` 在**全部 4 个 LB 上都是 0.0**，
包括每小时上万请求的那个。若照 `mdq-multi.jq` 的默认 `Average`+`Maximum` 采、
再用 `Maximum` 判，矩阵里「有活动」那一态永远不成立，三态会静默塌回二态——
也就是回到本节要修的那个错。（`AWS/NATGateway` 的
`ActiveConnectionCount` **不是**这样，实测 `Maximum` max = 541，
它是真的瞬时连接数；这个坑只在 `AWS/ApplicationELB` 上。）

**这条要求在下面的 jq 里是可执行的，不只是散文**：判定只认 `.stat == "Sum"` 的
agg 行。采成别的 stat 时两个指标都取不到 ⇒ 全部落 `no-data` ⇒ 走 §2.0 ④ 的
排除流程，而不是拿着错 stat 静默算出一批结论。**实测**过这个差别：把同一份
agg 的 `stat` 由 `Sum` 改成 `Average`，旧实现照样吐出
`candidate-manual / active / active / idle`（含一条删除建议），新实现四台全 `no-data`。

**「序列不存在」在 `agg.jq` 的输出里是「没有行」，agg 自己看不出来。**
实测上面 8 条 query 里有 2 条回空，agg 输出直接少两组，
按 agg 遍历会把这两个 LB 整个漏掉。所以判定必须拿 §1.1 的
`elb-cwdim.json`（NAT 用 `nat.json`）做左连接。

**NAT 与 ALB/NLB 共用同一份 jq。** 判据不同（NAT 单指标单状态、ALB 三态）但
**覆盖度门槛是同一条**，而 NAT 那条路径的动作也是删除。两份副本必然漂移，
所以 `quiet()` 与左连接只写一次，用 `$kind` 选路；取哪个 stat 变成参数，
NAT/ALB 的差别因此显式而不是靠记忆：

```bash
cat > $M/vpc-idle.jq <<'JQ'
# VPC 闲置判定（NAT 与 ALB/NLB 共用一份，$kind 选路）。
# $win  = 全窗口应有点数（WINDOW_DAYS × 24，与 §3 闭合不变式的 total 同一个数）。
# $kind = "nat" | "elb"
#
# 「无活动」= 序列不存在，或序列覆盖整窗口且恒为 0。
# 短序列的 0 不算证据（新建 / 曾停机 / 发布中断），否则一个 3 小时的资源会被判可删除。
def quiet($m; $win): $m == null or ($m.n >= $win and $m.max == 0);
($agg[0]) as $A
# 序列"不存在"在 agg 里是**没有行**，所以两条路径都必须拿清单左连接。
# stat 是参数而不是写死：NAT 的 ActiveConnectionCount 是真瞬时值，判据取 Maximum；
# ALB 的两个指标是计数类，Maximum 恒 0/1 没有判别力，判据取 Sum（见上文）。
# 采成别的 stat 时这里取不到序列 ⇒ no-data，而不是拿错 stat 算出结论。
# **必须排除 `full-window` 档再相加。** agg.jq 除三档外还输出一个 full-window
# 行（供否决项的 p95 与下限型的 min 用）；不排除它，`n` 会被算两遍
# （实测 465 → 930），于是覆盖不足的序列看起来满覆盖 ⇒ quiet() 放行 ⇒
# **活跃 LB 被报成可删除**。
# 这里用「排除后相加」而不是「直接读 full-window」，是因为本函数只用 n 与 max，
# 这两个跨三档是精确可合并的；full-window 档的存在理由只是 p95/mean/min
# （并集的 p95 ≠ 各档 p95 的 max），本函数不碰那三个。
| def series($d; $mn; $st):
    ([ $A[] | select(.rid == "\($d)@\($mn)" and .stat == $st
                     and .bucket != "full-window") ]
     | if length == 0 then null else {n:(map(.n)|add), max:(map(.max)|max)} end);
  if $kind == "nat" then
    # NAT 是单指标单状态。但**序列不存在 ≠ 闲置**，所以先判 null 再套 quiet()。
    map(.id as $d
      | { nat: .id, act: series($d; "ActiveConnectionCount"; "Maximum") }
      | .state = (if   .act == null      then "no-data"
                  elif quiet(.act; $win) then "idle"
                  elif .act.max > 0      then "active"
                  else "candidate-manual" end))
  else
    map(.id as $d
      | { lb: .name, type: .type,
          req: series($d; "RequestCount"; "Sum"),
          act: series($d; "ActiveConnectionCount"; "Sum") }
      | .state = (if   quiet(.req; $win) and quiet(.act; $win)
                       and (.req != null or .act != null)      then "idle"
                  elif (.req != null and .req.max > 0)         then "active"
                  elif (.act != null and .act.max > 0)         then "candidate-manual"
                  elif .req == null and .act == null           then "no-data"
                  else "candidate-manual" end))
  end
JQ

jq -r --slurpfile agg $M/agg-vpc.json --argjson win "$WIN" --arg kind elb \
   -f $M/vpc-idle.jq $IV/elb-cwdim.json
jq -r --slurpfile agg $M/agg-vpc.json --argjson win "$WIN" --arg kind nat \
   -f $M/vpc-idle.jq $IV/nat.json
```

**实测（2026-09-04，这段原样跑）**：us-west-2 上表 4 台 LB 得
`candidate-manual` / `active` / `active` / `idle`，ap-northeast-1 上 2 台得
`active` / `idle`——与上面的实测表逐台一致。**加覆盖度门槛后没有任何一台改判**
（同一份 agg 上跑旧实现得到逐字相同的六个结论）：门槛只在 `n < $win` 时才咬，
而这 6 台里唯一 `n < $win` 的序列是 LB ② 的 661/720，它 `max = 84 > 0`，
本来就走「有活动」，不经过门槛。

门槛与新判据都用**实测数据的合成变体**验过（账号里没有能天然触发这两格的资源，
所以只能合成；下面四条是在上面那份真实 agg 上改一处再跑）：

| 合成改动 | 旧实现 | 新实现 |
|---|---|---|
| LB ① 的 `RequestCount` `n` 由 720 改成 3（模拟 3 小时前新建） | `idle`（**这就是要修的洞**） | `candidate-manual` |
| 给 LB ① 补一条 720 点全 0 的 `ActiveConnectionCount`（本轮争议的那格） | `candidate-manual` | `idle` |
| LB ① 去掉 `RequestCount`、补 720 点全 0 的 `ActiveConnectionCount` | `candidate-manual` | `idle` |
| 整份 agg 的 `stat` 由 `Sum` 改成 `Average` | 照旧出四条结论 | 四台全 `no-data` |

**NAT 侧同样实测过（2026-09-04，`$kind=nat` 原样跑）**：us-west-2 的 4 个 NAT 得
`active` / `idle` / `idle` / `active`，ap-northeast-1 的 2 个全 `active`；
6 个 NAT 的 `ActiveConnectionCount`（`Maximum`）都是 **720/720**，
所以**加门槛后同样没有一个改判**。两个闲置 NAT 的 max 恒 0，另外四个
max 分别为 541 / 6 / 25 / 74。NAT 的门槛与「序列不存在 ≠ 闲置」也用合成变体验过：

| 合成改动（对一台已判 `idle` 的 NAT） | 新实现 |
|---|---|
| `ActiveConnectionCount` 的 `n` 由 720 改成 3 | `candidate-manual` |
| 该 NAT 的序列整条删掉（指标从未发布 / 模板写错） | `no-data`（**不是 `idle`**） |
| 整份 agg 的 `stat` 由 `Maximum` 改成 `Average` | 6 个全 `no-data` |

第二行是这条路径此前的第二个洞：NAT 没有左连接，序列不存在的 NAT
**不会被判成闲置，而是整个从输出里消失**——比误判更难发现，因为报告里
不会多出任何一行。

只有 `state == "idle"` 才填 `bucket=idle` 并计入桶 B 的确定节省；
`candidate-manual` 进报告的「需人工确认」清单、**金额不计入合计**；
`no-data` 先按 §2.0 ④ 查模板。这一行怎么填（含 `sample_points` 与
`window_profile` 必须同档）见 `report-template.md`。

NLB 用 `AWS/NetworkELB` + 同样的维度处理；两个验证 region 均无 NLB，**未实测**。
NLB 侧的对应指标是 `ProcessedBytes` / `ActiveFlowCount`（见
`metrics-catalog.md` 的 NLB 小节，同样未实测）——三态矩阵的两列须相应替换，
且**必须先 `list-metrics --namespace AWS/NetworkELB` 校验指标名再采**。
覆盖度门槛与 `quiet()` 不随指标名变，可原样复用。

## §3 时区归一化、时段切档与聚合

```bash
jq -r --argjson tz $TZ_OFFSET -f $S/references/agg.jq $M/raw-<svc>.json > $M/agg-<svc>.json

# 多份 agg（EC2 主指标 + CWAgent 内存）先合并再投影
jq -s 'add' $M/agg-ec2.json $M/agg-mem.json > $M/agg-ec2-all.json

jq -r '(["resource","metric","type","stat","bucket","n","mean","p95","max","min"]|@csv),
       (.[] | [(.rid|split("@")[0]),(.rid|split("@")[1]),.itype,.stat,.bucket,.n,
               (.mean*1000|round/1000),(.p95*1000|round/1000),
               (.max*1000|round/1000),(.min*1000|round/1000)]|@csv)' \
   $M/agg-ec2-all.json > $M/summary-ec2.csv
```

**CSV 列布局固定为 10 列**：
`resource, metric, type, stat, bucket, n, mean, p95, max, min`
（`metric` 由 Label 第一段 `split("@")` 拆出；`min` 由 `agg.jq` 输出，
供 RDS `FreeableMemory` 与信用触底这类下限型判据用）。

**列号即判据，不要凭记忆写 awk。** 本布局下 `n=$6 mean=$7 p95=$8 max=$9 min=$10`。
早期单指标版本是 8 列（无 `metric`、无 `min`），列号整体差 1；沿用旧列号会让
`$5+0==0` 变成"拿 bucket 字符串比 0"从而恒真，产生假告警。

### 必须跑的不变式检查（五项各须为 0，按顺序）

**第 1 项在 raw 层，采集后立即跑；后四项在聚合层。顺序不可颠倒**——
raw 层损坏会让后四项失去意义（实测分页拼接时后四项全部通过）。

```bash
# ① raw 层：重复 Label（分页拼接损坏的唯一可靠信号）
jq '[.MetricDataResults[].Label]|group_by(.)|map(select(length>1))|length' $M/raw-ec2.json

# ②③④⑤ 聚合层
awk -F, 'NR>1{gsub(/"/,""); if($8+0>$9+0)  v++} END{print "p95>max:",  v+0}' $M/summary-ec2.csv
awk -F, 'NR>1{gsub(/"/,""); if($7+0>$9+0)  v++} END{print "mean>max:", v+0}' $M/summary-ec2.csv
awk -F, 'NR>1{gsub(/"/,""); if($6+0==0)    v++} END{print "empty:",    v+0}' $M/summary-ec2.csv
awk -F, 'NR>1{gsub(/"/,""); if($10+0>$7+0) v++} END{print "min>mean:", v+0}' $M/summary-ec2.csv
```

| 项 | 层 | 抓什么 | 不为 0 时 |
|---|---|---|---|
| ① 重复 Label | raw | 分页拼接把同一序列拆段 | 减小 batch 重新采集，**不要往下走** |
| ② p95>max | 聚合 | 分位数计算错 | 查 `agg.jq` 的 `pct` |
| ③ mean>max | 聚合 | 聚合口径错 | 同上 |
| ④ empty | 聚合 | 空桶 | 查时区偏移与切档边界 |
| ⑤ min>mean | 聚合 | Minimum 序列串位 | 查 Label 与 stat 对应关系 |

**②–⑤ 不覆盖分页拼接损坏。** 实测 189 序列被拆段时这四项全部通过，
而判据实际只用了 74% 的数据。所以 ① 不可省，且必须先跑。

聚合层可再确认一次键唯一性作为交叉校验：

```bash
jq '[.[]|"\(.rid)|\(.stat)|\(.bucket)"]|group_by(.)|map(select(length>1))|length' $M/agg-ec2-all.json
# 须为 0
```

### 时段点数闭合不变式（按天对齐后才成立，能抓出错位与分页丢数据）

窗口对齐到业务本地午夜后，每个**满窗口**资源的三档点数是可精确预测的整数：

```
biz-hours   = 工作日数 × 11        (09:00–20:00)
off-hours   = 工作日数 × 13        (00:00–09:00 与 20:00–24:00)
weekend     = 周末天数 × 24
三者之和    = WINDOW_DAYS × 24
full-window = 三者之和             ← agg.jq 另发的一档，**不参与本式的三项比对**
```

```bash
# 实际值。**`$5!="full-window"` 不可省**：agg.jq 除三档外还发一个 full-window 行，
# 不排除它，输出会多出一行 `<rid>|full-window 720`，而下面的预期值只打印三档
# ——一边四项一边三项，operator 要么误报警要么干脆不再信这道检查。
# full-window 自身的闭合（它应恰等于三档之和）单独查，见本节末。
awk -F, 'NR>1{gsub(/"/,"");
              if($4=="Average"&&$2=="CPUUtilization"&&$5!="full-window") s[$1"|"$5]=$6}
         END{for(k in s) print k, s[k]}' $M/summary-ec2.csv | sort
# 预期值
python3 - "$START" "$TZ_OFFSET" "$WINDOW_DAYS" <<'PY'
import sys,datetime
st,tz,n=int(sys.argv[1]),int(sys.argv[2]),int(sys.argv[3])
d0=datetime.datetime.fromtimestamp(st+tz,datetime.UTC).date()
days=[d0+datetime.timedelta(i) for i in range(n)]
wd=sum(1 for d in days if d.isoweekday()<6); we=n-wd
print(f"expect biz={wd*11} off={wd*13} weekend={we*24} total={wd*24+we*24}")
PY
```

实测（UTC+8，30 天窗口含 22 个工作日 + 8 个周末日）：
`biz-hours=242`、`off-hours=286`、`weekend=192`，合计 **720 = 30×24**，完全闭合。

**这条比四项不变式更能抓问题**：分页拼接丢数据、窗口错位、时区偏移写错，
都会让闭合式不成立；而 `p95>max` 那四项在分页损坏时全部照样通过。

**再加一条 full-window 自闭合**（每个 `(rid, stat)` 的 full-window `n` 必须
恰等于该键三档 `n` 之和）。它抓的是 `agg.jq` 那一档自己算错，与上面三项互补：

```bash
jq -r 'group_by(.rid + "|" + .stat)[]
       | (map(select(.bucket == "full-window")) | .[0].n) as $fw
       | (map(select(.bucket != "full-window")) | map(.n) | add) as $sum
       | select($fw != null and $fw != $sum)
       | "\(.[0].rid)|\(.[0].stat) full-window=\($fw) 三档和=\($sum)"' $M/agg-ec2-all.json
# 须无输出
```

### 采样量分档（不是守卫）

`biz-hours` 点数低于 `min_biz_hours_points` ⇒ 该资源**照常产出降配建议**，
但 `confidence=low`、`blockers` 写明样本量与占门限比例。
只有点数为 `0` 或缺失才标 `insufficient-data`——那是「无」不是「少」。
点数低于上面的预期值说明该资源在窗口内并非全程存在（新建 / 曾停机），
属正常，不必修模板。

**这一分档只作用于降配路径。** `is_idle`（动作是删除）与 `is_stop_candidate`
（动作是停机）仍是硬门限：可回滚的动作允许低置信度产出，不可回滚的不允许。

实测触发案例：某 MSK 集群指标历史仅约 26 小时 ⇒ biz-hours 仅 **13–15** 点；
两台新建 EC2 ⇒ **154** 点（19 天）与 **54** 点（6 天）。

## §4 EKS 采集与分析

**已于 2026-09-03 在 us-west-2 首次实测跑通**（1 个 1.31 集群，1 个托管 nodegroup，
5 节点 / 71 pod）。

```bash
C=$(jq -r '.[0]' $IV/eks-names.json)
aws eks describe-cluster --region $R --name "$C" --output json > $IV/eks-cluster.json
aws eks list-nodegroups --region $R --cluster-name "$C" --output json > $IV/eks-ng.json
aws eks describe-nodegroup --region $R --cluster-name "$C" --nodegroup-name <NG> \
  --query 'nodegroup.{it:instanceTypes,scaling:scalingConfig,ami:amiType,cap:capacityType,disk:diskSize,lt:launchTemplate}' \
  --output json > $IV/eks-ng-detail.json
aws eks list-fargate-profiles --region $R --cluster-name "$C" --output json > $IV/eks-fargate.json
aws ec2 describe-instances --region $R \
  --filters "Name=tag:karpenter.sh/nodepool,Values=*" Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{id:InstanceId,type:InstanceType}' \
  --output json > $IV/eks-karpenter.json
```

**节点必须与独立 EC2 分开处理。** 用标签识别，否则会对节点单机出降配建议——
错的，机型由 nodegroup 的 `instanceTypes`（或 Karpenter NodePool）决定：

```bash
aws ec2 describe-instances --region $R --filters Name=instance-state-name,Values=running \
  --query 'Reservations[].Instances[].{id:InstanceId,ng:Tags[?Key==`eks:nodegroup-name`]|[0].Value,np:Tags[?Key==`karpenter.sh/nodepool`]|[0].Value}' \
  --output json > $IV/ec2-eks-owned.json
```

### §4.0 临时 kubeconfig —— 禁止碰本地 `~/.kube/config`

`aws eks update-kubeconfig` **默认写入 `~/.kube/config` 并可能改掉 `current-context`**，
会让 operator 后续的 kubectl 悄悄打到别的集群。只读审计不得有这种副作用。

```bash
KCDIR=$(mktemp -d); KC="$KCDIR/config"
trap 'rm -rf "$KCDIR"' EXIT              # 退出即删，不留残留
aws eks update-kubeconfig --region "$R" --name "$C" --kubeconfig "$KC"
export KUBECONFIG="$KC"                  # 仅当前 shell 生效

kubectl auth can-i list nodes                    # 先探权限，失败就别往下走
kubectl auth can-i list pods --all-namespaces
```

实测验证：本地 `~/.kube/config` 的 md5 前后完全一致，`current-context` 未被改动。

**禁止**：用 `update-kubeconfig` 的默认路径；用 `kubectl config use-context`；
把 `KUBECONFIG` 写进 shell profile。

### §4.0b Container Insights 缺失时仍能算出 4 项结论

**不要因为 `ContainerInsights` 为 0 就跳过 pod 级分析。** 6 项里 4 项是
「配置比配置」，纯 kubectl 即可：

| 分析 | kubectl 够 | 需 Container Insights |
|---|---|---|
| 预订率（requests ÷ allocatable） | ✅ | — |
| bin-packing 理论最少节点数 | ✅ | — |
| 空 nodegroup / 未调度节点 | ✅ | — |
| HPA 配置本身 | ✅ | 判"是否过高"需历史负载 |
| Fargate request 超配 | ✅ | — |
| pod **实际**利用率历史 | — | ✅ 唯一不可替代 |

实测（某集群 `ContainerInsights` = 0 条指标）：

```
节点 allocatable  9.65 vCPU / 34.08 GiB   （5 × m5.large）
pod requests      7.79 vCPU / 11.56 GiB   （71 个 running pod）
CPU 预订率        80.7%
内存预订率        33.9%     ← 差 2.4 倍，机型错配信号明确（该换 c 系列）
```

这个结论零历史指标即可得出。故报告应写「**pod 实际利用率不可得**」，
不是「pod 级分析不可得」——两者影响范围差很远。

### §4.1 节点与 pod 落盘（**原始输出必须留**）

```bash
# 原始 kubectl 输出必须落盘。requests 的正确算法要看 initContainers 与 spec.overhead，
# 在采集时就把容器 sum 掉会把这两项永久丢掉，之后再也算不回来（见 §4.1b）。
kubectl get nodes -o json                 > $IV/k8s-nodes-raw.json
kubectl get pods --all-namespaces -o json > $IV/k8s-pods-raw.json

# 节点侧：只做单位归一化，没有 sum 陷阱，jq 即可
jq '[.items[]|{name:.metadata.name,
  it:.metadata.labels["node.kubernetes.io/instance-type"],
  ng:(.metadata.labels["eks.amazonaws.com/nodegroup"] // "karpenter-or-self"),
  alloc_cpu_m:(.status.allocatable.cpu
    |if test("m$") then (.[:-1]|tonumber) else (tonumber*1000) end),
  alloc_mem_mi:(.status.allocatable.memory
    |if test("Ki$") then (.[:-2]|tonumber)/1024 elif test("Mi$") then (.[:-2]|tonumber)
     elif test("Gi$") then (.[:-2]|tonumber)*1024 else (tonumber/1048576) end)}]' \
  $IV/k8s-nodes-raw.json > $IV/k8s-nodes.json
```

**`ownerkind` 必须取**（在 §4.1b 里产出）。DaemonSet 的 request 是**每节点固定开销**，
会随节点数一起增减；业务 pod 的 request 是总量。两者混在一起算 bin-packing
会系统性高估所需节点数。

### §4.1b pod requests 只能由 `core.py` 的 `pod_requests()` 产出

**不要自己 sum 容器 requests。** K8s 的调度用量是：

```
max(Σ 普通容器, 各 init 容器的最大值) + pod overhead
```

init 容器顺序执行且先于普通容器完成，故**不与普通容器叠加**；但单个 init 容器
可能大于普通容器之和，那时以它为准。overhead 是 RuntimeClass 固定开销，恒叠加。
漏算这两项会**低估 requests**，而预订率是 EKS 分析里唯一不依赖
Container Insights 的核心结论，低估会直接推出错误的机型建议。

下面这段就是 §4.2 / §4.3 消费的 `$IV/k8s-pods.json`，字段与旧版逐字相同
（`ns` / `name` / `node` / `ownerkind` / `req_cpu_m` / `req_mem_mi`），
只是数值改由 `pod_requests()` 算：

```bash
python3 - "$S/references" "$IV/k8s-pods-raw.json" > $IV/k8s-pods.json <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import core
out = []
for p in json.load(open(sys.argv[2]))["items"]:
    if p["status"]["phase"] not in ("Running", "Pending"):
        continue
    cpu, gib = core.pod_requests(p)          # 调度口径：init 取 max、overhead 叠加
    md, spec = p["metadata"], p["spec"]
    out.append({"ns": md["namespace"], "name": md["name"],
                "node": spec.get("nodeName") or "UNSCHEDULED",
                "ownerkind": (md.get("ownerReferences") or [{}])[0].get("kind", "none"),
                "req_cpu_m": round(cpu * 1000, 3), "req_mem_mi": round(gib * 1024, 3)})
json.dump(out, sys.stdout, ensure_ascii=False)
PY

jq -r '"pods=\(length) zero_req=\([.[]|select(.req_cpu_m==0 and .req_mem_mi==0)]|length)"' \
  $IV/k8s-pods.json
```

差距有多大：一个 pod 两个普通容器 `250m`+`50m`、一个 init 容器 `2`、overhead `100m`，
按容器求和得 **300m**，按调度口径得 `max(300m, 2000m) + 100m` = **2100m**——**7 倍**。
内存同例 `576Mi` vs `1144Mi`。这就是"自己 sum"与判据的实际差额。

### §4.1c 多集群必须逐个算，不得汇总

```bash
for C in $(aws eks list-clusters --region "$R" --query 'clusters[]' --output text); do
  KCDIR=$(mktemp -d); KC="$KCDIR/config"
  aws eks update-kubeconfig --region "$R" --name "$C" --kubeconfig "$KC" >/dev/null
  KUBECONFIG="$KC" kubectl get nodes -o json > "$IV/k8s-nodes-raw-$C.json"
  KUBECONFIG="$KC" kubectl get pods --all-namespaces -o json > "$IV/k8s-pods-raw-$C.json"
  rm -rf "$KCDIR"

  # 拼成 core.booking_rates() 要的形状：nodes 带 allocatable、pods 带原始 spec
  jq -n --slurpfile n "$IV/k8s-nodes-raw-$C.json" \
        --slurpfile p "$IV/k8s-pods-raw-$C.json" --arg c "$C" \
    '{name:$c,
      nodes:[$n[0].items[]|{allocatable:.status.allocatable}],
      pods:[$p[0].items[]|select(.status.phase=="Running" or .status.phase=="Pending")
            |{spec:.spec}]}' > "$IV/eks-booking-$C.json"
done

jq -s '{clusters:.}' $IV/eks-booking-*.json > $IV/eks-booking-in.json

# 一次调用返回逐集群结果。booking_rates() **不提供**汇总口径，这是刻意的。
python3 - "$S/references" "$IV/eks-booking-in.json" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
import core
print(json.dumps(core.booking_rates(json.load(open(sys.argv[2]))["clusters"]),
                 ensure_ascii=False, indent=1))
PY
```

输出形状（对 `tests/fixtures/k8s-pods-sample.json` 实测）：

```
{"cluster-a": {"alloc_cpu": 1.93, "alloc_gib": 6.815, "req_cpu": 0.5, "req_gib": 1.0,
               "cpu_pct": 25.9, "mem_pct": 14.7, "pods": 1},
 "cluster-b": {"alloc_cpu": 3.86, "alloc_gib": 13.631, "req_cpu": 0.2, "req_gib": 0.5,
               "cpu_pct": 5.2,  "mem_pct": 3.7,  "pods": 1}}
```

不同集群的节点池互不调度，**跨集群汇总预订率会掩盖单个集群的错配**。

### §4.2 bin-packing 理论最少节点数

```bash
jq -n --slurpfile nodes $IV/k8s-nodes.json --slurpfile pods $IV/k8s-pods.json '
  ($nodes[0]) as $N | ($pods[0]) as $P
| ($N[0].alloc_cpu_m) as $ac | ($N[0].alloc_mem_mi) as $am
| ($P|map(select(.ownerkind=="DaemonSet"))) as $ds
| ($P|map(select(.ownerkind!="DaemonSet"))) as $app
| ($ds|group_by(.node)|map({cpu:(map(.req_cpu_m)|add),mem:(map(.req_mem_mi)|add)})) as $dsn
| ($dsn|map(.cpu)|max) as $dscpu | ($dsn|map(.mem)|max) as $dsmem
| ($app|map(.req_cpu_m)|add) as $acpu | ($app|map(.req_mem_mi)|add) as $amem
| ($ac-$dscpu) as $freecpu | ($am-$dsmem) as $freemem
| { nodes_now:($N|length), alloc_per_node:"\($ac)m/\($am|round)Mi",
    daemonset_per_node:"\($dscpu)m/\($dsmem|round)Mi",
    app_requests:"\($acpu)m/\($amem|round)Mi",
    free_per_node:"\($freecpu)m/\($freemem|round)Mi",
    need_by_cpu:(($acpu/$freecpu)|ceil), need_by_mem:(($amem/$freemem)|ceil),
    min_nodes:([(($acpu/$freecpu)|ceil),(($amem/$freemem)|ceil)]|max),
    zero_request_pods:($app|map(select(.req_cpu_m==0 and .req_mem_mi==0))|length),
    unscheduled:($P|map(select(.node=="UNSCHEDULED"))|length) }'
```

实测输出（5 × 2vCPU/8GiB 节点）：每节点可分配 `1930m/6979Mi`，
DaemonSet 每节点 `680m/513Mi`，业务 request 合计 `4392m/9276Mi` ⇒
CPU 维度需 4 节点、内存维度需 2 节点 ⇒ `min_nodes=4`，当前 5 ⇒ 可减 1 台。

该式是总量近似，成立前提是**最大单 pod request 远小于单节点可用量**
（实测最大 256m vs 每节点可用 1250m）。有大 request pod 时须改真装箱。
缩容建议须在 `blockers` 写明：检查 PodDisruptionBudget、滚动更新余量、
`scalingConfig.minSize` 是否允许、以及 cluster-autoscaler 会不会立刻加回来。

### §4.3 每节点预订率与 HPA / Fargate

```bash
jq -r --slurpfile n $IV/k8s-nodes.json '($n[0][0].alloc_cpu_m) as $ac|($n[0][0].alloc_mem_mi) as $am
| group_by(.node)[]|{node:(.[0].node|split(".")[0]),pods:length,
    cpu:(map(.req_cpu_m)|add),mem:(map(.req_mem_mi)|add)}
| "\(.node) pods=\(.pods) cpu=\(.cpu)m(\((.cpu/$ac*100)|round)%) mem=\(.mem|round)Mi(\((.mem/$am*100)|round)%)"' \
  $IV/k8s-pods.json

kubectl get hpa --all-namespaces -o json \
  | jq -r '.items[]|[.metadata.namespace,.metadata.name,.spec.minReplicas,.spec.maxReplicas,.status.currentReplicas]|@tsv'
```

### §4.4 pod 级实际用量：只有 Container Insights 能给历史序列

`kubectl top nodes` / `top pods` 需要 metrics-server，且**只有瞬时值**，
不能当定档依据。历史 p95 必须靠 `ContainerInsights` 命名空间。

```bash
aws cloudwatch list-metrics --region $R --namespace ContainerInsights \
  --query 'length(Metrics)' --output text
```

**实测坑**：集群里装了 `amazon-cloudwatch-observability` addon 与
`cloudwatch-agent` DaemonSet，`ContainerInsights` 命名空间**仍为 0**
（指标没落到该命名空间）。所以**不能用"agent 装了"推断"指标有"**，
必须用 `list-metrics` 实证。为 0 时只出节点级结论，并在报告缺口标注
"pod 级不可得 + 每 workload 的目标 request 给不出来"。

## §5 RDS 可订购类查询的性能约束

`describe-orderable-db-instance-options` **必须 pin `--engine-version` 且异步执行**。
实测不 pin 版本时两次调用均超过 120 秒超时；pin 后响应体 1.8 MB、251 个类。

**2026-09-03 复测：pin 了版本 + 300 秒超时仍然超时。** 该调用不可靠，
不能作为降配候选的唯一来源。**回退路径**：用 pricing API 按
`databaseEngine` + `deploymentOption` 取回价目表，其中出现的实例类即该 region
该引擎该部署形态实际可订购的集合：

```bash
aws pricing get-products --region us-east-1 --service-code AmazonRDS \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
    'Type=TERM_MATCH,Field=databaseEngine,Value=MySQL' \
    'Type=TERM_MATCH,Field=deploymentOption,Value=Multi-AZ' \
  --output json > $SP/rds-price-raw.json

jq -r '[.PriceList[]|fromjson
        | select((.product.attributes.instanceType // "") != "")
        | {t:.product.attributes.instanceType, ut:.product.attributes.usagetype,
           vcpu:.product.attributes.vcpu, mem:.product.attributes.memory,
           usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
                |to_entries[0].value.pricePerUnit.USD|tonumber)}]
      | map(select(.usd>0)) | sort_by(.usd)
      | .[] | "\(.t)\t\(.vcpu)C/\(.mem)\t\(.ut)\t\(.usd)"' $SP/rds-price-raw.json
```

用回退路径时必须在报告缺口写明"候选集来自价目表而非权威可订购列表"。

### §5.1 非 EC2 服务取价必须按 `usagetype` + `operation` 双重消歧

**ElastiCache 与 ELB 只按 `instanceType` / 机型取价会拿到错的数。**
两个服务各有**两个互相独立**的陷阱，只挡住一个仍然取错价。

#### ElastiCache：`usagetype` 挡 extended support，`operation` 挡引擎

实测同一 region 同一节点类型有五行（`us-west-2` / `cache.t3.medium`，
`pricing:GetProducts` 原样输出）：

| $/hr | `usagetype` | `operation` | `cacheEngine` | `vcpu` | `memory` |
|---|---|---|---|---|---|
| 0.0680 | `USW2-NodeUsage:cache.t3.medium` | `CreateCacheCluster:0002` | Redis | 2 | 3.09 GiB |
| 0.0680 | `USW2-NodeUsage:cache.t3.medium` | `CreateCacheCluster:0001` | Memcached | 2 | 3.09 GiB |
| 0.0544 | `USW2-NodeUsage:cache.t3.medium` | `CreateCacheCluster:Valkey` | Valkey | 2 | 3.09 GiB |
| 0.0540 | `USW2-ExtendedSupportYr1_Yr2-NodeUsage:cache.t3.medium` | `CreateCacheCluster:0002` | Redis | `null` | `null` |
| 0.1090 | `USW2-ExtendedSupportYr3-NodeUsage:cache.t3.medium` | `CreateCacheCluster:0002` | Redis | `null` | `null` |

**陷阱一（已记录，仍然成立）：extended support 档。** `unique_by(.instanceType)`
会随机拿到 0.1090（**高估 60%**）或 0.0540（**低估 21%**）。
过滤式 `usagetype` 须匹配 `^[A-Z0-9]+-NodeUsage:` ——`ExtendedSupportYr1_Yr2`
含小写字母与下划线，匹配不上 `[A-Z0-9]+`，这道过滤已经把它挡在外面。
这两行的 `vcpu`/`memory` 为 `null`，是第二道旁证。

**陷阱二（新增）：三个引擎共用同一个 `usagetype`。** Valkey / Redis / Memcached
的 `usagetype` **逐字相同**，三行都能过 `^[A-Z0-9]+-NodeUsage:`，
`vcpu`/`memory` 也都有值——上面那两道旁证一条都不触发。实测
`unique_by(.t)` 取到的是 **Valkey 的 0.0544**，对 Redis 集群**低估 20%**。
实测 us-west-2 全量 506 条价目里，只按 `usagetype` 过滤后
**94** 个 `instanceType` 仍带多个价。

**解法：键改成 `(instanceType, operation)`，与 EC2 侧 `(机型, UsageOperation)` 同构。**
`operation` 本来就在回包里，不必额外取。**两道过滤必须都在**：实测省掉
`usagetype` 过滤、只用 `(t, operation)` 建键，仍有 **153** 个键带多个价——
因为 extended support 行的 `operation` 与正常 Redis 行**也是同一个**
`CreateCacheCluster:0002`。

```bash
aws pricing get-products --region us-east-1 --service-code AmazonElastiCache \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
  --output json > $SP/ec-price-raw.json

# 价目表：键 = "<节点类型>|<operation>"
jq -c '[.PriceList[]|fromjson
        | select((.product.attributes.usagetype // "")|test("^[A-Z0-9]+-NodeUsage:"))
        | {t:.product.attributes.instanceType,
           op:.product.attributes.operation,
           eng:(.product.attributes.cacheEngine|ascii_downcase),
           mem:.product.attributes.memory, vcpu:.product.attributes.vcpu,
           usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
                |to_entries[0].value.pricePerUnit.USD|tonumber)}]
      | map(select(.usd>0))' $SP/ec-price-raw.json > $SP/ec-keyed.json

# 引擎 → operation 映射，从同一份回包里生成（不要硬编码 :0001/:0002 这种不透明码）
jq -c '[.[]|{key:.eng, value:.op}]|unique_by(.key)|from_entries' $SP/ec-keyed.json \
  > $SP/ec-engine-op.json

# 校验：同一 (机型, operation) 出现多价的键数**必须为 0**
jq '[group_by([.t,.op])[]|select((map(.usd)|unique|length)>1)]|length' $SP/ec-keyed.json
# 反向对照：只按机型分组时是多少（不为 0 才说明这道消歧真的在起作用）
jq '[group_by(.t)[]|select((map(.usd)|unique|length)>1)]|length' $SP/ec-keyed.json
```

取价时按集群的引擎选 `operation`：`describe-cache-clusters` 的 `.engine`
（§1 已落进 `$IV/elasticache.json` 的 `engine` 字段）。
**注意大小写**：API 回的是小写 `redis` / `memcached` / `valkey`，
pricing 的 `cacheEngine` 是首字母大写 `Redis` / `Memcached` / `Valkey`，
上面的 jq 已用 `ascii_downcase` 归一。

```bash
# 某集群的节点单价
jq -r --slurpfile p $SP/ec-keyed.json --slurpfile m $SP/ec-engine-op.json \
  '.[] | .engine as $e | .type as $t
   | ($m[0][$e]) as $op
   | [ $p[0][] | select(.t==$t and .op==$op) | .usd ] as $hit
   | "\($t)\t\($e)\t\($op)\t\(if ($hit|length)==1 then $hit[0] else "AMBIGUOUS:\($hit)" end)"' \
  $IV/elasticache.json
```

`$hit` 长度不为 1 就**不得取价**，按 `price-unknown` 处理——长度 0 是引擎映射没命中，
长度 >1 是消歧还不够，两种都不能靠随便挑一个蒙过去。

实测（us-west-2，7 个 `engine=redis` 的集群）：`(cache.t3.medium,
CreateCacheCluster:0002)` 唯一命中 **0.0680**；`unique_by(.t)` 那条路给的是
Valkey 的 0.0544。校验式两个输出分别为 **0** 与 **94**。

#### ALB：`operation` 挡 LB 类型，jq 挡 Outposts 与 `-TS-`

同一 `usagetype=<前缀>-LoadBalancerUsage` 会按 `operation` 返回多个价，
必须限定 `operation=LoadBalancing:Application`。实测 us-west-2 的
`USW2-LoadBalancerUsage` 一个字符串对应四行：

| $/hr | `operation` |
|---|---|
| 0.0225 | `LoadBalancing:Application` |
| 0.0225 | `LoadBalancing:Network` |
| 0.0250 | `LoadBalancing` |
| 0.0125 | `LoadBalancing:Gateway` |

**但加了 `operation` 还不够，而且不要再按 `usagetype` 过滤。**
`usagetype` 的 region 前缀无法从 region 码推出来（见 `SKILL.md`「易错项速查」
里 NAT 那条：`eu-west-1` 的前缀是 `EU-` 而不是 `EUW1-`），
拼错就静默返回空。改成**只按 `operation` 拉回、在 jq 里筛**：

```bash
aws pricing get-products --region us-east-1 --service-code AWSELB \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
    'Type=TERM_MATCH,Field=operation,Value=LoadBalancing:Application' \
  --output json > $SP/alb-price-raw.json

jq '[.PriceList[]|fromjson
     | select((.product.attributes.usagetype // "")|test("LoadBalancerUsage$"))
     | select((.product.attributes.usagetype // "")|test("Outposts|-TS-")|not)
     | {ut:.product.attributes.usagetype,
        usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
             |to_entries[0].value.pricePerUnit.USD|tonumber)}]' $SP/alb-price-raw.json
```

筛完必须只剩 1 条；剩 0 或 >1 一律 `price-unknown`，不得挑一个。
实测两个验证 region 的完整回包（`operation=LoadBalancing:Application`，各 6 行）：

| region | 正确价 `<前缀>-LoadBalancerUsage` | `-TS-` 那行 | 比例 |
|---|---|---|---|
| us-west-2 | **0.0225** | `USW2-TS-LoadBalancerUsage` 0.0063 | 28.0% |
| ap-northeast-1 | **0.0243** | `APN1-TS-LoadBalancerUsage` 0.0054 | 22.2% |

`-TS-` 只有正确价的 **22%–28%**（实测两 region）；若用 `unique_by` 或 `.[0]`
随机取到它，ALB 小时费**低估 3.6–4.5 倍**。
`Outposts-LoadBalancerUsage` 与正确价**数值相同**（两 region 都是），
所以它不会造成金额偏差，但它是 Outposts 场景的价、不该混进普通 ALB 的取价集，
留着会让「筛完只剩 1 条」这道断言恒不成立。
`LCUUsage` / `ReservedLCUUsage` 不以 `LoadBalancerUsage` 结尾，第一道 `test` 已排除。

这与 ElastiCache 的 extended support 是同一形状的陷阱：**同一个 `usagetype`
词根下挂着不同售卖场景的价**，ALB 侧此前只写了 `operation` 一半。

## §6 `core.py` 调用契约

判据的唯一实现是 `references/core.py`，用法只有一种：**一个 JSON 对象走 stdin，
findings 数组走 stdout**。八个顶层键缺一不可（`thresholds` 例外，见下）。

用 `jq -n --slurpfile` 拼这个对象，**不要用 `--argjson` 传价格表**：单 region 的
价格表是 2 万键、1 MB 这个量级（精确条数是 A 类观测值，见 §0.1），
`--argjson` 会撞 `Argument list too long`（实测）。**量级足够支撑这条结论**——
条数再涨只会让它更成立，所以这里不需要现查。

```bash
jq -c '[.[]|{key:"\(.t)|\(.op)", value:.usd}] | from_entries' $SP/od-keyed.json > $SP/price.json
jq -c '[.[]|{key:.t, value:.cat}] | unique_by(.key) | from_entries' $SP/od-keyed.json > $SP/catmap.json

jq -n --arg  prof "$SIZING_PROFILE" \
      --slurpfile s $SP/ec2-types.json \
      --slurpfile p $SP/price.json \
      --slurpfile c $SP/catmap.json \
      --slurpfile o $SP/offerings.json \
      --slurpfile b $S/references/baseline-pct.json \
      --slurpfile l $S/references/legacy-families.json \
      --slurpfile r $O/solver-in.json \
  '{sizing_profile: $prof, specs: $s[0], prices: $p[0], categories: $c[0],
    offerings: $o[0], baseline_pct: $b[0], legacy_families: $l[0],
    resources: $r[0]}' > $O/core-in.json

python3 $S/references/core.py < $O/core-in.json > $O/findings.json
```

| 顶层键 | 形状 | 来源 |
|---|---|---|
| `sizing_profile` | `"aggressive"` / `"conservative"` | 运行时输入，**必填且不可推断**。`core.py` 用下标读它，缺失直接 `KeyError`——两个预设在同一机队上的条数与总额都不同，静默选一个等于替 operator 做决定 |
| `specs` | 机型规格数组，元素含 `t/vcpu/gib/arch/burst/store/ebs` | 运行时，`describe-instance-types` 全量落盘（§0） |
| `prices` | `{"<型号>\|<operation>": usd}` | 运行时取价，见 §6.1 |
| `categories` | `{型号: 用途分类}` | 运行时，从取价输出的 `instanceFamily` 抽取（§6.1 同一次产出） |
| `offerings` | 型号数组 | 运行时，`describe-instance-type-offerings --location-type region`（§6.2） |
| `baseline_pct` | `{型号: 小数}` | `references/baseline-pct.json`（静态资产） |
| `legacy_families` | 族名数组 | `references/legacy-families.json`（静态资产） |
| `resources` | 待判资源数组，**每条必须带 `service`** | §7 组装 |

**不要自己拼 `thresholds`。** `core.py` 只在顶层没有 `thresholds` 键时才按
`sizing_profile` 从 `thresholds.json` 加载——那是唯一正确的路径。`thresholds`
这个键只为测试注入保留：手拼的阈值字典少一个键（例如 `min_biz_hours_points`）
就会让对应的守卫抛 `KeyError`，而这类手拼字典在不同 agent 之间必然不一致。

**只判托管服务时，`specs` / `prices` / `categories` / `offerings` /
`baseline_pct` / `legacy_families` 仍须存在，可以为空**（`[]` / `{}`）——
它们只被 EC2 判据消费，但 `main()` 会无条件索引它们。

自检（**已实测**，用两个验证 region 的归档 `raw/specs/*` + `solver-in.json` 跑过）：

```bash
# ① 输出行数必须等于输入行数——core.py 内部也有同一条 assert
[ "$(jq length $O/findings.json)" = "$(jq '.resources|length' $O/core-in.json)" ] \
  || echo "FAIL: 静默丢行"
# ② verdict / bucket 分布，用于跟 report-template.md 的枚举对照
jq -r '[.[].verdict]|group_by(.)|map({(.[0]):length})|add' $O/findings.json
jq -r '[.[].bucket] |group_by(.)|map({(.[0]):length})|add' $O/findings.json
# ③ 两条降配路线的合计。禁止把两列直接相加（见 SKILL.md），且**必须先排除
#    bucket=="idle" 的行**——闲置行的 nb_save_mo 是"若须保持运行改为降配"的替代
#    方案，该资源已按全额 cur_cost_mo 计入桶 B 合计，再进路线一/二就是同一笔钱
#    算两遍（口径定义见 report-template.md「汇总口径」）。
jq -r '[.[]|select(.bucket!="idle")] as $D
 | "路线一 Σnb=\([$D[]|.nb_save_mo//0]|add // 0) 路线二 Σmax=\([$D[]|[(.nb_save_mo//0),(.b_save_mo//0)]|max]|add // 0)"' \
  $O/findings.json
# ④ 桶 B 合计单独算，且对 idle 行取 cur_cost_mo 而**不是** nb_save_mo
jq -r '"桶B Σcur=\([.[]|select(.bucket=="idle")|.cur_cost_mo//0]|add // 0)"' $O/findings.json
# ⑤ 采集侧合计（第四条口径）**算不出来，这里也不该算**：它对 other_save_mo 求和，
#    而 core.py 按设计从不产出那一列（见 report-template.md 的派生列清单）。
#    findings.json 里没有这一列 ⇒ 只能等 findings.csv 组装完成后在 CSV 上算。
#    算式在 report-template.md「汇总口径」，四条口径一处定义，本文件不复述。
#    ③④ 只给三个数，而报告的摘要要**四个**——少的那个不是漏了，是在下游。
```

**③ 漏掉 `bucket!="idle"` 会把闲置资源算两遍，量级不小。** 实测（us-west-2 真实机队
13 行，`aggressive`，一条 `bucket=idle` 的行同时带 `nb_save_mo=98.55` 与
`cur_cost_mo=1369.48`）：

| profile | 口径 | 不过滤（旧写法） | 过滤 `bucket!="idle"`（正确） |
|---|---|---|---|
| aggressive | 路线一 Σnb | 249.21 | **150.66** |
| aggressive | 路线二 Σmax | 255.05 | **156.50** |
| conservative | 路线一 Σnb | 221.20 | **122.65** |
| conservative | 路线二 Σmax | 227.04 | **128.49** |

四个数各虚高**同一个** 98.55（那一行的 `nb_save_mo`），即路线一被抬高
**65%**（aggressive）到 **80%**（conservative）；而这 98.55 对应的资源已经整台
以 1369.48 记在桶 B 合计里。报告若写「路线一 + 桶 B」，旧写法给的是
`249.21 + 1369.48`，其中 98.55 是重复的。

（这份机队与 `thresholds.md` 里锚定回归总额的那份**不是同一个** region 的机队，
两边都是 13 行属巧合，数字不可互相对照。）

`add // 0` 不是可省的装饰：过滤后可能一行不剩（整个 region 只有闲置资源），
`[]|add` 返回 `null`，字符串插值会得到 `路线一 Σnb=null`——看起来像取不到数，
实际是零。实测空集下改后的命令回 `路线一 Σnb=0 路线二 Σmax=0`。

### §6.1 price 与 catmap 的生成（同一次取价产出两者）

**取价时不要按 `operatingSystem` 过滤**，否则非 Linux 实例会被套用 Linux 价格。

```bash
aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
    'Type=TERM_MATCH,Field=tenancy,Value=Shared' \
    'Type=TERM_MATCH,Field=capacitystatus,Value=Used' \
  --output json > $SP/od-raw.json

jq '[.PriceList[] | fromjson | {
      t:  .product.attributes.instanceType,
      op: .product.attributes.operation,
      cat:.product.attributes.instanceFamily,
      usd:(.terms.OnDemand | to_entries[0].value.priceDimensions
           | to_entries[0].value.pricePerUnit.USD | tonumber)}]
    | map(select(.usd > 0))' $SP/od-raw.json > $SP/od-keyed.json
```

这一步产出的键数、体积、耗时都是 **A 类观测值**（见 §0.1）。
**具体数字只记在「价目缓存」一节的那张表里，本节不复述**——同一组测量抄两处
必然漂成两个值。那里也给了同口径的上一次测量，可以看出漂移幅度。

### 非 EC2 服务的取价属性（每个都不一样，实测确认）

**属性名猜错时 pricing API 返回空且不报错**，症状像"该服务没有价格"。逐服务实测：

| 服务 | serviceCode | 关键属性 | 必加过滤 |
|---|---|---|---|
| MSK broker | `AmazonMSK` | **`computeFamily`**（值形如 `t3.small`，**不带 `kafka.` 前缀**） | `usagetype` 形如 `<区域前缀>-Kafka.<型号>`，须排除 `Express` |
| ElastiCache | `AmazonElastiCache` | `instanceType`（带 `cache.` 前缀）、**`operation`**、`memory`、`vcpu`、`cacheEngine` | **两道都要**：`usagetype` 匹配 `^[A-Z0-9]+-NodeUsage:`（挡 `ExtendedSupport*`）＋ 键含 `operation`（挡 Valkey / Redis / Memcached 共用同一 usagetype）。见 §5.1 |
| EBS | `AmazonEC2` | `productFamily=Storage` + `volumeApiName` | — |
| NAT Gateway | `AmazonEC2` | `productFamily=NAT Gateway` | `usagetype` 含 `NatGateway-Hours`（同时命中 `NatGateway-Hours` 与 `RegionalNatGateway-Hours` 两行，实测两行同价故不影响金额）。**不得反推 region 前缀**，见「易错项速查」 |
| RDS | `AmazonRDS` | `instanceType`（带 `db.` 前缀） | **`usagetype` 须限 `Multi-AZUsage:`**，否则混进 Single-AZ 价 |
| ELB | `AmazonEC2` / `AWSELB` | `usagetype` + `operation` 双重消歧 | `operation=LoadBalancing:Application` 限 LB 类型；再在 jq 里排除 **`Outposts`** 与 **`-TS-`**。实测 `-TS-` 只有正确价的 **22%–28%**（两 region），随机取到即**低估 3.6–4.5 倍**；`Outposts` 与正确价同值，不影响金额但会破坏「筛完只剩 1 条」这道断言。见 §5.1 |

**MSK 是唯一一个属性名与其他服务不同的**：按 `instanceType` 过滤实测返回 **0 条且不报错**
（试错三轮才定位）。正确写法：

```bash
aws pricing get-products --region us-east-1 --service-code AmazonMSK \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" --output json \
| jq '[.PriceList[]|fromjson
       | select((.product.attributes.usagetype // "") | test("Express") | not)
       | {family:.product.attributes.computeFamily,
          usagetype:.product.attributes.usagetype,
          usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
               |to_entries[0].value.pricePerUnit.USD|tonumber)}]
      | map(select(.usd>0))'
```

### 公有 IPv4 取不到价——标 price-unknown，不得用记忆值顶替

未关联 EIP 的公有 IPv4 单价**经 pricing API 三条路都取不到**（实测）：

| 尝试 | 结果 |
|---|---|
| `AmazonEC2` 的 `IP Address` 族 | 只含 Wavelength CarrierIP |
| `AmazonVPC` 的 `Public IPv4 Address` 族 | 不存在该族 |
| `get-attribute-values` 枚举 | 超时 |

按 skill 规则标 `price-unknown`、**不计入合计**，并在报告写明该项金额缺失。
**不得用记忆里的单价顶替**——那会让一个无法核实的数字混进可核实的合计里。

### 价目缓存：用 version 校验，不用时间猜测

全量取回代价不小——**百 MB / 分钟级 / 两万条**这个量级（精确值是 A 类观测值，
见 §0.1；最近一次实测在本节末），但价目响应每条记录都带
`version` 与 `publicationDate`，**同一次取回内完全一致**，且**单机型探针返回同一个
version**，耗时仅数秒。因此缓存有效性用探针判定：

```bash
CACHE="$HOME/.cache/aws-rightsizing/prices-$R.json"      # 文件名必须含 region

PROBE=$(aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
    'Type=TERM_MATCH,Field=instanceType,Value=m5.large' \
    'Type=TERM_MATCH,Field=tenancy,Value=Shared' \
    'Type=TERM_MATCH,Field=capacitystatus,Value=Used' \
    'Type=TERM_MATCH,Field=operatingSystem,Value=Linux' \
  --max-results 1 --output json | jq -r '.PriceList[0]|fromjson|.version')

[ -n "$PROBE" ] || { echo "STOP: pricing 探针失败，不得回退缓存"; exit 1; }

CACHED=$(jq -r '.version // "none"' "$CACHE" 2>/dev/null || echo none)

if [ "$PROBE" = "$CACHED" ]; then
  echo "价目缓存命中 version=$PROBE，复用（省一次全量取回）"
else
  echo "价目版本 $CACHED → $PROBE，全量重取"
  mkdir -p "$(dirname "$CACHE")"
  aws pricing get-products --region us-east-1 --service-code AmazonEC2 \
    --filters "Type=TERM_MATCH,Field=regionCode,Value=$R" \
      'Type=TERM_MATCH,Field=tenancy,Value=Shared' \
      'Type=TERM_MATCH,Field=capacitystatus,Value=Used' \
    --output json \
  | jq --arg v "$PROBE" --arg r "$R" --arg f "$(date -u +%FT%TZ)" \
      '{version:$v, region:$r, fetched:$f,
        data:[.PriceList[]|fromjson|{t:.product.attributes.instanceType,
              op:.product.attributes.operation,
              cat:.product.attributes.instanceFamily,
              usd:(.terms.OnDemand|to_entries[0].value.priceDimensions
                   |to_entries[0].value.pricePerUnit.USD|tonumber)}]
             |map(select(.usd>0))}' > "$CACHE"
fi

PRICE_KEYED=$(jq -c '[.data[]|{key:"\(.t)|\(.op)", value:.usd}]|from_entries' "$CACHE")
CAT_MAP=$(jq -c '[.data[]|{key:.t, value:.cat}]|unique_by(.key)|from_entries' "$CACHE")
```

**四条硬要求：**

1. **文件名必须含 region。** 价格随 region 变（实测东京对弗吉尼亚溢价 117–131%），
   `(机型, operation)` 键集也不同。不含 region 的缓存会重犯已删除的
   `offerings-region.json` 那个错——被误用于其他 region 且**查不出来**。
2. **顶层必须存 `version` / `region` / `fetched`。** 缺 `version` 就无法校验，
   缓存退化为不可信快照。
3. **缓存只放运行环境 `~/.cache/`**，不进 skill 包、不进版本库。skill 静态资产仅
   `baseline-pct.json` 与 `legacy-families.json`——它们无 API 可查；价目可查且会变。
4. **探针失败不得回退缓存。** 探针失败说明 `pricing:GetProducts` 不可用，
   而无价格时选型退化为"最小够用"会推荐出更贵的机型
   （实测 `i3en.large` $0.266 > `m5.xlarge` $0.248）。按 preflight 规则停止。

**为什么不能用「缓存 N 天」**：AWS 调价无固定周期，7 天可能跨了一次调价、
30 天可能一次都没调。version 比对是确定性判据，且探针只花数秒
（把上面那条探针原样跑了一次，实测 2.5 秒，返回一个非空 `version` 串——
具体值当然也是 A 类，故不抄进来）。

**全量取回的最近一次实测（观测值 @2026-09-04，A 类，见 §0.1）：**

| region | 唯一 `(型号, operation)` 键数 | 体积 | 耗时 |
|---|---|---|---|
| ap-northeast-1 | 19,754 | 95.6 MiB | 82 秒 |
| us-west-2 | 21,025 | 100.0 MiB | 90 秒 |

同口径 2026-09-03 记录的是 ap-northeast-1 = 19,534、us-west-2 = 21,019。
**耗时尤其不要当基准**：两次的差别里既有条数增长也有网络波动，同一 region
重跑就能差十几秒。us-west-2 的体积上一次记的是「约 112 MB」，这次量到 100.0 MiB
（104,882,034 字节），**没能复现**——单位口径与取回时点都可能不同，
这正是这类数字不能当断言的原因。

### §6.2 offerings 的生成

```bash
jq -c 'unique' <<<"$(aws ec2 describe-instance-type-offerings --region $R \
  --location-type region --query 'InstanceTypeOfferings[].InstanceType' --output json)" \
  > $SP/offerings.json
```

**必须按当前 region 现查。** 观测值 @2026-09-04（A 类，见 §0.1）：
ap-northeast-1 有 1198 个、us-east-1 有 1371 个、us-west-2 有 1350 个，
其中 182 个仅 us-east-1 提供（相对 ap-northeast-1）、9 个仅 ap-northeast-1 提供。
套错 region 会错误排除大量候选——**这条结论稳定，具体个数不稳定。**

差集比单个计数漂得更快，因为两端都在动：同一组数 2026-09-03 时是
「226 个仅 us-east-1 提供」，一天后变成 182 个，而两 region 的并集
**两天都是 1380**（新增的 44 个 ap-northeast-1 机型 us-east-1 早就有）。
所以复述差集尤其没有意义。

## §7 solver-in.json 的组装（`core.py` 的 `resources` 数组）

`agg` 输出 + `inventory` 两方 join。**这一步没有附带脚本，规格在本节，按规格实现。**
`operation`（平台/授权）来自 inventory 的 `UsageOperation`，即"三方"里的第三方
已经并进 inventory，不需要单独一份 platform 文件。

**遍历方向是 inventory，不是 agg。** 以 agg 为主循环会让"一个指标都没采到"的实例
整条消失——而那恰恰是最需要被人看到的资源（新建、刚停机、维度写错）。
以 inventory 为主循环，缺指标的实例照样出一行、字段为 `null`，由 `core.py`
判成 `insufficient-data` / `metric-missing`。

### §7.0 字段规格（逐字段，缺失一律 `null`，**禁止兜底为 0**）

| 字段 | 必填 | 取法 | 缺失后果 |
|---|---|---|---|
| `rid` | 是 | inventory `.id` | `KeyError` |
| **`service`** | **是** | 本节只组装 EC2，**恒为字符串 `"ec2"`** | **`core.py` 抛 `ValueError`**。它是分派键，缺失不回退（见 §7.3） |
| `type` | 是 | inventory `.type` | `KeyError` |
| `arch` | 是 | inventory `.arch` | 候选池恒空，无建议 |
| `operation` | 是 | inventory `.op`（= `UsageOperation`） | `price-unknown` |
| `az` | 否 | inventory `.az` | 原样输出，报告里少一列 |
| `name` | 否 | inventory `.name` | 报告 `resource_name` 列为空 |
| `count` | 否，默认 1 | 一行一实例时填 `1`；**若按机型分组成一行，填该组实例数** | `core.py` 用它乘 `cur_cost_mo` 与两个 `*_save_mo`。**字段名就是 `count`**——写成 `instance_count`（CSV 输出列名）会被静默忽略、按 1 计算，**按分组规模低估节省额** |
| `sus_cpu` | 是 | agg 中 `CPUUtilization` / `Average` / `biz-hours` 那一行的 `p95` | `metric-missing` |
| `peak_cpu` | 是 | agg 中 `CPUUtilization` / `Maximum` / `biz-hours` 那一行的 `max` | `metric-missing` |
| `cpu_n` | 是 | 与 `sus_cpu` **同一行**的 `n`（biz-hours 有效点数） | `insufficient-data` |
| `sus_mem` | 否 | agg 中 `mem_used_percent` / `Average` / `biz-hours` 的 `p95` | 内存保持当前规格，`confidence` 上限 `medium` |
| `peak_mem` | 否 | 同上，`Maximum` 的 `max` | 同上 |
| `ebs_need` | 是 | `(Σ EBSReadBytes 的 Sum + Σ EBSWriteBytes 的 Sum) ÷ 窗口秒数 ÷ 1048576`，单位 MB/s | `metric-missing`（**不可当 0**，否则跳过带宽校验，选出带宽不够的机型） |
| `net_mb_day` | 桶 B 需要 | `(Σ NetworkIn 的 Sum + Σ NetworkOut 的 Sum) ÷ 1048576 ÷ 窗口天数` | `is_idle()` 返回 `False`，该资源不进桶 B（不是"判成不闲置"，是"没判"） |
| `surplus_credits` | T 机型必填 | agg 中 `CPUSurplusCreditsCharged` / `Maximum` 的 `max`，**三档取最大**。**非突发机型该序列结构性不存在，字段留空即正确** —— `core.py` 用 spec 的 `burst` 标志区分「不适用」与「缺失」。**不要补 0**：补 0 会让「当前机型是 T 系列而序列真的采失败」被当成「已确认未超额」放行，那是反方向的错且无任何信号 | **当前机型是 T 系列时**抑制 burstable 侧（不能断言"没超额"）；非突发机型不受影响 |
| `credit_balance_min` | T 机型必填 | agg 中 `CPUCreditBalance` / `Minimum` / **`full-window`** 档的 `min`。**这是下限型指标，必须取 `full-window`** —— `biz-hours` 会漏掉夜间批处理把信用耗尽的低点（同 `freeable_mem_min_gib` 的坑）。**非突发机型该序列结构性不存在，字段留空即正确，不要补 0** | 当前机型是 T 系列时 `metric-missing`（信用耗尽会把 `CPUUtilization` 压住，放行等于按被限流的持续值定档）；非突发机型不受影响 |
| `credit_balance_max` | T 机型必填 | 同一行的 `max`（判据按「占窗口内观测最大余额的百分比」判，不依赖信用上限——RDS 的 baseline 百分比不在本 skill 的静态资产里） | 同上 |
| `has_replica` | ElastiCache 必填 | 由 `raw/inventory/elasticache.json` 的节点 `id`（形如 `<rg>-<NNNN>-<MMM>`）按 `(rg, NNNN)` 分组，**任一分片的成员数 > 1** 即 `true`。**不要用 `count` 代替** —— `3 分片 × 1 节点`（`count=3`、无副本）是合法的 cluster-mode 配置 | `metric-missing`（无法区分「无副本故不适用」与「采集失败」，不得假定无副本） |
| `engine` | ElastiCache 必填 | `raw/inventory/elasticache.json` 每个节点的 `engine` 字段原值（**小写**，实测 `"redis"`）。引擎是复制组级属性，同组取任一节点即可 | `metric-missing` —— 无法判定两个主判据指标是否适用，**不得假定 Redis**。`memcached` 与未知取值 ⇒ `excluded`（本版本不评估，白名单见 `core.py` 的 `EC_ENGINES_WITH_ENGINE_CPU`） |
| `off_sus_cpu`、`off_peak_cpu`、`off_net_mb_day` | 桶 C 需要 | 与 `sus_cpu` / `peak_cpu` / `net_mb_day` 同法，但只取 `bucket == "off-hours"` 那一档 | 六个里少一个 ⇒ `stop_candidate = null`（**判不了**，不是"不是候选"） |
| `weekend_sus_cpu`、`weekend_peak_cpu`、`weekend_net_mb_day` | 桶 C 需要 | 同上，取 `weekend` 档 | 同上 |
| `metric_coverage` | 是 | 上面哪几项取不到的名字数组 | 报告缺口列不出来 |
| `partial_coverage` | 否 | 三元组数组 `[[指标名, 该指标点数, 该资源最大点数], …]`。派生规则：同资源 `full-window` 档内，**该资源最大点数 >= 600** 且某指标点数 **< 最大值的 90%**。与 `metric_coverage` 不同——那条列的是**完全缺失**的字段，本条列的是**部分覆盖**的指标 | 不加注记，行为与不传时逐字相同（**可选字段，向后兼容**） |

**`has_replica` 的派生。** 从节点 id 的分片-成员结构推出，**不需要**
`describe-replication-groups`。

**节点 id 有两种形态，取决于 cluster mode**（实测，两支机队都同时存在）：

| cluster mode | 节点 id | 分片号 |
|---|---|---|
| enabled | `<rg>-<NNNN>-<MMM>`（如 `…redis-01-0001-002`） | 有 |
| **disabled** | `<rg>-<MMM>`（如 `…redis-01-002`） | **无**，隐含单分片 |

**只认前一种会静默丢掉后一种。** 实测某账号 13 个复制组里有 2 组是非集群模式，
按单形态正则推导只得到 11 组 —— 那 2 组的 `has_replica` 会缺失，
进而整组判 `metric-missing`。所以分片号必须**可选**，缺省当 `0001`：

```bash
jq -s '
  [ .[0][]
    | {rg,
       shard: (((.id | capture("-(?<s>[0-9]{4})-[0-9]{3}$").s)? // "0001")),
       member: (.id | capture("-(?<m>[0-9]{3})$").m)} ]
  | group_by(.rg)
  | map({ (.[0].rg): (group_by(.shard) | map(length) | max > 1) })
  | add
' raw/inventory/elasticache.json > raw/solver/has-replica.json
```

`rg` 直接取 inventory 里的字段，**不从 id 里解析** —— 复制组名本身含连字符和
数字后缀，用一条正则同时切 `rg` 与分片号必然在某些命名上切错。

**自检两条**（都必须相等；不等说明有节点 id 两种形态都不匹配、被静默丢弃）：

```bash
# ① 覆盖到的节点数 == inventory 节点总数
jq -s '[.[0][] | (.id | capture("-(?<m>[0-9]{3})$").m)] | length' \
   raw/inventory/elasticache.json
jq 'length' raw/inventory/elasticache.json
# ② 推出的复制组数 == inventory 的 rg 去重数
jq 'length' raw/solver/has-replica.json
jq '[.[].rg] | unique | length' raw/inventory/elasticache.json
```

实测两支机队：节点 64/64 → 13 组（**12 有副本 / 1 无副本**）、
节点 42/42 → 11 组（**10 / 1**）。形态分布含
`3 分片×2 成员`、`3 分片×3 成员`、`1 分片×3 成员`、非集群模式 `3 成员`、
以及单节点 `1×1`。

**不要用 `count` 代替。** 在这两份数据上 `count > 1` 恰好与本推导同结果
（唯一的无副本组也正好是单节点），**但那是巧合**：`3 分片×1 节点`
（`count=3`、无副本）是合法的 cluster-mode 配置，按 `count` 判会把它误报成
「该有副本却缺指标」。上面的配方在合成用例上验证过这一形态判 `false`。

**`partial_coverage` 的派生。** 信号在已采的 `n` 里，不需要新增任何 API 调用：
同一资源内某指标的点数明显低于该资源其他指标的点数，说明它只在窗口的一段时间
里存在 —— 常见成因是**窗口内改过规格**（实测两台 `db.m6g.xlarge` 的信用序列
只覆盖 178/720，而核心指标 720/720，且信用上限对应一个更小的机型）。

```bash
for f in raw/metrics/summary-*.csv; do
  case "$f" in *vpc*) continue;; esac      # ALB/NAT 见下方警告
  awk -F, 'NR>1 && $5=="\"full-window\"" {
             gsub(/"/,""); res=$1; met=$2; n=$6+0
             if (n > mx[res]) mx[res]=n
             key=res SUBSEP met; pts[key]=n; r[key]=res; m[key]=met }
           END { for (k in pts)
                   if (mx[r[k]] >= 600 && pts[k] < mx[r[k]] * 0.9)
                     printf "%s\t%s\t%d\t%d\n", r[k], m[k], pts[k], mx[r[k]] }' "$f"
done
```

**两个门限的理由**：`>= 600`（30 天窗口的 ~83%）确保拿来做基准的「该资源最大
点数」自己是满覆盖的 —— 否则一个整体新建的资源会让所有指标互相比较、全部通过；
`< 90%` 留出正常抖动的余量（CloudWatch 偶发缺点、窗口边界）。

**这两个数不进 `thresholds.json`**：它们只在派生时用，`core.py` 只消费结果数组、
从不读它们。放进去会造出一个判据从不读取的孤儿键，而
`tests/test_no_duplicated_constants.py` 的键覆盖是**双向**的。

**实测结果**（两支机队）：命中 **2 台 RDS**（各 2 个指标，均 `178/720`）。
ALB 的 `ActiveConnectionCount` 也会命中，但那属采集侧的 VPC 行、`core.py` 没有
VPC 判据，且 §2.6 的 ALB/NAT 闲置判据**本来就带覆盖度门槛** ——
**不要把 ALB/NAT 的行喂进 `partial_coverage`**，那会重复告警（上面的 `case` 已排除）。

**桶 C 的网络口径。** `off_net_mb_day` / `weekend_net_mb_day` 是**该档的 Σ Sum
÷ 窗口天数**，即"该时段对全天流量的贡献"，与 `net_mb_day`（三档合计）同一个分母，
所以三者可以直接相加核对。门限沿用 `idle_net_mb_day`，对子集而言更严，
这是刻意的——桶 C 输出的是候选清单，宁可少给。

**Σ Sum 怎么从 agg 里取。** `agg.jq` 不输出 `sum` 列，但它的 `mean` 就是
`add / length`，所以某一档的 Σ Sum **恒等于** `mean × n`，三档相加即全窗口总量。
这是恒等式而不是近似——不要为了拿总量去改 `agg.jq`，也不要退回用 `Average` 乘系数。

### §7.1 Sum 语义指标：只认 `Stat=Sum`，零换算假设

`NetworkIn` / `NetworkOut` / `EBSReadBytes` / `EBSWriteBytes` 是**按发布粒度累计的量**
而非速率。`Stat=Average` 拿到的是"每个发布间隔的字节数"的小时均值，要还原总量必须乘一个
**取决于 SampleCount 而非发布粒度**的系数——本 skill 在这个系数上写错过三次
（×24 → ×288 → ×1440，每次都标着"实测"）。

**所以采集侧就取 `Stat=Sum`**（§2.1 的模板已经这么写）：Σ Sum 就是窗口内总字节数，
换算只剩下除以窗口长度这一步，没有任何依赖发布粒度的系数。

实测：按 ×24 算把 11 台实际有流量的实例误判成闲置（低估 12 倍），
修正后同一 region 只剩 1 台真闲置。闲置判据的网络门限 `idle_net_mb_day` 很小，
12 倍偏差足以把判据从"几乎选不中"翻成"几乎全选中"。

**发布粒度（`Monitoring.State`）不进这一步的算式。** 它逐实例而异
（`report-template.md` 要求报告逐实例标注），任何"全机队一个发布粒度"的标量都必然错。
`Stat=Sum` 把这个变量整个消掉了。发布粒度只影响一件事：basic monitoring 下
<5 分钟的尖峰不可见——那是报告里要声明的口径限制，不是换算系数。

### §7.2 组装式（**已实测**）

```bash
# 先合并该 region 全部 EC2 相关的 agg（主指标 + CWAgent 内存 + 信用指标）
jq -s 'add' $M/agg-ec2.json $M/agg-mem.json > $M/agg-ec2-all.json

cat > $O/solver-in.jq <<'JQ'
def mn:   .rid | split("@")[1];      # Label 第一段是 "<rid>@<metric>"
def rid0: .rid | split("@")[0];
def one($x; $m; $st; $bk): $x["\($m)|\($st)|\($bk)"];
# 某指标全窗口的 Σ Sum：agg 的 mean = add/length，故 mean*n 就是该档的 Sum 之和。
# **`.bucket != "full-window"` 不可省。** agg.jq 除三档外还输出一个 full-window 行，
# 它的 mean*n 恰好等于三档之和 ⇒ 不排除就把总量算成 2 倍。
# 后果是双向的、且都静默：`net_mb_day` 翻倍会让真闲置实例（4 MB/日 → 报 8）
# 越过 `idle_net_mb_day` 门限、永远进不了桶 B（实测漏判过 $1,369/mo 的实例）；
# `ebs_need` 翻倍会让 `passes_common` 的带宽校验否掉本来够用的候选、白丢节省。
def tsum($rows; $m):
  [ $rows[]
    | select(mn == $m and .stat == "Sum" and .bucket != "full-window")
    | .mean * .n ]
  | if length == 0 then null else add end;
# 同上，但只算某一档（桶 C 要分档看）
def bsum($rows; $m; $bk):
  [ $rows[] | select(mn == $m and .stat == "Sum" and .bucket == $bk) | .mean * .n ]
  | if length == 0 then null else add end;
# 某档的 net_mb_day：该档 Σ Sum ÷ 窗口天数，与全窗口口径同分母
def bnet($rows; $bk; $days):
  [ bsum($rows; "NetworkIn"; $bk), bsum($rows; "NetworkOut"; $bk) ]
  | if any(. == null) then null else (add / 1048576 / $days) end;

($agg[0]) as $A
| ($days * 86400) as $wsec
| ( $A | group_by(rid0) | map({key: (.[0]|rid0), value: .}) | from_entries ) as $BY
| map(
    . as $i
  | ( $BY[$i.id] // [] ) as $rows
  | ( $rows | map({key: "\(mn)|\(.stat)|\(.bucket)", value: .}) | from_entries ) as $x
  | one($x; "CPUUtilization"; "Average"; "biz-hours")   as $cpuA
  | one($x; "CPUUtilization"; "Maximum"; "biz-hours")   as $cpuM
  | one($x; "mem_used_percent"; "Average"; "biz-hours") as $memA
  | one($x; "mem_used_percent"; "Maximum"; "biz-hours") as $memM
  | ( [ $rows[] | select(mn == "CPUSurplusCreditsCharged" and .stat == "Maximum") | .max ]
      | if length == 0 then null else max end )                             as $sc
  | ( [ tsum($rows; "NetworkIn"), tsum($rows; "NetworkOut") ]
      | if any(. == null) then null else (add / 1048576 / $days) end )       as $net
  | ( [ tsum($rows; "EBSReadBytes"), tsum($rows; "EBSWriteBytes") ]
      | if any(. == null) then null else (add / $wsec / 1048576) end )       as $ebs
  | { rid: $i.id, service: "ec2", type: $i.type, arch: $i.arch,
      operation: $i.op, az: $i.az, name: $i.name, count: 1,
      sus_cpu:  ($cpuA | if . == null then null else .p95 end),
      peak_cpu: ($cpuM | if . == null then null else .max end),
      cpu_n:    ($cpuA | if . == null then null else .n   end),
      sus_mem:  ($memA | if . == null then null else .p95 end),
      peak_mem: ($memM | if . == null then null else .max end),
      net_mb_day: $net, ebs_need: $ebs, surplus_credits: $sc,
      # 桶 C：off-hours 与 weekend 两档各三项，缺一即 stop_candidate=null
      off_sus_cpu:      (one($x; "CPUUtilization"; "Average"; "off-hours")
                         | if . == null then null else .p95 end),
      off_peak_cpu:     (one($x; "CPUUtilization"; "Maximum"; "off-hours")
                         | if . == null then null else .max end),
      off_net_mb_day:   bnet($rows; "off-hours"; $days),
      weekend_sus_cpu:  (one($x; "CPUUtilization"; "Average"; "weekend")
                         | if . == null then null else .p95 end),
      weekend_peak_cpu: (one($x; "CPUUtilization"; "Maximum"; "weekend")
                         | if . == null then null else .max end),
      weekend_net_mb_day: bnet($rows; "weekend"; $days),
      metric_coverage:
        ( [ if $cpuA == null or $cpuM == null then "cpu"     else empty end,
            if $memA == null or $memM == null then "mem"     else empty end,
            if $ebs  == null                  then "ebs"     else empty end,
            if $net  == null                  then "net"     else empty end,
            if $sc   == null                  then "credits" else empty end ] ) } )
JQ

jq -c --slurpfile agg $M/agg-ec2-all.json --argjson days "$WINDOW_DAYS" \
   -f $O/solver-in.jq $IV/ec2-standalone.json > $O/solver-in.json
```

**主循环喂的是 `ec2-standalone.json`，不是 `ec2.json`。** EKS 节点不进
`solver-in.json`（§7.3 ① 与 `report-template.md`「分母的范围」都以此为准）：
节点机型只能整池改，逐节点出降配建议不可执行，且与节点池聚合行的节省额重复计数。
用 `ec2.json` 会同时犯两个错：多出一批不可执行的建议，且让 §7.3 ① 必然 FAIL。
指标侧不受影响——`agg-ec2-all.json` 里照样有节点的序列（§4 的预订率要用），
只是本步不为它们建行。

`if . == null then null else .p95 end` 这种写法不能简写成 `.p95 // null`：
`//` 的 falsy 语义会把 **`0` 换成右值**，而 `p95 = 0`（零流量、零 CPU）是有效值，
恰恰是闲置信号最强的那些记录。整个 skill 一律用显式 `== null` 判缺失。

### §7.3 组装后的必检项

```bash
# ① 元素数须等于 §1.1 ④ 的 ec2-standalone.json 行数——**不是 ec2.json**：
#    §4 把 EKS 节点排除在 solver 之外（节点机型只能整池改），所以本文件的行数
#    必然少于 ec2.json，少的正是节点数。
[ "$(jq length $O/solver-in.json)" = "$(jq length $IV/ec2-standalone.json)" ] \
  || echo "FAIL: 数量不匹配"

# ② 必需字段齐全（service 在内——缺它 core.py 直接抛错）
jq -r '["rid","service","type","arch","operation","sus_cpu","peak_cpu","sus_mem",
        "peak_mem","ebs_need","net_mb_day","surplus_credits","cpu_n"] as $F
 | [ .[] as $e | $F[] as $f | select(($e|has($f))|not) | $f ] | unique
 | if length==0 then "OK" else "MISSING: \(.)" end' $O/solver-in.json

# ③ 恒不得为 null 的字段（sus_mem/peak_mem 允许 null = 内存不动）
jq -r '[.[]|select(.service==null or .type==null or .arch==null or .operation==null)|.rid]
 | if length==0 then "OK" else "NULL: \(.)" end' $O/solver-in.json

# ④ service 取值只能是 ec2（本节只组装 EC2）
jq -r '[.[].service]|unique|if .==["ec2"] then "OK" else "BAD service: \(.)" end' $O/solver-in.json

# ⑤ 内存数据覆盖率（决定多少条建议只能给 medium confidence）
jq -r '"mem coverage: \([.[]|select(.sus_mem!=null)]|length)/\(length)"' $O/solver-in.json

# ⑥ 桶 C 可评估率：六个分档字段齐全的条数。不齐 ⇒ stop_candidate=null，
#    报告里必须写"桶 C 未评估"，不能写"无候选"
jq -r '["off_sus_cpu","off_peak_cpu","off_net_mb_day",
        "weekend_sus_cpu","weekend_peak_cpu","weekend_net_mb_day"] as $F
 | "bucket-C evaluable: \([.[]|select([$F[] as $f|.[$f]]|all(.!=null))]|length)/\(length)"' \
  $O/solver-in.json
```

**① 的分母为什么不是 `ec2.json`。** §4 要求 EKS 节点与独立 EC2 分开处理——
节点机型由 nodegroup 的 `instanceTypes`（或 Karpenter NodePool）决定，
**单个节点无法单独降配**，逐节点出降配建议既不可执行、又与节点池聚合行的节省额
重复计数（同一条规则也写在 `report-template.md`「分母的范围」里）。
所以 `solver-in.json` 的行数**必然少于** `ec2.json`，凡集群非空即少。
拿 `ec2.json` 当分母是**照文档逐字执行必然 FAIL** 的断言，不是偶发不匹配：
实测验证 region us-west-2，`solver-in.json` **13** 行 vs `ec2.json` **18** 行，
差的正好是那 5 台节点。正确分母是 §1.1 ④ 的 `ec2-standalone.json`。
EKS 节点的行由 §4 另行产出（`service=eks`，不走 `core.py`），
两边合起来分母才完整——**节点不进 solver ≠ 节点不进分母**。

托管服务（RDS / ElastiCache / MSK）的 `resources` 行由各自的 agg 另行组装，
字段清单见 `sample-solve.md` 的托管服务小节；`service` 分别填
`rds` / `elasticache` / `msk`，与 EC2 行**放进同一个 `resources` 数组**一次判完。

**取哪一档，逐字段不同**——主判据限 `biz-hours`，否决项与下限型取 `full-window`：

| 字段 | 指标 / stat | 取哪一档 |
|---|---|---|
| `sample_n`、`dbload_p95`、`engine_cpu_p95`、`cpu_total_p95` | 各服务主判据 / `Average` | **`biz-hours`** 的 p95 与 n |
| `under_replicated_p95` | `UnderReplicatedPartitions` / `Average` | **`full-window`** 的 p95 |
| `repl_lag_p95` | `ReplicationLag` / `Average` | **`full-window`** 的 p95 |
| `evictions_p95` | `Evictions` / **`Sum`** | **`full-window`** 的 p95 |
| `under_replicated_max`、`repl_lag_max`、`evictions_sum` | 同上 / `Maximum` | **`full-window`** 的 max（写进 `blockers` 的尖峰值） |
| `freeable_mem_min_gib` | `FreeableMemory` / `Minimum` | **`full-window`** 的 min（**改**：原为 `biz-hours`） |
| `disk_used_max`、`handler_idle_p95` | MSK 前置指标 | `full-window` |

三个 `*_p95` 是**可选**字段：不送时 `core.py` 回退到对应的 `*_max`，
行为与加这三个字段之前逐字节相同。送了才享受「尖峰不否决」。

**这张表必须配一份可执行样例，不能只留散文。** 本仓库自己的规律是
「有代码/样例载体的判据一次就对；只有散文描述的判据全部出过问题」
（`sample-solve.md` 开头）—— 而这张表**第一次被实现就踩了**：
按它写的第一个组装把三个 `*_p95` 全取成了 `biz-hours`（`worst_p95` 的默认档），
而 `biz-hours` 上 URP/Average 结构性为 0（实测某集群 242 个点平铺 0，
真实 under-replication 全在 off-hours）⇒ 否决项形同失效。

托管三服务的 `*_p95` / `*_max` / 下限型字段，逐档取值：

```bash
# 输入：$M/agg-<svc>.json（agg.jq 产出，含 full-window 档）
# 输出：{rid: {字段: 值}}，直接 merge 进 solver-in 的托管行
cat > $O/managed-bands.jq <<'JQ'
def rid0: .rid | split("@")[0];
def mn:   .rid | split("@")[1];
# 显式带档取一格。**档位写死在调用处**，不给默认值——
# 默认值就是上面那次事故的成因。
def at($rows; $m; $st; $bk; $f):
  [ $rows[] | select(mn == $m and .stat == $st and .bucket == $bk) | .[$f] ]
  | if length == 0 then null else max end;      # 多 broker/多节点取最坏者
group_by(rid0)[]
| { rid: (.[0] | rid0), rows: . }
| .rows as $r
| { (.rid): {
      # ---- 否决项的持续值：**full-window**，gauge 用 Average、计数类用 Sum ----
      under_replicated_p95: at($r; "UnderReplicatedPartitions"; "Average"; "full-window"; "p95"),
      repl_lag_p95:         at($r; "ReplicationLag";            "Average"; "full-window"; "p95"),
      evictions_p95:        at($r; "Evictions";                 "Sum";     "full-window"; "p95"),
      # ---- 否决项的尖峰值：**full-window** 的 max，只进 blockers ----
      under_replicated_max: at($r; "UnderReplicatedPartitions"; "Maximum"; "full-window"; "max"),
      repl_lag_max:         at($r; "ReplicationLag";            "Maximum"; "full-window"; "max"),
      evictions_sum:        at($r; "Evictions";                 "Maximum"; "full-window"; "max"),
      # ---- 下限型：**full-window** 的 min（内存低点常在 off-hours 的备份窗口）----
      freeable_mem_min_raw: at($r; "FreeableMemory";            "Minimum"; "full-window"; "min"),
      # ---- 主判据：**biz-hours**（这一档才是业务负载的口径）----
      dbload_p95:      at($r; "DBLoad";                   "Average"; "biz-hours"; "p95"),
      engine_cpu_p95:  at($r; "EngineCPUUtilization";     "Average"; "biz-hours"; "p95"),
      cpu_total_p95:   at($r; "CpuUserPlusSystem";        "Average"; "biz-hours"; "p95"),
      sample_n:        at($r; "DBLoad";                   "Average"; "biz-hours"; "n") } }
JQ

jq -s -c 'add' $(jq -n --arg m "$M" '[$m+"/agg-rds.json"]' | jq -r '.[]')   | jq -c -f $O/managed-bands.jq | jq -s -c add > $O/managed-bands-rds.json
```

**自检（照抄，别跳）**：三个 `*_p95` 若与同键的 `biz-hours` p95 逐值相同，
且该指标在 off-hours 有非零 max，就说明档位取错了：

```bash
jq -r --slurpfile a $M/agg-msk.json '
  $a[0] | group_by(.rid) | .[]
  | select(.[0].rid | endswith("@UnderReplicatedPartitions"))
  | { rid: .[0].rid,
      biz:  (map(select(.stat=="Average" and .bucket=="biz-hours"))   | .[0].p95),
      full: (map(select(.stat=="Average" and .bucket=="full-window")) | .[0].p95),
      off_max: (map(select(.stat=="Maximum" and .bucket=="off-hours")) | .[0].max) }
  | select(.off_max > 0 and .biz == .full)
  | "WARN 档位可疑（off-hours 有非零 max 而 biz 与 full 的 p95 相同）: \(.rid)"'   /dev/null
# 有输出时先确认是真同值还是取错档，再往下走
```

`freeable_mem_min_gib` 改取全窗口的理由：它是**下限型**判据（最小值低于实例内存
`rds_freeable_mem_floor_pct`% ⇒ 降配会 OOM），而内存低点常落在备份/批处理的
`off-hours`。只取 `biz-hours` 会把真实低点漏掉（实测两台 RDS 偏高 0.18% 与
1.1%，本机队未跨越地板但方向是**把危险实例判成安全**）。

⑤ 的实测覆盖率：两个验证 region 都是 **2/13** —— 绝大多数实例
`required_gib = cur_gib`（内存不动），`confidence` 上限 `medium`。
（us-west-2 的分母是 `solver-in.json` 的 13 行，不是机队的 18 台；
`metrics-catalog.md` 那份 `2/18` 是**机队**口径，两者分母不同、都对。
实测那 5 台 EKS 节点一台都没发布 `mem_used_percent`，所以分子不变。）
这不是缺陷，是 `thresholds.md` 里"无内存数据则不动内存"决策的正常后果，
但必须写进报告缺口。

`sus_mem`/`peak_mem` 为 `null` 时**不要在这里填地板值**——那是替实例做假设。
