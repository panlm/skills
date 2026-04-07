# 当 AI Agent 遇见混沌工程：专业能力的普惠化实践

## 一、专业能力的门槛问题

在技术领域，有一类能力被称为"专家专属"——大家都知道重要，但实际做的人很少。混沌工程就是典型例子。

2011 年，Netflix 开源了 Chaos Monkey，开启了混沌工程的先河。此后，这个理念逐渐被业界认可：与其等待生产环境出问题，不如主动注入故障，验证系统的韧性（Resilience）。AWS 在 2021 年推出了 Fault Injection Service (FIS)，让混沌工程变得更加标准化和易于管理。

然而，十多年过去了，真正在团队中常规化实施混沌工程的组织仍然是少数。

为什么？不是不想做，而是**门槛太高**。

这是很多专业工具的共同困境：工具本身很强大，但要用好它，你得先成为这个工具的专家。对于混沌工程来说，你需要理解 FIS 的概念模型、熟悉几十种 action 的适用场景、掌握 Scenario Library 的配置方式、了解各种资源的兼容性要求……这条学习曲线，足以让很多团队望而却步。

但如果有另一种可能呢？

如果专业知识可以被"封装"到 AI Agent 中，用户只需描述意图，Agent 负责选择工具、配置参数、执行操作——这不是"替代专家"，而是"让非专家也能做专家的事"。

本文以混沌工程为例，展示这种范式转变的具体实践：三个Agent Skill 如何让任何工程师都能完成 EKS 故障演练，从"先学 FIS 才能做实验"到"描述意图就能做实验"。

---

## 二、旧范式的困境：为什么混沌工程难以普及

### 困境一：FIS 学习门槛高

AWS FIS 功能强大，但学习曲线陡峭：

- **Action 众多** —— 几十种 action，每种对应不同服务和故障类型，选哪个？
- **兼容性隐蔽** —— 某些 action 只适用特定资源类型（如 `failover-db-cluster` 只能用于 Aurora），配置时不会提醒，启动时才报错
- **Scenario Library 复杂** —— 4 种复合场景的 JSON 模板无法通过 API 生成，需要从文档手动提取

从"我想测试 AZ 故障"到写出正确的 experiment template，新手需要走完：理解概念 → 选择 action → 了解兼容性 → 编写模板。这条路不短也不易。

### 困境二：应用层影响的观测盲区

即使你成功完成了一次 FIS 实验，挑战还没结束。

FIS 的实验报告只提供基础设施视角：RDS failover 耗时 30 秒，ElastiCache 节点恢复正常……但应用呢？

- 连接池断开了多久？
- 重试机制生效了吗？
- 用户看到错误页面了吗？
- 应用恢复正常花了多长时间？

这些问题，FIS 报告回答不了。你需要手动收集 kubectl logs，与实验时间线对齐，逐一分析。这个过程繁琐且容易遗漏关键信息。

混沌工程的真正价值不在于"注入了故障"，而在于"理解系统如何响应故障"。如果观测能力跟不上，实验的价值就大打折扣。

---

## 三、新范式的实践：AI Agent 如何封装专业能力

我们开发了三个 Claude Code Agent Skill，形成一个端到端的混沌工程流水线：

```
aws-fis-experiment-prepare → aws-fis-experiment-execute → eks-app-log-analysis
         准备                        执行                      分析
```

这三个 Skill 的设计理念是：**把 FIS 专业知识封装到 Agent 中，用户只需用自然语言描述意图**。

### Skill 1：aws-fis-experiment-prepare

**解决问题：** FIS 学习门槛高

**工作方式：**

用户只需描述测试意图，例如：
- "准备一个 AZ 断电实验，目标是 us-east-1a"
- "我想测试 RDS 故障转移对应用的影响"
- "帮我设置一个 EKS Pod 网络延迟的实验"

Agent 会自动完成以下工作：

1. **理解意图，选择方案** —— 根据用户描述，判断应该使用哪个 FIS action 或 Scenario Library 场景
2. **查询资源，验证兼容性** —— 调用 AWS CLI 发现目标资源，检查资源类型与 action 的兼容性
3. **读取文档，获取模板** —— 对于 Scenario Library 场景，自动读取 AWS 文档提取 JSON 模板（这些模板无法通过 API 生成）
4. **生成配置目录** —— 输出完整的配置目录，包括 experiment template、IAM policy、CloudFormation 模板、CloudWatch 告警和 Dashboard。**这个目录将作为下一个 Skill 的输入**
5. **部署基础设施** —— 执行 CloudFormation 部署，创建所需的 IAM 角色、告警和实验模板

**额外亮点：自愈式部署。** CloudFormation 部署经常因为各种原因失败（IAM 传播延迟、区域限制、属性验证错误）。Agent 会自动分析错误原因、修复模板、删除失败的栈、重新部署，最多重试 5 次。用户不需要看 CloudFormation 错误日志。

**核心价值：** 用户不需要学习 FIS action 的细节，不需要知道 `failover-db-cluster` 和 `reboot-db-instances` 的区别，只需要描述"我想测什么"。Skill 之间通过配置目录传递上下文，形成完整的工作流。

### Skill 2：aws-fis-experiment-execute

**功能：** 安全执行实验 + 自动发现依赖 + 监控 + 结果报告

FIS 实验会影响真实的生产资源。这个 Skill 的设计原则是：**安全第一，绝不自动启动**。

工作流程：
1. 验证 CloudFormation 栈状态，确认部署成功
2. 提取实验模板 ID
3. **自动发现应用依赖** —— 分析实验目标资源，发现哪些应用依赖这些服务（如哪些 Pod 连接 RDS、哪些服务使用 ElastiCache）
4. **展示影响范围，要求用户明确确认** —— 显示目标资源、受影响应用、影响区域、预计时长
5. 用户确认后才启动实验
6. 轮询实验状态，提醒用户查看 CloudWatch Dashboard
7. 生成结果报告：按服务分组的影响分析，包括时间线、观察和关键发现

### Skill 3：eks-app-log-analysis

**解决问题：** 应用层观测盲区

**工作方式：**

支持两种模式：
- **实时监控** —— 实验进行中，每 30 秒展示日志洞察
- **事后分析** —— 实验结束后，基于时间范围批量分析

Agent 会：
1. 读取实验上下文，了解涉及哪些 AWS 服务
2. 询问用户：哪些应用依赖这些服务？
3. 自动收集相关应用的 kubectl logs
4. 生成应用层分析报告：
   - 错误时间线（与 FIS 事件对齐）
   - 错误模式统计
   - 恢复时间分析
   - 跨服务关联

**核心价值：** 补全了 FIS 报告缺失的"应用视角"，让混沌工程的分析从基础设施延伸到业务影响。

---

## 四、范式转变的效果

### 对比：谁能做混沌工程？

| 维度 | 旧范式（手工） | 新范式（Agent Skill） |
|------|---------------|----------------------|
| **前置知识** | 需要熟悉 FIS action、scenario、资源兼容性 | 只需描述测试意图 |
| **学习曲线** | 数小时到数天 | 几乎为零 |
| **执行时间** | 半天到一天（新手） | 10-15 分钟 |
| **谁能做** | FIS 专家或愿意投入学习的工程师 | 任何了解业务的工程师 |

这里的关键变化不是"快了多少倍"，而是**"原本不会做的人现在能做了"**。

当混沌工程的门槛从"需要专家"降低到"会描述意图"，它就有可能从"年度演练任务"变成"团队常规实践"。这才是 Resilience 工程的真正目标。

---

## 五、示例：实际报告展示

以下是通过 Agent Skill 完成的故障演练报告示例。

### 示例 1：Redis + MySQL 故障时的应用表现

这是一次同时测试 ElastiCache Redis AZ 电源中断和 RDS MySQL failover 的实验。以下是 `aws-fis-experiment-execute` 自动生成报告的核心内容：

---

#### Action Results

| Action | Action ID | Status | Start (UTC) | End (UTC) | Duration |
|---|---|---|---|---|---|
| InterruptElastiCacheAZPower | aws:elasticache:replicationgroup-interrupt-az-power | completed | 02:34:07 | 02:44:08 | 10 分 01 秒 |
| RebootRDSWithFailover | aws:rds:reboot-db-instances | completed | 02:34:07 | 02:34:08 | ~1 秒 (触发) |

#### Per-Service Impact Analysis

**ElastiCache Redis (demo-redis)**

| Time (UTC) | Event | Observation |
|---|---|---|
| 02:34:07 | FIS 触发 AZ 电源中断 | InterruptElastiCacheAZPower action 启动 |
| 02:34:07 | Redis 复制组进入 modifying 状态 | us-west-2a 节点断电 |
| 02:34:07 - 02:44:08 | 电源中断持续 10 分钟 | 复制组持续处于 modifying 状态 |
| 02:44:08 | FIS action 完成 | 电源恢复，节点开始恢复 |

**Key Findings:**
- checkout 应用在整个 Redis AZ 电源中断期间 **零错误**，证明 Redis 集群模式的跨 AZ 副本切换对应用完全透明
- 应用使用集群模式，客户端能自动重定向到健康节点

**RDS MySQL (demo-mysql)**

| Time (UTC) | Event | Observation |
|---|---|---|
| 02:34:07 | FIS 触发 RDS reboot with failover | RebootRDSWithFailover action 启动 |
| 02:34:13 | Multi-AZ failover 开始 | RDS 事件: "Multi-AZ instance failover started" |
| 02:34:14 | catalog 第一个 SQL 查询开始超时 | SELECT 查询开始挂起 (10s timeout) |
| 02:34:23 | 2 个 SQL 查询 10s 超时 | 返回 SocketTimeoutException |
| 02:34:23 | UI 首次 500 错误 | 级联到前端 |
| 02:34:26 | RDS 实例重启 (新 primary) | RDS 事件: "DB instance restarted" |
| 02:34:28-29 | catalog 连接错误爆发 | 4 次 `dial tcp: i/o timeout` |
| 02:34:34 | catalog 恢复正常 | 首个成功 200 响应 (1.2ms 延迟) |

**Key Findings:**
- RDS Multi-AZ failover 从触发到应用恢复总计约 **27 秒**
- 应用层实际中断时间约 **10 秒**
- DNS 切换后应用自动重连到新 primary，无需人工干预

**UI 前端 (间接受影响)**

| Time (UTC) | Event | Observation |
|---|---|---|
| 02:34:23 | 首次 500 错误 | `GET /catalog` → SocketTimeoutException |
| 02:34:28-33 | 500 错误集中爆发 | 7 个 500 错误，包括 `/catalog`, `/`, `/cart` 端点 |
| 02:34:34 | 恢复正常 | catalog 恢复后 UI 请求正常 |

**Key Findings:**
- UI 的 500 错误完全由 catalog 后端的 MySQL 连接超时级联导致
- 实验期间共 7 个 500 错误，影响范围有限

---

以下是 `eks-app-log-analysis` 自动生成的应用日志分析报告核心内容：

#### Summary

| Service | Application | Total Errors | Peak Error Rate | Recovery Time |
|---------|-------------|--------------|-----------------|---------------|
| ElastiCache Redis (demo-redis) | retail-store/checkout | 0 | 0/min | N/A (无影响) |
| RDS MySQL (demo-mysql) | retail-store/catalog | 5 (连接错误) + 2 (SQL超时) | ~42/min (02:34:23-02:34:33) | 02:34:34 (~27s) |
| UI (间接) | retail-store/ui | 7 (500 错误) | ~42/min (02:34:23-02:34:33) | 02:34:34 (~27s) |

#### Per-Service Application Analysis

**ElastiCache Redis — checkout (retail-store/checkout)**

Error Timeline: (无错误记录) — 整个实验期间未产生任何错误

Log Sample (正常请求):
```
2026-04-02T02:34:58 [Nest] 1 - LOG [HTTP] GET /checkout/135e77c9-... 200 1.715ms
2026-04-02T02:34:59 [Nest] 1 - LOG [HTTP] POST /checkout/1ed151bd-.../update 201 2.421ms
2026-04-02T02:35:06 [Nest] 1 - LOG [HTTP] GET /checkout/4e934791-... 200 1.936ms
```

**Insights:**
- checkout 应用在整个 10 分钟 Redis AZ 电源中断期间保持零错误，响应时间稳定在 1-3ms
- 这证明 ElastiCache Redis 集群模式 (2 分片 × 3 节点) 在单 AZ 故障场景下，对应用端完全透明
- 实验期间收集了 13,205 行日志，全部为正常 HTTP 200/201 响应

**RDS MySQL — catalog (retail-store/catalog)**

Error Timeline:

| Time (UTC) | Level | Message |
|------------|-------|---------|
| 02:34:23 | SLOW | `SELECT * FROM products WHERE id = '...' LIMIT 1` — 10000.098ms 超时 |
| 02:34:24 | SLOW | `SELECT * FROM tags ORDER BY display_name asc` — 10000.037ms 超时 |
| 02:34:28 | ERROR | `dial tcp 10.0.12.178:3306: i/o timeout` |
| 02:34:28 | ERROR | `dial tcp 10.0.12.178:3306: i/o timeout` |
| 02:34:29 | ERROR | `dial tcp 10.0.12.178:3306: i/o timeout` |
| 02:34:33 | ERROR | `dial tcp 10.0.12.178:3306: i/o timeout` |
| 02:34:34 | OK | 首次恢复: `GET /catalog/size?tags=` 200 1.225ms |

Log Sample (Critical Errors):
```
2026-04-02T02:34:24.152Z [10000.098ms] [rows:0] SELECT * FROM `products` WHERE id = '1ca35e86-...' LIMIT 1
2026-04-02T02:34:28.588Z /appsrc/repository/repository.go:151 dial tcp 10.0.12.178:3306: i/o timeout
2026-04-02T02:34:33.835Z /appsrc/repository/repository.go:151 dial tcp 10.0.12.178:3306: i/o timeout
```

**Insights:**
- RDS failover 触发后约 16 秒应用才感知到问题，因为已建立的连接需等待 10s 超时
- 02:34:28 开始出现 `dial tcp: i/o timeout`，说明旧 IP 已不可达，DNS 尚未完成切换
- 应用实际中断时间: **~10 秒** (02:34:23 → 02:34:34)
- 应用未实现 connection pool 的健康检查或快速重连机制

**UI — ui (retail-store/ui)**

Error Timeline:

| Time (UTC) | Level | Message |
|------------|-------|---------|
| 02:34:23 | ERROR | `500 Server Error for HTTP GET "/catalog"` — SocketTimeoutException |
| 02:34:28 | ERROR | `500 Server Error for HTTP GET "/"` — catalog 连接超时 |
| 02:34:28 | ERROR | `500 Server Error for HTTP GET "/catalog/4f18544b-..."` |
| 02:34:29 | ERROR | `500 Server Error for HTTP GET "/"` |
| 02:34:33 | ERROR | `500 Server Error for HTTP GET "/catalog"` |
| 02:34:33 | ERROR | `500 Server Error for HTTP GET "/cart"` |

Log Sample (Critical Errors):
```
2026-04-02T02:34:23.801Z ERROR 500 Server Error for HTTP GET "/catalog"
java.lang.RuntimeException: java.net.SocketTimeoutException: timeout
Caused by: java.net.SocketException: Socket closed
```

**Insights:**
- UI 的所有 500 错误均由 catalog 后端的 MySQL 连接超时级联导致
- UI 未实现降级策略，任何后端服务不可用都直接返回 500

---

### 示例 2：Pod 到数据库的网络延迟注入

在实际场景中，托管数据库可能包含多个 database 供不同应用使用，直接重启数据库影响范围太大。更精准的做法是：**对特定应用的 Pod 注入网络延迟**，模拟该应用到数据库的网络故障，而不影响其他应用。

以下是 `aws-fis-experiment-execute` 自动生成报告的核心内容：

---

#### Action 结果

| Action | Action ID | 状态 | 开始 (UTC) | 结束 (UTC) | 持续时间 |
|---|---|---|---|---|---|
| InjectNetworkLatency | aws:eks:pod-network-latency | completed | 04:49:08 | 04:54:36 | 5 分 28 秒 |

#### 各服务影响分析

**Catalog Pod (retail-store/catalog on demo-cluster)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 04:49:08 | Action 开始执行 | FIS 开始对 catalog Pod 注入 20s 网络延迟 |
| 04:49:23 | 首次错误出现 | `dial tcp 10.0.11.101:3306: i/o timeout` — 到 RDS 的连接超时 |
| 04:49:28 | context canceled 错误 | 4 次 context canceled — 请求在等待数据库响应时被上下文超时取消 |
| 04:49:28 | SQL 查询耗时 ~10s | SELECT 查询从正常 2-3ms 飙升至 9998-10001ms |
| 04:49:33 - 04:54:19 | 持续性故障 | 每 ~5 秒出现 2 个 timeout 错误，持续约 5 分钟 |
| 04:54:25 | 开始恢复 | 首次出现正常 200 响应，延迟恢复到 2-3ms |
| 04:54:36 | Action 完成 | FIS 停止故障注入 |

**关键发现:**
- 网络延迟注入后 **15 秒**内出现首次错误
- 错误模式稳定：每 5 秒 2 个 timeout 错误（分别来自 2 个 catalog Pod 副本）
- 数据库查询超时导致 **404** 响应（而非 500），说明应用将 "未找到数据" 与 "数据库错误" 混淆
- 恢复**几乎即时**：Action 停止后 ~10 秒内完全恢复正常
- 总计 **124 次错误**：120 次 i/o timeout + 4 次 context canceled

**UI (retail-store/ui) — 间接影响**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 04:49:23 | 首次级联错误 | UI 调用 catalog 服务超时，抛出 HTTPError |
| 04:49:23 - 04:54:19 | 持续性级联错误 | 2546 次错误/异常，主要为 HTTPError (1079) 和 ApiException (476) |
| 04:54:25 | 恢复 | UI 恢复正常页面渲染 |

**关键发现:**
- UI 的错误数 (2546) 远超 catalog 错误数 (124)，因为每个页面请求会触发多个 catalog 子调用
- UI 缺乏对 catalog 服务降级的优雅处理（无缓存回退、无默认页面）

---

以下是 `eks-app-log-analysis` 自动生成的应用日志分析报告核心内容：

#### 摘要

| 服务 | 应用 | 总错误数 | 峰值错误率 | 恢复时间 |
|------|------|---------|-----------|---------|
| Catalog (RDS) | retail-store/catalog | 124 | ~2次/5秒 | ~10 秒 |
| UI (Catalog) | retail-store/ui | 2546 | ~20次/5秒 | ~10 秒 |

#### 各服务应用分析

**Catalog 服务 (retail-store/catalog)**

错误时间线:

| 时间 (UTC) | 级别 | 消息 |
|-----------|------|------|
| 04:49:23 | ERROR | dial tcp 10.0.11.101:3306: i/o timeout |
| 04:49:28 | ERROR | context canceled (SQL查询 9998ms) |
| 04:49:28 | ERROR | context canceled (SQL查询 10001ms) |
| 04:49:28 | ERROR | dial tcp 10.0.11.101:3306: i/o timeout (SQL查询 5000ms) |
| ... | ... | 持续每5秒2次错误 ... |
| 04:54:19 | ERROR | dial tcp 10.0.11.101:3306: i/o timeout (最后一条错误) |

日志样本（关键错误）:
```
2026-04-02T04:49:23 /appsrc/repository/repository.go:187 dial tcp 10.0.11.101:3306: i/o timeout
  [5000.473ms] [rows:0] SELECT * FROM `products` WHERE id = '631a3db5-...' ORDER BY `products`.`id` LIMIT 1
  [GIN] 04:49:28 | 404 | 5.000589223s | GET "/catalog/products/631a3db5-..."
```

正常基线 vs 故障期间 vs 恢复后:
```
正常 (04:48:22): [GIN] | 200 | 2.402164ms | GET "/catalog/products/..."
故障 (04:49:28): [GIN] | 404 | 10.002248s | GET "/catalog/products/..."
恢复 (04:54:29): [GIN] | 200 |  2.809579ms | GET "/catalog/products/..."
```

**洞察:**
- 网络延迟(20s)远超应用连接超时(5s)，导致每次新连接必定失败
- 错误分布极为规律（每5秒2个），与 2 个 catalog Pod 副本的请求处理节奏一致
- 恢复后响应时间立即恢复到 2-3ms，说明应用没有连接池预热延迟问题

**UI 服务 (retail-store/ui)**

关键错误模式:

| 模式 | 次数 | 首次出现 | 最后出现 |
|------|------|---------|---------|
| HTTPError | 1079 | 04:49:23 | 04:54:19 |
| FluxOnError (Reactor 错误传播) | 828 | 04:49:23 | 04:54:20 |
| ApiException | 476 | 04:49:23 | 04:54:19 |
| SocketTimeoutException | 207 | 较早前 | 04:54:19 |

日志样本（关键错误）:
```
2026-04-02T04:49:23 com.amazon.sample.ui.client.catalog.models.httputil.HTTPError: null
  at OkHttpRequestAdapter.throwIfFailedResponse(OkHttpRequestAdapter.java:705)
```

**洞察:**
- UI 错误数 (2546) 是 catalog 错误数 (124) 的 **20 倍**，反映了典型的微服务级联放大效应
- 错误传播链: catalog 404 → OkHttp HTTPError → Kiota ApiException → Reactor FluxOnError → Thymeleaf TemplateProcessingException
- 没有观察到断路器或降级逻辑 — 所有 catalog 失败都直接传递给前端用户

---

### 示例 3：AZ 电源中断场景

这是最全面的混沌实验场景：模拟整个可用区 (us-west-2a) 的电源中断，同时影响 EC2 节点、ElastiCache、RDS 故障转移、网络连接和 ASG 扩容。这个场景包含 6 个并行 action，可以验证系统在真实 AZ 故障时的恢复能力。

以下是 `aws-fis-experiment-execute` 自动生成报告的核心内容：

---

#### Action Results

| Action | Action ID | Status | Start (UTC) | End (UTC) | Duration |
|---|---|---|---|---|---|
| Stop-EKS-Instances | aws:ec2:stop-instances | completed | 12:27:54 | 12:42:57 | 15m 3s |
| Pause-ASG-Scaling | aws:ec2:asg-insufficient-instance-capacity-error | completed | 12:27:54 | 12:42:54 | 15m 0s |
| Pause-ElastiCache | aws:elasticache:replicationgroup-interrupt-az-power | completed | 12:27:54 | 12:42:54 | 15m 0s |
| Pause-Instance-Launches | aws:ec2:api-insufficient-instance-capacity-error | completed | 12:27:55 | 12:42:55 | 15m 0s |
| Pause-Network-Connectivity | aws:network:disrupt-connectivity | completed | 12:27:54 | 12:42:55 | 15m 1s |
| Reboot-RDS-Failover | aws:rds:reboot-db-instances | completed | 12:27:55 | 12:27:56 | 1s |

#### 各服务影响分析

**EC2 / EKS Nodes (us-west-2a)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:27:54 | Stop-EKS-Instances 开始 | FIS 开始停止 us-west-2a 中的两个 EKS 节点 |
| 12:28:19 | 节点 NotReady | 两个节点变为 NotReady/SchedulingDisabled |
| 12:28:38 | Pod 开始 Terminating | 运行在 us-west-2a 节点上的 Pod 进入 Terminating 状态 |
| 12:28:38 | 新 Pod Pending | K8s 尝试调度替代 Pod，但 ASG 扩容被阻止，无法启动新节点 |
| 12:42:57 | Stop-EKS-Instances 完成 | 实例被 terminated，ASG 启动新实例替代 |
| 12:43:47 | 新节点加入 | 多个新节点在 us-west-2a 和 us-west-2b 加入集群 |

**关键发现:**
- 两个 us-west-2a 节点被 **terminated**（而非 stopped），ASG 自动启动了新实例替代
- Kubernetes 快速检测到节点不可用，将 Pod 标记为 Terminating 并尝试重新调度
- 由于 Pause-ASG-Scaling 阻止了扩容，7 个 Pod 长时间处于 Pending 状态（约 15 分钟）

**RDS MySQL (demo-mysql)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:27:55 | Reboot-RDS-Failover 触发 | Multi-AZ 强制故障转移启动 |
| 12:28:00 | catalog 连接超时开始 | `read tcp ...->10.0.11.76:3306: i/o timeout` — 旧主节点不可达 |
| 12:28:10 | catalog 持续超时 | `dial tcp 10.0.11.76:3306: i/o timeout` — 新连接也无法建立 |
| ~12:29:30 | catalog 恢复正常 | 开始返回 200 响应，DNS 已解析到新主节点 (us-west-2c) |

**关键发现:**
- RDS Multi-AZ 故障转移成功完成，主节点从 us-west-2a 切换到 us-west-2c
- catalog 服务经历了约 **90 秒** 的数据库不可用期
- 应用未实现连接池健康检查或快速失败机制，导致超时持续时间较长

**ElastiCache Redis (demo-redis)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:27:54 | Pause-ElastiCache 开始 | 中断 us-west-2a 节点的电力 |
| 12:28:19 | 状态变为 modifying | ElastiCache 检测到节点丢失，开始内部故障转移 |
| 12:42:54 | Pause-ElastiCache 完成 | FIS action 完成 |

**关键发现:**
- ElastiCache Redis 的 Multi-AZ 自动故障转移 **对应用透明** — checkout 服务 **未记录任何错误**
- Redis 集群模式 (2 分片 x 3 节点) 提供了良好的高可用性保护
- checkout 使用 clustercfg endpoint，节点故障转移对客户端完全透明

**子网网络连通性 (us-west-2a)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:27:54 | Pause-Network-Connectivity 开始 | us-west-2a private-a 和 public-a 子网全部网络中断 |
| 12:28:00 | 连接超时开始 | 所有经过 us-west-2a 子网的流量中断 |
| 12:42:55 | Pause-Network-Connectivity 完成 | 网络连通性恢复 |

**关键发现:**
- 网络中断放大了 RDS 故障转移的影响，导致 catalog 在 DNS 切换前无法通过旧 IP 连接
- CloudWatch Agent 也受到网络中断影响，导致 OTel exporter 持续超时

**ASG (eks-demo-nodegroup-v2)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:27:54 | Pause-ASG-Scaling 开始 | 阻止 ASG 在 us-west-2a 扩容 |
| 12:28:38 | Pod Pending | 新 Pod 无法调度，因为 us-west-2a 无法扩容节点 |
| 12:42:54 | Pause-ASG-Scaling 完成 | ASG 恢复正常扩容能力 |
| 12:43:47 | 新节点启动 | ASG 在 us-west-2a 和 us-west-2b 启动新节点 |

**关键发现:**
- ASG 扩容限制成功模拟了 AZ 完全不可用场景
- 实验期间 7 个 Pod 持续 Pending，无法调度到新节点
- us-west-2b 的现有节点接收了部分重新调度的 Pod

**CloudWatch Agent (间接影响)**

| 时间 (UTC) | 事件 | 观察 |
|---|---|---|
| 12:28:10 | OTel exporter 超时开始 | orders, catalog 的 OTel agent 无法将 metrics/traces 发送到 CloudWatch Agent |
| 12:28:29 | catalog traces 导出超时 | `Post "http://cloudwatch-agent.amazon-cloudwatch:4316/v1/traces": context deadline exceeded` |
| 12:43:29 | 仍在超时 | 网络恢复后仍有部分超时（恢复过渡期） |

**关键发现:**
- CloudWatch Agent pod 可能运行在 us-west-2a 节点上，导致 OTel 收集中断
- orders 服务的大部分 "errors" 实际是 OTel exporter 超时，**非业务逻辑错误**
- 建议确保 CloudWatch Agent 跨 AZ 部署以提高可观测性的可用性

#### Recovery Status Summary

| Resource | Recovery Status | Notes |
|---|---|---|
| EKS 节点 (us-west-2a) | Recovering | 原实例 terminated，新节点正在启动并加入集群 |
| RDS MySQL (demo-mysql) | Recovered | 已故障转移至 us-west-2c，主节点可用，Multi-AZ 已重建 |
| ElastiCache Redis (demo-redis) | Recovering | 仍处于 modifying 状态，应用层已恢复正常 |
| 子网网络 | Recovered | 网络连通性已恢复 |
| ASG 扩容 | Recovered | 已恢复正常扩容，新节点正在启动 |
| catalog 应用 | Recovered | MySQL 故障转移后约 90 秒恢复 |
| checkout 应用 | Not Impacted | Redis 故障转移对应用透明 |
| orders 应用 | Recovering | OTel exporter 仍有超时，业务功能正常 |

#### Issues Requiring Attention

**1. catalog 服务 RDS 故障转移恢复时间过长 (~90秒)**
- **Problem:** catalog 使用直接 TCP 连接到 RDS，未实现快速失败或连接池健康检查。RDS 故障转移期间，旧连接超时需等待较长时间。
- **Recommendation:** 配置 MySQL 连接池的 `connectTimeout` 和 `socketTimeout` 为较短值（如 5 秒），并启用连接验证。考虑使用 RDS Proxy 来处理故障转移。

**2. EKS 实例被 terminated 而非 stopped**
- **Problem:** 实验中 EC2 实例被 terminated，导致 ASG 需要启动全新实例。实验模板配置了 `startInstancesAfterDuration: PT15M`，但实例在恢复前被终止。
- **Recommendation:** 检查 ASG 终止保护设置。实际 AZ 故障场景中实例 terminate 是预期行为，确保应用能容忍节点替换。

**3. CloudWatch Agent 可观测性中断**
- **Problem:** CloudWatch Agent 可能集中部署在 us-west-2a，导致实验期间 OTel metrics/traces 收集中断。
- **Recommendation:** 确保 CloudWatch Agent DaemonSet 的 Pod 分布在所有 AZ，并配置 Pod Topology Spread Constraints。

**4. 多个 Pod 长时间 Pending (15分钟)**
- **Problem:** 由于 ASG 扩容被阻止，7 个 Pod 在实验全程处于 Pending 状态。
- **Recommendation:** 考虑配置 Pod Disruption Budgets (PDB) 确保关键服务的最小副本数，并将副本分布在多个 AZ 使用 topologySpreadConstraints。

---

以下是 `eks-app-log-analysis` 自动生成的应用日志分析报告核心内容：

#### Summary

| Service | Application | Total Errors | Peak Error Rate | Recovery Time |
|---------|-------------|--------------|-----------------|---------------|
| RDS MySQL (demo-mysql) | catalog | 40 | ~4/min (12:28:00-12:28:15) | ~15 秒 (MySQL), OTel 未完全恢复 |
| ElastiCache Redis (demo-redis) | checkout | 0 | 0/min | 无影响 |
| EKS Nodes (间接) | orders | 337 | ~22/min | OTel exporter 持续超时 |
| EKS Nodes | carts | 0 | 0/min | 无影响 |
| EKS Nodes | ui | 0 | 0/min | 无影响 |
| MSK (间接) | msk-client | 0 | 0/min | 无影响 |
| EKS Nodes | loadgen | 52 | N/A (统计报告行) | N/A |

#### Per-Service Application Analysis

**catalog (RDS MySQL)**

错误时间线:

| Time (UTC) | Level | Message |
|------------|-------|---------|
| 12:28:00 | ERROR | `[mysql] connection.go:49: read tcp 10.0.12.215:50222->10.0.11.76:3306: i/o timeout` |
| 12:28:00 | ERROR | `[mysql] connection.go:49: read tcp 10.0.12.215:60496->10.0.11.76:3306: i/o timeout` |
| 12:28:05 | ERROR | `repository.go:152 dial tcp 10.0.11.76:3306: i/o timeout` |
| 12:28:05 | ERROR | `repository.go:188 dial tcp 10.0.11.76:3306: i/o timeout` |
| 12:28:10 | ERROR | `repository.go:152 dial tcp 10.0.11.76:3306: i/o timeout` (x2) |
| 12:28:15 | ERROR | `repository.go:174 dial tcp 10.0.11.76:3306: i/o timeout` |
| 12:28:15 | **RECOVERY** | `[GIN] | 200 | 19.939945ms | GET "/catalog/tags"` — 恢复正常响应 |
| 12:28:29 | WARN | `traces export: processor export timeout` — OTel exporter 开始超时 |
| 12:43:45 | ERROR | `dial tcp: lookup demo-mysql...rds.amazonaws.com: i/o timeout` — 新 Pod DNS 解析超时 |

关键错误模式:

| Pattern | Count | First Occurrence | Last Occurrence |
|---------|-------|------------------|-----------------|
| `dial tcp 10.0.11.76:3306: i/o timeout` | 6 | 12:28:05 | 12:28:15 |
| `read tcp ...->10.0.11.76:3306: i/o timeout` | 2 | 12:28:00 | 12:28:00 |
| `traces export: processor export timeout` | 24 | 12:28:29 | 12:43:29 |
| `lookup ...rds.amazonaws.com: i/o timeout` | 1 | 12:43:45 | 12:43:45 |

日志样本:
```
[pod/catalog-fb7cf6c57-b2d2w/catalog] 2026-04-06T12:28:00 [mysql] connection.go:49: read tcp 10.0.12.215:50222->10.0.11.76:3306: i/o timeout
[pod/catalog-fb7cf6c57-b2d2w/catalog] 2026-04-06T12:28:05 repository.go:152 dial tcp 10.0.11.76:3306: i/o timeout
[pod/catalog-fb7cf6c57-b2d2w/catalog] 2026-04-06T12:28:10 repository.go:152 dial tcp 10.0.11.76:3306: i/o timeout
[pod/catalog-fb7cf6c57-b2d2w/catalog] 2026-04-06T12:28:15 repository.go:174 dial tcp 10.0.11.76:3306: i/o timeout
[pod/catalog-fb7cf6c57-b2d2w/catalog] 2026-04-06T12:28:15 [GIN] | 200 | 19.939945ms | GET "/catalog/tags" ← RECOVERY
```

**洞察:**
- MySQL 连接超时持续约 **15 秒** (12:28:00 - 12:28:15)，随后 RDS DNS 解析到新主节点 (us-west-2c)，catalog 自动恢复
- catalog 使用 Go MySQL driver，连接超时为 5 秒，每 5 秒重试一次
- 后续持续出现 OTel traces export 超时（30 秒间隔），这是 CloudWatch Agent 不可用导致的间接影响，非业务错误
- 实验结束后出现的 DNS 解析超时是新 Pod 在网络恢复过渡期的瞬态错误

**checkout (ElastiCache Redis)**

错误时间线:

| Time (UTC) | Level | Message |
|------------|-------|---------|
| (无错误记录) | - | checkout 在实验全程未产生任何 error/warning 级别日志 |

日志样本 (Normal Operation):
```
[pod/checkout-56dc67d67f-r6b92/checkout] 2026-04-06T12:27:53 [Nest] 1 - LOG [HTTP] GET /checkout/c9877939-... 200 2.030395ms
[pod/checkout-56dc67d67f-q5mq7/checkout] 2026-04-06T12:27:53 [Nest] 1 - LOG [HTTP] POST /checkout/.../update 201 2.16995ms
```

**洞察:**
- ElastiCache Redis 集群模式 (2 分片 x 3 节点, Multi-AZ) 表现出色 — 即使 us-west-2a 节点电力中断，应用层完全无感知
- checkout 使用 Redis cluster configuration endpoint (clustercfg)，Redis 客户端自动路由到可用分片
- 这是本次实验中 **高可用配置最成功的案例**

**orders (EKS 节点中断 — 间接影响)**

错误时间线:

| Time (UTC) | Level | Message |
|------------|-------|---------|
| 12:28:10 | ERROR | `Failed to export metrics. Full error message: timeout` |
| 12:28:11 | ERROR | `Failed to export metrics. timeout` |
| 12:28:27 | ERROR | `java.io.IOException: Canceled` |
| 12:28:28 | ERROR | `Failed to export metrics. timeout` |
| ... | ERROR | (持续 OTel exporter 超时) |
| 12:43:23 | ERROR | `Failed to export spans. timeout` |
| 12:44:06 | WARN | `HikariPool-1 - Failed to validate connection... This connection has been closed.` |

关键错误模式:

| Pattern | Count | First Occurrence | Last Occurrence |
|---------|-------|------------------|-----------------|
| `timeout` (OTel exporter) | 252 | 12:28:10 | 12:43:23 |
| `Failed to export metrics` | 60 | 12:28:10 | 12:42:42 |
| `Failed to export spans` | 24 | 12:28:27 | 12:43:23 |
| `HikariPool-1 - Failed to validate` | 2 | 12:44:06 | 12:44:06 |

**洞察:**
- orders 的 337 个 "errors" 中 **99%+ 是 OTel Java agent 的 exporter 超时**，并非业务逻辑错误
- CloudWatch Agent (cloudwatch-agent.amazon-cloudwatch:4316) 不可用导致 metrics/traces 无法上报
- 实验结束后出现 HikariPool 连接验证失败（PostgreSQL），这是因为 orders-postgresql Pod 在节点迁移期间重启
- orders 的业务功能在实验期间 **基本正常运行**（只有可观测性受影响）

**carts (EKS 节点)**

**洞察:**
- carts 未记录任何应用级错误
- carts 使用本地 DynamoDB (carts-dynamodb)，不依赖外部 AWS 服务
- us-west-2a 上的 carts Pod 进入 Terminating，但 us-west-2b 上的副本继续正常服务

**ui (EKS 节点)**

**洞察:**
- ui 未记录任何应用级错误
- ui 作为前端网关，后端服务 (catalog, checkout, orders, carts) 在 us-west-2b 节点上仍有可用副本
- Kubernetes Service 负载均衡自动将流量路由到健康 Pod

**loadgen (EKS 节点)**

**洞察:**
- loadgen (Locust) 在实验期间持续产生流量
- 统计行包含 "fail" 关键字但非实际错误
- loadgen 部署在 us-west-2b 节点上，未受直接影响

**msk-client (MSK — 间接影响)**

**洞察:**
- msk-client 未记录任何错误
- MSK broker 分布在多个 AZ (b-1, b-2, b-3)，单 AZ 网络中断不影响集群可用性
- msk-client 仅有 10 行日志，可能处于低活动状态

#### Cross-Service Correlation

| Time (UTC) | Event | RDS Impact | ElastiCache Impact | EKS Impact | Application Response |
|------|-------|------------|--------------------|-----------|--------------------|
| 12:27:54 | 故障注入开始 | 故障转移触发 | AZ 电力中断 | 2节点停止 | — |
| 12:28:00 | 首个错误 | catalog: MySQL i/o timeout | 无影响 | 节点 NotReady | orders: OTel timeout |
| 12:28:15 | catalog 恢复 | DNS 解析到新主节点 | — | Pod Terminating | catalog 200 OK |
| 12:28:38 | Pod 重调度 | — | — | 7 Pod Pending | 部分副本仍可用 |
| 12:42:57 | 实验结束 | 主节点在 us-west-2c | 仍在 modifying | 新节点启动 | 业务恢复正常 |
| 12:43:47 | 恢复期 | DNS 瞬态超时 | 持续恢复 | Pod 调度到新节点 | 逐步全量恢复 |

#### Recommendations

1. **catalog MySQL 连接韧性**
   - **Impact:** RDS 故障转移期间 15 秒不可用
   - **Recommendation:** 虽然 15 秒的恢复时间已较快，但可进一步优化：配置更短的 `connectTimeout`（如 3 秒）和 `readTimeout`（如 5 秒），启用连接池的 `testOnBorrow` 验证。对于更短的故障转移感知，考虑使用 RDS Proxy。

2. **OTel Observability 高可用**
   - **Impact:** orders, catalog 在实验全程无法上报 metrics/traces (约15分钟)
   - **Recommendation:** 确保 CloudWatch Agent DaemonSet 在所有 AZ 均有 Pod 运行。配置 OTel exporter 的 `retry` 和 `sending_queue` 以在 Agent 不可用时缓存数据。

3. **Pod 跨 AZ 分布**
   - **Impact:** 7 个 Pod 长时间 Pending，应用副本数下降
   - **Recommendation:** 使用 `topologySpreadConstraints` 确保 Pod 均匀分布在多个 AZ。配置 Pod Disruption Budget (PDB) 确保关键服务的最小可用副本数。

4. **orders PostgreSQL 连接池**
   - **Impact:** 实验后 HikariPool 连接验证失败
   - **Recommendation:** 配置 HikariCP 的 `connectionTestQuery` 和较短的 `maxLifetime`，确保连接池能快速检测并替换失效连接。

---

## 六、更大的图景：专业能力的普惠化

混沌工程只是一个例子。

技术领域有大量"专家专属"的能力：安全审计、性能调优、合规检查、架构评估、成本优化……这些能力的共同特点是：工具强大，但学习门槛高。结果是，很多"应该做"的事情，因为"不会做"而被搁置。

AI Agent 提供了一种新的可能：**把专业知识封装成可对话的能力**。

这是一种范式转变：

| 旧范式 | 新范式 |
|--------|--------|
| 人先学工具 → 再用工具做事 | 人描述意图 → Agent 选择工具、配置、执行 |
| 专业知识是使用门槛 | 专业知识被封装到 Agent 中 |
| 能力受限于个人学习投入 | 能力受限于 Agent Skill 的覆盖范围 |

这不是"降低标准"——专业知识没有消失，而是换了一种存在形式。也不是"替代专家"——对于复杂场景和边界情况，仍然需要专家判断。但对于大量标准化的、重复性的专业任务，Agent Skill 可以让更多人参与进来。

对工程师来说，这意味着：
- 可以专注于**决策和分析**（这是混沌工程的真正价值），而不是**工具配置**
- 可以更频繁地进行 Resilience 测试，而不是因为门槛高而放弃
- 可以把时间花在理解系统行为上，而不是学习又一个专业工具

Agent Skill 是一种新的知识封装和分发方式。我们期待看到更多专业领域的能力被"普惠化"——不是取代专家，而是让专家的知识能够惠及更多人。

**你的领域有哪些专业能力，可以被封装成 Skill？**

---

*本文涉及的三个 Agent Skill 已开源：[链接待补充]*
