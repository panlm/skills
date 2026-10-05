# list-metrics 回包只留「当前挂载」那一条序列。
#
# AWS/EBS 的 VolumeAvgIOPS / VolumeAvgThroughput / *ExceededCheck 维度是
# VolumeId + InstanceId。卷在窗口内换过宿主时，list-metrics 会同时回旧宿主与新宿主
# 两条序列；mdq-dims.jq 的 Label 只编卷 ID（`<vol>@<metric>|gp2|<stat>`），两条必然
# 撞名 ⇒ §2 的重复 Label 断言阻断整批采集。判据要的是「现在这台宿主上的用量」，
# 所以只取当前挂载那条；范围清单外的卷也在这里一并丢掉。
#
# 参数: --slurpfile vols <ebs-gp2-eval.json>   （§2.7 ① 的范围清单，含 .id 与 .attach）
# 输入: aws cloudwatch list-metrics --namespace AWS/EBS --metric-name X 的原始 JSON
# 产出: 同形 JSON（只删 Metrics 里的条目），直接喂 mdq-dims.jq
($vols[0] | map({key: .id, value: .attach}) | from_entries) as $att
| .Metrics |= map(
    (.Dimensions | map({key: .Name, value: .Value}) | from_entries) as $d
    | select($d.InstanceId != null and $att[$d.VolumeId] == $d.InstanceId))
