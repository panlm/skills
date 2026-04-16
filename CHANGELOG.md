# 变更日志

[panlm/skills](https://github.com/panlm/skills) 的所有重要变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/)，按周分组，按 Skill 模块归类。

---

## [2026-04-14 ~ 2026-04-16] — 第 16 周

### aws-fis-experiment-prepare
- **新增**: AZ Power Interruption 场景指南（`references/az-power-interruption-guide.md`）— 标签策略、权限、设计决策
- **新增**: 服务范围子动作裁剪 — 用户提到特定服务时仅包含相关子动作，防止影响其他业务应用；子动作与服务映射表、依赖规则、裁剪示例
- **变更**: 默认实验持续时间从 PT30M 改为 PT10M（10 分钟）；ARC Zonal Autoshift 时间按比例缩放
- **变更**: ARC Zonal Autoshift 从"强制基础设施子动作"降级为"条件包含"（仅当环境有启用 zonal autoshift 的资源时才包含）；Pause-Network-Connectivity 为唯一强制子动作
- **重构**: 移除独立的 experiment-template.json 和 iam-policy.json，仅保留 cfn-template.yaml 和 README；移除默认的 Pause-Instance-Launches action
- **修复**: README 模板中 Directory 字段使用完整绝对路径

### aws-fis-experiment-execute
- **重构**: 流程从 10 步精简到 8 步 — 移除检查 Stack 状态（prepare 已保证）和从 Stack Outputs 提取模板 ID（从目录名提取）
- **重构**: Step 6 移除重复的实现细节，直接委托给 app-service-log-analysis 对应步骤
- **修复**: 移除所有对已删除的 experiment-template.json 和 iam-policy.json 的引用；改为通过 `aws fis get-experiment-template` API 获取 action 列表
- **修复**: `kubectl version --client --short` 替换为 `-o yaml`（`--short` 在新版 kubectl 中已移除）
- **修复**: 实验状态轮询 `while true` 改为 MAX_POLL=30 防止死循环（空 queryId / API 报错时退出）

### app-service-log-analysis
- **新增**: 多集群 EKS 深度依赖发现 — 自动发现 region 内所有 EKS 集群，为每个集群生成独立 kubeconfig（绝不覆盖 `~/.kube/config`），并行扫描
- **新增**: 6 层深度扫描：Pod env vars、ConfigMaps、Secret key names（仅元数据）、EnvFrom 引用、Service ExternalName、Volume mounts（projected/CSI）
- **新增**: ASG scaling activity 历史收集
- **重构**: 日志收集改为始终启用；新增 3 分钟实验后基线窗口；skill 重命名为 app-service-log-analysis
- **修复**: CloudWatch Logs query 脚本新增 3 层防护 — log group 存在性预检查、空 queryId 防护、MAX_POLL=30 防止死循环
- **修复**: Step 7a 托管服务日志仅收集保存到本地文件，Step 7b 统一读取所有日志进行分析

### remote-skill-test
- **重构**: 移除 test-prompt.md 机制，改为用户直接在对话中提供测试提示词；流程从 9 步精简到 8 步
- **修复**: 改为安装全部 skills 解决 skill 间依赖问题

### 文档与项目配置
- **变更**: 根 README 更新三个核心 skill 描述（服务范围裁剪、多集群发现、流程精简）
- **移除**: 所有 skill 的 test-prompt.md 文件

---

## [2026-04-07 ~ 2026-04-13] — 第 15 周

### aws-fis-experiment-execute
- **新增**: Pod 实验自动日志收集、CFN 权限模拟验证、根据 template ID 自动解析目录
- **变更**: 应用日志收集改为 opt-in；移除独立 summary report 合并到 README；资源命名规范统一（可读资源用 ExperimentName，Lambda 资源用 RandomSuffix）
- **重构**: 引用 app-service-log-analysis skill 替代重复日志逻辑
- **修复**: 流程图导致 agent 跳过步骤、Lambda 函数名超 64 字符限制、EKS token 认证

### aws-fis-experiment-prepare
- **变更**: 共享固定名 RBAC 支持幂等创建；CFN Custom Resource 管理 EKS RBAC；新增 pod-memory-stress 阈值计算
- **移除**: 过时的 design.md

### remote-skill-test（新 Skill）
- **新增**: 创建 remote-skill-test skill 及各 skill 的 test-prompt.md 模板
- **改进**: 项目级安装、隔离到带时间戳目录、自动发现 test-prompt.md 路径

### 文档与项目配置
- **新增**: Blog 草稿 v1-v3；AGENTS.md 添加 README 同步规则和 no-auto-commit 规则
- **合并**: PR #1 from ViolaTangxl — 优化文档话术

---

## [2026-03-31 ~ 2026-04-06] — 第 14 周

### app-service-log-analysis（新 Skill）
- **新增**: 创建 app-service-log-analysis skill，用于 BCP 演练的应用日志分析

### aws-fis-experiment-execute
- **重构**: 移除部署步骤，新增 CFN Stack 验证；移除重复 CLI 命令和状态表
- **变更**: 输出保存到 cwd、目录名前置时间戳、目标资源 ID 纳入命名
- **修复**: `&&` 链式命令变量丢失问题

### aws-fis-experiment-prepare
- **新增**: EKS AccessEntry 支持 Pod 故障注入；CFN 权限预检
- **变更**: 使用 AWS 托管 FIS 策略；目标从 resourceTags 切换为 resourceArns
- **修复**: resourceArns + filters 互斥规则；不支持 resourceArns 的资源类型回退到 resourceTags

### 文档
- **新增**: EKS Pod action 前置条件参考；多个 skill 前置条件增加 jq

---

## [2026-03-24 ~ 2026-03-30] — 第 13 周

### aws-fis-experiment-prepare / execute（新 Skill）
- **新增**: 创建 FIS 实验准备和执行 skill — CFN 自愈部署循环、资源-Action 兼容性验证、Scenario Library 文档要求
- **变更**: 停止条件默认 `source:none`；报告时间线格式多次优化（合并到按服务影响分析）

### aws-best-practice-research
- **变更**: 3 份报告合并为单份评估报告；audit 重命名为 assessment
- **修复**: Kiro CLI 报告生成必须用 Write 工具替代 bash heredoc

### aws-service-chaos-research（新 Skill）
- **新增**: 创建 aws-service-chaos-research skill — 混沌测试场景研究
- **变更**: Scenario Library 去重规则加强；输出模板重构（SVC-# 测试 ID）

### 项目配置
- **新增**: context7 MCP 服务器前置条件；根目录中文 README
- **变更**: 调整文件夹结构，设计文档移至各 skill 目录内

---

## [2026-03-23 ~ 2026-03-25] — 第 12-13 周（项目创建）

### aws-best-practice-research（首个 Skill）
- **新增**: 初始提交 — agent skills 合集，包含 aws-bestpractice-research
- **变更**: 强制严格顺序 MCP 调用（禁止并行）；MCP 限流错误重试最多 10 次
- **修复**: Test ID 格式加强 — 移除 # 列，增加 Red Flag 警告

---

## 编写规范

本文件供人工阅读和 agent 读取，遵循以下规范以保持简洁和一致性：

### 结构
- **按周分组**：`## [起始日期 ~ 结束日期] — 第 N 周`
- **按 Skill 归类**：每周内按 `### skill-name` 分类，新 Skill 首次出现时标注 `（新 Skill）`
- **跨 Skill 的变更**（文档、项目配置、CI）归入 `### 文档`、`### 项目配置` 等通用分类

### 条目
- 每条以加粗标签开头：`**新增**`、`**变更**`、`**修复**`、`**重构**`、`**移除**`、`**改进**`、`**合并**`
- **同一方向的多次 commit 合并为一条** — 例如 5 次命名规范调整合并为"资源命名规范统一"
- **回退再修复的来回合并为最终状态** — 只记录最终结果，不记录中间的回退和重试
- **不记录 commit hash** — 保持简洁，需要追溯时通过 `git log` 查找
- 每条描述控制在一行内，用分号分隔多个相关变更

### 新增条目的流程
1. 确定当前日期所属的周区间，找到或创建对应的周标题
2. 在该周下找到或创建对应的 Skill 子标题
3. 查看该 Skill 下已有条目，如果新变更属于同一方向则合并到已有条目，否则新增一条
4. 如果是全新的 Skill，在子标题后标注 `（新 Skill）`
