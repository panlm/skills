# MSK 专用查询生成器 —— 逐 broker 展开 + CPU 用 metric math 逐点相加
#
# 输入: inventory/msk-eval.json  [{id, type, broker_ids, ...}]
#   broker_ids 必须来自 `kafka list-nodes`，**不得由 brokers 计数生成 1..N**。
#   取法见 cli-recipes.md §1.1 ⑤（本文件不复述那条命令）。
#
#   为什么不能生成 1..N：broker 被替换后 ID 不保证从 1 连续排到 N，
#   `range(1; N+1)` 会取到不存在的 Broker ID。而维度值错误时
#   `get-metric-data` **返回空序列且不报错**——错误表现为"这个 broker 没数据"，
#   与真的没数据无法区分，于是降配前置条件被静默判为不满足、建议被吞掉。
#   本文件因此 fail-closed：缺 broker_ids 直接 error，不退化成计数生成。
#
#   两个实测坑（都在 §1.1 ⑤ 的命令里处理掉了）：
#   ① list-nodes 返回 BrokerId 为浮点（实测 `1.0` / `2.0`），而 CloudWatch 的
#      `Broker ID` 维度要字符串 "1"。直接拼 "1.0" 会取不到数据且不报错。
#   ② list-nodes **不保证有序**：实测某 3-broker 集群返回 `2 1 3`。
#      顺序影响 Label 与 Id 的排列，须先 sort -n 再落盘。
# 产出: MetricDataQueries 数组
#
# 三件 MSK 专有的事，每件都踩过：
#
# 1. **维度名带空格**：`Cluster Name`、`Broker ID`。写成 ClusterName 返回空序列不报错。
#    `Broker ID` 的值是字符串形式的 broker 序号，**逐个来自 broker_ids**，
#    不是 1..NumberOfBrokerNodes 的推导值（见上）。
#
# 2. **CPU 必须用 metric math `Expression: "m1+m2"` 逐点相加**。
#    MSK 没有单一的 CPU 利用率指标，判据是 CpuUser + CpuSystem。
#    分别聚合再相加是错的 —— 两序列各自的 p95 之和 ≠ 和的 p95。
#    被加数设 `ReturnData: false` 避免多余传输。
#    实测对比（某 broker，biz-hours）：metric math p95=5.45 / max=41.82，
#    分别算再相加 p95=5.495 / max=41.817。该例只差 0.8% 是因为两序列峰值恰好同时
#    出现，属运气不是通例；峰值错开时误差会显著放大。
#
# 3. **同 namespace 内刻度不统一**，判据刻度写错会让它永不成立、建议被静默吞掉：
#    KafkaDataLogsDiskUsed 是 0–100，RequestHandlerAvgIdlePercent 是 **0–1**。
#    见 thresholds.md。
#
# RequestHandlerAvgIdlePercent 在 EnhancedMonitoring=DEFAULT 下**不发布**
# （实测：list-metrics 返回空，而同集群的 CpuUser / KafkaDataLogsDiskUsed /
# UnderReplicatedPartitions 在 DEFAULT 下都有 per-broker 数据）。
# 该指标缺失 ⇒ 降配前置条件无法评估 ⇒ 不产出降配建议。
# 报告缺口「把 EnhancedMonitoring 提到 PER_BROKER 再等一个窗口」**只在同形态下
# 确实存在更便宜的候选机型时才写**：core.py 的 eval_msk 先查
# cheaper_candidate_exists，为假则直接「已合理配置」、不再要求任何前置指标
# （实测 kafka.t3.small 就是这种情况，补了指标也不会有建议）。
# 本文件不复述判据顺序，见 core.py 的 eval_msk。
if any(.[]; (.broker_ids|type) != "array" or (.broker_ids|length) == 0)
then error("msk inventory 缺 broker_ids，见 cli-recipes.md §1.1 ⑤："
           + ([.[] | select((.broker_ids|type) != "array"
                            or (.broker_ids|length) == 0) | .id] | tostring))
else . end
| ["KafkaDataLogsDiskUsed","RequestHandlerAvgIdlePercent",
 "UnderReplicatedPartitions","MemoryUsed","BytesInPerSec"] as $SIMPLE
| ["Average","Maximum"] as $STATS
| [ to_entries[] as $c
    | $c.value.broker_ids[] as $b
    | [ {Name:"Cluster Name", Value:$c.value.id},
        {Name:"Broker ID",    Value:($b|tostring)} ] as $d
    | range(0; ($STATS|length)) as $i
    | "\($c.key)_\($b)_\($i)" as $k
    | [ # 被加数不回传
        { Id:"cu\($k)", ReturnData:false,
          MetricStat:{Metric:{Namespace:"AWS/Kafka",MetricName:"CpuUser",Dimensions:$d},
                      Period:3600, Stat:$STATS[$i]} },
        { Id:"cs\($k)", ReturnData:false,
          MetricStat:{Metric:{Namespace:"AWS/Kafka",MetricName:"CpuSystem",Dimensions:$d},
                      Period:3600, Stat:$STATS[$i]} },
        # 逐点相加后的合成序列才是判据输入
        { Id:"cpu\($k)", ReturnData:true,
          Expression:"cu\($k)+cs\($k)",
          Label:"\($c.value.id)-b\($b)@CpuUserPlusSystem|\($c.value.type)|\($STATS[$i])" } ]
      + [ $SIMPLE | to_entries[]
          | { Id:"m\($k)_\(.key)",
              Label:"\($c.value.id)-b\($b)@\(.value)|\($c.value.type)|\($STATS[$i])",
              MetricStat:{Metric:{Namespace:"AWS/Kafka",MetricName:.value,Dimensions:$d},
                          Period:3600, Stat:$STATS[$i]} } ] ]
| flatten
