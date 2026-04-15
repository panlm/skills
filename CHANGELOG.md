# 变更日志

[panlm/skills](https://github.com/panlm/skills) 的所有重要变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/)，按周分组，按 Skill 模块归类。

---

## [2026-04-14 ~ 2026-04-15] — 第 16 周

### aws-fis-experiment-prepare
- **新增**: AZ Power Interruption 场景指南（`references/az-power-interruption-guide.md`）— 标签策略、权限、设计决策
- **修复**: README 模板中 Directory 字段使用完整绝对路径

### aws-fis-experiment-execute
- **修复**: 测试 prompt 中移除"跳过应用日志收集"的配置

### remote-skill-test
- **修复**: 改为安装全部 skills 解决 skill 间依赖问题

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
