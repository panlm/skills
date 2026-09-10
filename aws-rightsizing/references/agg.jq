# 输入: cloudwatch get-metric-data 的原始响应
# 参数: --argjson tz <业务时区偏移秒数>   例 UTC+8 => 28800
# 输出: 每 (resource, stat, bucket) 一个对象的数组
#
# 依赖 Label 格式 "<resource_id>|<type>|<stat>"（见 cli-recipes.md §2）。
# GetMetricData 响应不回显 Dimensions，只回显 Label，把身份编进 Label 可免去 join。

# AWS CLI v2 时间戳格式受 cli_timestamp_format 影响：可能带本地偏移(+08:00)
# 也可能以 Z 结尾。两种都要处理，不能假定 Z——实测输出为 +08:00 形式。
def parse_ts:
  if test("Z$") then fromdateiso8601
  elif test("[+-][0-9]{2}:[0-9]{2}$") then
    ( capture("^(?<b>.*)(?<sg>[+-])(?<oh>[0-9]{2}):(?<om>[0-9]{2})$")
      | ((.b + "Z") | fromdateiso8601)
        - ( ((.oh|tonumber)*3600 + (.om|tonumber)*60)
            * (if .sg == "+" then 1 else -1 end) ) )
  else (. + "Z" | fromdateiso8601) end;

def bucket(e):
  (e + $tz) as $l
  | ($l | strftime("%u") | tonumber) as $dow
  | ($l | strftime("%H") | tonumber) as $h
  | if $dow >= 6 then "weekend"
    elif $h >= 9 and $h < 20 then "biz-hours"
    else "off-hours" end;

def pct(p): sort | if length == 0 then null else .[ (((length-1) * p) | floor) ] end;

[ .MetricDataResults[]
  | select((.Timestamps | length) > 0)
  | (.Label | split("|")) as $L
  | { rid: $L[0], itype: $L[1], stat: $L[2],
      pts: [ range(0; (.Timestamps | length)) as $i
             | { b: bucket(.Timestamps[$i] | parse_ts), v: .Values[$i] } ] }
  | .rid as $rid | .itype as $it | .stat as $st
  # 三档 + 一个 full-window 档。full-window **不是**三档的算术合并：
  # n 与 max 可以合并，但 p95 与 mean 不行（并集的 p95 ≠ 各档 p95 的 max）。
  # 否决项判持续态要的正是全窗口 p95，下限型判据要的是全窗口 min，
  # 所以这一档必须在这里出，不能让调用方在 jq 里拿三档去凑。
  | ( ( [ { b: "full-window", pts: .pts } ]
        + ( .pts | group_by(.b) | map({ b: .[0].b, pts: . }) ) )[]
      | .b as $b | .pts as $ps
      | { rid: $rid, itype: $it, stat: $st, bucket: $b, n: ($ps | length),
          mean: (($ps | map(.v) | add) / ($ps | length)),
          p95:  ($ps | map(.v) | pct(0.95)),
          max:  ($ps | map(.v) | max),
          # min 是给"下限型"判据用的：RDS 的 FreeableMemory 阻断
          # （最小值 < 实例内存的 rds_freeable_mem_floor_pct% ⇒ 降配会 OOM）、
          # burstable 的 CPUCreditBalance
          # 是否触底。这类判据要的是窗口最小值，不是 max/p95，用后者会反向误判。
          # 采集时须对这些指标显式加 Stat=Minimum（见 mdq-multi.jq 的 "stats"），
          # 否则这里算的是"每小时均值的最小值"，仍会高于真实低点。
          min:  ($ps | map(.v) | min) } ) ]
