# 多指标 GetMetricData 查询生成器（单维度指标通用）
#
# 参数:
#   --argjson metrics '[{"ns":"AWS/RDS","mn":"DBLoad","dim":"DBInstanceIdentifier"},
#                       {"ns":"AWS/RDS","mn":"FreeableMemory","dim":"DBInstanceIdentifier",
#                        "stats":["Average","Maximum","Minimum"]}]'
#   --arg idkey   <inventory 中作为资源 id 的字段名>
#   --arg typekey <inventory 中作为规格标签的字段名>
#
# 输入: inventory 数组
# 产出: MetricDataQueries 数组
#
# Label 三段式 "<rid>@<metric>|<type>|<stat>" —— 指标名必须编进第一段。
# agg.jq 按 "|" split 成 [rid, itype, stat] 三段；给四段会让 stat 被指标名占掉，
# Average/Maximum 的区分整个丢失（实测踩过）。
#
# 每指标默认只取 Average + Maximum。需要窗口最小值的指标（RDS FreeableMemory、
# CPUCreditBalance）用 "stats" 显式加 "Minimum"，agg.jq 会输出对应的 min 列。
#
# Id 必须匹配 ^[a-z][a-zA-Z0-9_]*$，故加 q 前缀。
[ to_entries[] as $e
  | $metrics | to_entries[] as $m
  | (($m.value.stats) // ["Average","Maximum"]) as $stats
  | range(0; ($stats|length)) as $i
  | { Id: "q\($e.key)_\($m.key)_\($i)",
      Label: "\($e.value[$idkey])@\($m.value.mn)|\($e.value[$typekey])|\($stats[$i])",
      MetricStat: { Metric: { Namespace: $m.value.ns, MetricName: $m.value.mn,
                              Dimensions: [ {Name: $m.value.dim, Value: $e.value[$idkey]} ] },
                    Period: 3600, Stat: $stats[$i] } } ]
