# agg 产出 + 范围清单 → core.gp3_plan() 的 vol 数组，一卷一条。
#
# 参数: --slurpfile agg <agg-ebs.json>   （agg.jq 产出，含 full-window 档）
#       --argjson win <窗口应有点数 = WINDOW_DAYS × 24>   **必传**：jq 引用未定义的变量是
#       编译期错误，`//` 兜不住（SKILL.md 易错项速查）
# 输入: ebs-gp2-eval.json（§2.7 ① 的范围清单）
#
# **遍历方向是范围清单，不是 agg。** 以 agg 为主循环会让「一个指标都没采到」的卷
# 整条消失，而那恰恰是要走 missing-parity 兜底的那一类（非 Nitro 宿主）。
# **只取 full-window 档**：gp3 的配置 24 小时生效，夜间备份被限流同样是事故。
# 取值一律显式判 null，不用 `//`：0 是有效值（零 IO 的卷）。
def rid0: .rid | split("@")[0];
def mn:   .rid | split("@")[1];
def at($rows; $m; $st; $f):
  [ $rows[] | select(mn == $m and .stat == $st and .bucket == "full-window") | .[$f] ]
  | if length == 0 then null else .[0] end;
# 触顶序列只有 0 / 1，mean × n 恰为取 1 的小时数（与 §7 求 Σ Sum 同一个恒等式）；
# round 去掉浮点残差，否则 blocker 里会出现 27.000000000000004 小时。
def hours($rows; $m):
  [ $rows[] | select(mn == $m and .stat == "Maximum" and .bucket == "full-window")
    | .mean * .n ]
  | if length == 0 then null else (.[0] | round) end;
# 覆盖度：full-window 档各序列点数的最小值。卷在窗口内新建或换过宿主（lm-ebs-attached.jq
# 丢掉旧宿主那条序列）时它小于 $win —— gp3_plan 据此写一条覆盖不足的 blocker，不改结论。
def coverage($rows):
  [ $rows[] | select(.bucket == "full-window") | .n ] | if length == 0 then null else min end;
($agg[0] | group_by(rid0) | map({key: (.[0] | rid0), value: .}) | from_entries) as $BY
| map(
    . as $v
  | (if $BY[$v.id] == null then [] else $BY[$v.id] end) as $r
  | { rid: $v.id, size_gib: $v.size,
      sus_iops:  at($r; "VolumeAvgIOPS"; "Average"; "p95"),
      peak_iops: at($r; "VolumeAvgIOPS"; "Maximum"; "max"),
      sus_kibs:  at($r; "VolumeAvgThroughput"; "Average"; "p95"),
      peak_kibs: at($r; "VolumeAvgThroughput"; "Maximum"; "max"),
      iops_exceeded_p95:   at($r; "VolumeIOPSExceededCheck"; "Maximum"; "p95"),
      iops_exceeded_hours: hours($r; "VolumeIOPSExceededCheck"),
      tput_exceeded_p95:   at($r; "VolumeThroughputExceededCheck"; "Maximum"; "p95"),
      tput_exceeded_hours: hours($r; "VolumeThroughputExceededCheck"),
      sample_n: coverage($r), window_points: $win } )
