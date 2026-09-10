# 多维度指标的查询生成器：维度组合直接取自 list-metrics 的回包
#
# 用于 CWAgent 这类**必须提供发布时全部维度**的指标。少一个维度返回空序列且不报错，
# 症状看起来像"该 region 没有这类资源"。所以不要自己拼维度，一律用本文件从
# list-metrics 的输出原样搬。
#
# 参数（**五个全部必传，本文件没有任何默认值**）:
#   --arg mn      <指标名，写进 Label 第一段>
#   --arg idname  <维度里代表资源 id 的维度名，如 InstanceId / CacheClusterId>
#   --argjson ty  '{"<rid>":"<规格标签>"}'   把 rid 映射到机型，写进 Label 第二段
#   --argjson stats '["Average","Maximum"]'
#   --arg idprefix <字符串>  Id 前缀，合并多批时必须各不相同
#
# **五个都必传，不能靠 `$x // 默认值` 兜。** jq 里引用未定义的 `$var` 是
# **编译期错误**，不会退化成 null，`//` 根本执行不到——整个程序在求值前就死了。
# 实测漏传 `--arg idprefix` 的原始报错（行号会随本文件改动漂移，故不抄）：
#   jq: error: $idprefix is not defined at <top-level>, ...
#   jq: 1 compile error
# 漏传 `--argjson stats` 同理（`$stats is not defined`）。
#
# Id 撞名是本 skill 唯一一个**会让命令直接失败**的错（其余多为静默失败）：
# 本文件的 Id 形如 <prefix><index>_<stat>，两批各自从 0 编号，
# 直接 `jq -s add` 合并会 Id 重复 ⇒ ValidationError: The values for parameter id
# in MetricDataQueries are not unique。mem 与 disk 两批必须传不同 idprefix。
#
# 输入: aws cloudwatch list-metrics --namespace X --metric-name Y 的原始 JSON
# 产出: MetricDataQueries 数组
#
# $ty 里没有的 rid 会被丢掉 —— 用于过滤掉已终止实例残留的指标。
$stats as $ST
| [ .Metrics | to_entries[] as $e
    | ($e.value.Dimensions | map(select(.Name == $idname)) | .[0].Value) as $rid
    | select($rid != null and $ty[$rid] != null)
    # 同一实例内可有多条序列（如 disk_used_percent 每挂载点一条）。把除 id 外
    # 所有区分性维度编进 Label，否则撞名。
    | ( [ $e.value.Dimensions[] | select(.Name != $idname)
          | select(.Name | IN("path","device","fstype","mode")) | .Value ]
        | if length > 0 then "#" + join("#") else "" end ) as $SUF
    | range(0; ($ST|length)) as $i
    | { Id: "\($idprefix)\($e.key)_\($i)",
        # Label 必须含**所有能区分同一实例内多条序列**的维度，否则撞名。
        # 实测 disk_used_percent 单实例 6 条序列（每挂载点一条）；只用 rid@metric
        # 会全部撞名，后果二选一：跑重复 Label 断言被阻断，或跳过断言后
        # agg.jq 静默只留一个挂载点。
        # 另有更细的情形：同一 path 可挂在不同 device（如 /snap/... 同时在
        # loop7 与 loop10），故 path 与 device 都要编进去。
        Label: "\($rid)\($SUF)@\($mn)|\($ty[$rid])|\($ST[$i])",
        MetricStat: { Metric: { Namespace: $e.value.Namespace,
                                MetricName: $e.value.MetricName,
                                Dimensions: $e.value.Dimensions },
                      Period: 3600, Stat: $ST[$i] } } ]
