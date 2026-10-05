# EBS 取价回包 → core.gp3_plan() 要的单价。吞吐单价保留原单位，
# 换算交给 core.gp3_tput_price_per_mibps()（单位是 GiBps-mo，当成每 MiB/s 会高估 1024 倍）。
#
# 参数: --slurpfile g2 <gp2 回包投影>  --slurpfile g3 <gp3 回包投影>
#   两份投影都是 [{fam, ut, unit, usd}]（见 cli-recipes.md §6.1 的 EBS 取价命令）
# 产出: {gp2_gb_mo, gp3_gb_mo, gp3_iops_mo, gp3_tput_usd, gp3_tput_unit}
#
# **每个 productFamily 恰好一条才取**，否则给 null ⇒ gp3_plan 判 price-unknown。
# 不取第一条：同一 family 多条说明回包里混进了别的东西（Local Zone、Outposts 之类），
# 随机取一条就是 ALB `-TS-` 那个坑（SKILL.md 易错项速查）。
def one($rows; $fam):
  [ $rows[] | select(.fam == $fam) ] | if length == 1 then .[0] else null end;
def usd($r): if $r == null then null else $r.usd end;
one($g2[0]; "Storage") as $s2
| one($g3[0]; "Storage") as $s3
| one($g3[0]; "System Operation") as $io
| one($g3[0]; "Provisioned Throughput") as $tp
| { gp2_gb_mo: usd($s2), gp3_gb_mo: usd($s3), gp3_iops_mo: usd($io),
    gp3_tput_usd: usd($tp),
    gp3_tput_unit: (if $tp == null then null else $tp.unit end) }
