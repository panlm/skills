# Partition 差异（aws / aws-cn）

## 检测

```bash
aws sts get-caller-identity --query Arn --output text | cut -d: -f2
```
→ `aws` 或 `aws-cn`

## 机型与 node type 集合：不维护静态表

一律在目标账号内运行时查询：

| 对象 | 查询 |
|---|---|
| EC2 / EKS 节点 | `ec2 describe-instance-type-offerings --location-type region` |
| 机型规格 | `ec2 describe-instance-types`（全量落盘再本地 join） |
| RDS | `rds describe-orderable-db-instance-options`（须 pin `--engine-version`） |
| ElastiCache | `elasticache describe-reserved-cache-nodes-offerings` |
| 按需价目 | `pricing get-products`（过滤 regionCode / Linux / Shared / NA / Used） |

中国区机型集合显著小于全球区，但集合是运行时发现的，候选筛选会自动收窄，
无需预置清单。

## 行为差异

| 项 | aws | aws-cn |
|---|---|---|
| endpoint 后缀 | `.amazonaws.com` | `.amazonaws.com.cn` |
| pricing API endpoint | `us-east-1`（全局） | **须核实**：中国区 pricing API 可用性与 endpoint |
| 候选集规模 | 大 | 明显更小，`已合理配置` 结论会更多 |
| 币种 | USD | **CNY**，金额列须标注币种 |
| legacy 清单 | 通用 | 通用（机型族划分与 partition 无关） |
| baseline_pct 表 | 通用 | 通用（T 系列基线是产品特性，与 partition 无关） |
| 用途分类 | 通用 | 通用 |

## 待核实项（中国区）

- pricing API 在中国区的可用性、endpoint、以及返回的币种字段名
- 中国区是否提供 `t4g` / Graviton 机型（影响 burstable 候选与同架构约束）
- 中国区可用机型集合（运行时查询即可，但首次运行需人工抽查合理性）

**未核实前不得假定中国区与全球区一致。** 金额列若币种标注错误，
会让客户按错误汇率理解节省额。
