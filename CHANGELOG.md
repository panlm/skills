# 变更日志

[panlm/skills](https://github.com/panlm/skills) 的所有重要变更记录。

格式参考 [Keep a Changelog](https://keepachangelog.com/)，按周分组，按 Skill 模块归类。

---

## [2026-04-14 ~ 2026-04-15] — 第 16 周（本周进行中）

**3 次提交** | 贡献者: panlm

### remote-skill-test

- **修复**: 改为安装全部 skills 而非单个 skill，解决 skill 间的互相依赖问题 ([c16dcac](https://github.com/panlm/skills/commit/c16dcac))

### aws-fis-experiment-prepare

- **修复**: README 模板中 Directory 字段使用完整绝对路径 ([735ffc3](https://github.com/panlm/skills/commit/735ffc3))

### aws-fis-experiment-execute

- **修复**: 从测试 prompt 中移除"跳过应用日志收集"的配置 ([e88955a](https://github.com/panlm/skills/commit/e88955a))

---

## [2026-04-07 ~ 2026-04-13] — 第 15 周

**约 30 次提交** | 贡献者: panlm, violatang, claude

### aws-fis-experiment-execute

- **新增**: Pod 实验（`aws:eks:pod-*`）自动启用日志收集 ([67bc2bd](https://github.com/panlm/skills/commit/67bc2bd))
- **新增**: CFN 权限模拟验证和 FIS ExperimentTemplate 文档查找 ([b2eeb75](https://github.com/panlm/skills/commit/b2eeb75))
- **新增**: 根据 template ID 自动解析实验目录 ([3963037](https://github.com/panlm/skills/commit/3963037))
- **变更**: 应用日志收集改为 opt-in（默认关闭） ([1cad85f](https://github.com/panlm/skills/commit/1cad85f))
- **变更**: 非 Pod 实验强制弹出日志收集确认提示 ([67d37b9](https://github.com/panlm/skills/commit/67d37b9))
- **变更**: 合并主线流程与 test 分支改进 ([4fe8c63](https://github.com/panlm/skills/commit/4fe8c63))
- **重构**: 引用 eks-app-log-analysis skill 替代重复的日志逻辑 ([8d92488](https://github.com/panlm/skills/commit/8d92488))
- **变更**: 移除独立的 summary report，合并到 README；部署后按 template ID 重命名输出目录 ([386c97e](https://github.com/panlm/skills/commit/386c97e))
- **变更**: 统一资源命名规范 — 可读资源（IAM Role、Dashboard、Alarm）使用 ExperimentName，Lambda 资源使用 RandomSuffix（`fis-rbac-`、`fis-lambda-role-`），限制在 64 字符内 ([d21d76d](https://github.com/panlm/skills/commit/d21d76d))
- **变更**: 所有资源名统一小写；IAM Role 使用 RandomSuffix（`fis-role-`）；移除 README 模板中多余的 CLI 手动命令 ([2fa3c0b](https://github.com/panlm/skills/commit/2fa3c0b))
- **修复**: 流程图导致 agent 跳过日志收集提示 ([0da2bdc](https://github.com/panlm/skills/commit/0da2bdc))
- **修复**: description 和 overview 缺少 Step 4.5 — agent 曾跳过该步骤 ([d36d61a](https://github.com/panlm/skills/commit/d36d61a))
- **修复**: 日志收集使用 `--container` 替代 `--all-containers`，排除 FIS 临时容器 ([3c1ee75](https://github.com/panlm/skills/commit/3c1ee75))
- **修复**: Lambda 函数名超过 64 字符限制，改用 `fis-rbac-{RandomSuffix}`（15 字符）替代 `fis-rbac-mgr-{StackName}`（最长 75 字符） ([0003089](https://github.com/panlm/skills/commit/0003089))
- **修复**: Lambda EKS token 认证、命名规范，并将日志分析集成到 execute skill ([c9ccc5b](https://github.com/panlm/skills/commit/c9ccc5b))
- **修复**: eks-app-log-analysis skill 引用使用显式 'MUST load' 指令 ([1aa9fd0](https://github.com/panlm/skills/commit/1aa9fd0))

### aws-fis-experiment-prepare

- **变更**: 使用共享固定名 RBAC，支持幂等创建和删除时跳过 ([a83041d](https://github.com/panlm/skills/commit/a83041d))
- **变更**: 通过 CFN Custom Resource 管理 EKS RBAC，新增 pod-memory-stress 阈值计算 ([ac8907b](https://github.com/panlm/skills/commit/ac8907b))
- **变更**: 更新 slug 描述，README 模板增加 Directory 字段 ([0134459](https://github.com/panlm/skills/commit/0134459))
- **移除**: 删除过时的 design.md（已被 README 取代） ([5068a47](https://github.com/panlm/skills/commit/5068a47))

### remote-skill-test（新 Skill）

- **新增**: 创建 remote-skill-test skill 及所有可测试 skill 的 test-prompt.md 模板 ([0422898](https://github.com/panlm/skills/commit/0422898))
- **新增**: .gitignore 排除 skills-lock.json 和 skills/ 符号链接；为 best-practice-research 添加 test-prompt.md ([099ffb0](https://github.com/panlm/skills/commit/099ffb0))
- **改进**: 创建目录优先、项目级安装、捕获 opencode 运行输出到日志 ([97385fd](https://github.com/panlm/skills/commit/97385fd))
- **改进**: 仅安装目标 skill，每次运行隔离到带时间戳的目录，就近存放上次报告 ([f274813](https://github.com/panlm/skills/commit/f274813))
- **改进**: 自动发现 test-prompt.md 路径，不再硬编码 agent skill 目录 ([714b612](https://github.com/panlm/skills/commit/714b612))
- **改进**: 使用已知路径查找替代 find 命令定位 test-prompt.md（先查项目级、再查全局） ([09d4669](https://github.com/panlm/skills/commit/09d4669))

### 文档与博客

- **新增**: Blog 草稿、v2、v2.1 版本 ([67a5dc6](https://github.com/panlm/skills/commit/67a5dc6), [d622632](https://github.com/panlm/skills/commit/d622632), [027d56f](https://github.com/panlm/skills/commit/027d56f))
- **新增**: Blog v3 — 反映 execute skill 实验分类和日志收集决策变更 ([20d1ebe](https://github.com/panlm/skills/commit/20d1ebe))
- **变更**: Blog v3 — 将关键发现段落移到对比表前，提升可读性 ([901ae2f](https://github.com/panlm/skills/commit/901ae2f))
- **变更**: 更新 README.md 和 README_CN.md，反映共享固定名 RBAC 变更 ([de61294](https://github.com/panlm/skills/commit/de61294))
- **合并**: PR #1 from ViolaTangxl — 优化文档话术 ([33aec61](https://github.com/panlm/skills/commit/33aec61))

### 项目配置

- **新增**: AGENTS.md — 添加 README 同步规则（SKILL.md 变更后必须更新 README） ([c3c002f](https://github.com/panlm/skills/commit/c3c002f))
- **新增**: AGENTS.md — 添加 no-auto-commit 规则 ([cb81730](https://github.com/panlm/skills/commit/cb81730))
- **新增**: 报告保存到实验目录而非 cwd；AGENTS.md 添加 git `--no-verify` 规则 ([7f74b44](https://github.com/panlm/skills/commit/7f74b44))
- **变更**: 优化搜索查询 — 缩减为 5 个查询，简化 topics，移除 Q6 ([cb81730](https://github.com/panlm/skills/commit/cb81730))

---

## [2026-03-31 ~ 2026-04-06] — 第 14 周

**约 30 次提交** | 贡献者: panlm, claude

### eks-app-log-analysis（新 Skill）

- **新增**: 创建 eks-app-log-analysis skill，用于 BCP 演练的应用日志分析 ([7b26a9c](https://github.com/panlm/skills/commit/7b26a9c))
- **重构**: 用描述性指令替代冗长脚本 ([2bcb757](https://github.com/panlm/skills/commit/2bcb757))
- **变更**: 日志收集从 `deployment/xxx` 切换为 `--selector`，提升健壮性 ([7f16cf5](https://github.com/panlm/skills/commit/7f16cf5))

### aws-fis-experiment-execute

- **重构**: 移除部署步骤，新增 CFN Stack 验证 ([26cf7e6](https://github.com/panlm/skills/commit/26cf7e6))
- **重构**: 移除重复的 CLI 命令和状态表 ([f077962](https://github.com/panlm/skills/commit/f077962))
- **变更**: 实验输出保存到 cwd，日志保存到 /tmp 而非实验目录 ([b92567c](https://github.com/panlm/skills/commit/b92567c))
- **变更**: 输出目录名前置时间戳 ([b8d72a8](https://github.com/panlm/skills/commit/b8d72a8))
- **变更**: 应用日志目录增加时间戳前缀，支持多次运行 ([d0dc37b](https://github.com/panlm/skills/commit/d0dc37b))
- **变更**: 合并输出模板，简化条件输出逻辑 ([98bf3c3](https://github.com/panlm/skills/commit/98bf3c3))
- **变更**: 目标资源 ID 纳入目录/Stack/模板名称，Stack 名使用随机后缀 ([0fa9456](https://github.com/panlm/skills/commit/0fa9456))
- **移除**: 移除 expected-behavior.md ([e29dc56](https://github.com/panlm/skills/commit/e29dc56))
- **修复**: `&&` 链式命令中变量丢失问题 — 使用 export 和多行脚本 ([cc65c78](https://github.com/panlm/skills/commit/cc65c78))
- **修复**: 修正剩余目录名示例 ([43fd1af](https://github.com/panlm/skills/commit/43fd1af))
- **回退**: 撤销"简化 SKILL.md，将 CLI 细节移至 reference" ([aab0a83](https://github.com/panlm/skills/commit/aab0a83))

### aws-fis-experiment-prepare

- **新增**: EKS AccessEntry 支持 Pod 故障注入 ([1605dd6](https://github.com/panlm/skills/commit/1605dd6))
- **新增**: CFN 权限预检，目标从 resourceTags 切换为 resourceArns ([6d19b1c](https://github.com/panlm/skills/commit/6d19b1c))
- **变更**: 使用 AWS 托管 FIS 策略作为 IAM Role，新增应用依赖自动发现 ([97f9b64](https://github.com/panlm/skills/commit/97f9b64))
- **修复**: resourceArns + filters 互斥规则，移除 dry-run 步骤 ([0c648f2](https://github.com/panlm/skills/commit/0c648f2))
- **修复**: 不支持 resourceArns 的资源类型回退到 resourceTags ([b89e296](https://github.com/panlm/skills/commit/b89e296))
- **修复**: README cleanup 命令中 Stack 名不一致问题 ([43b4582](https://github.com/panlm/skills/commit/43b4582))

### 文档

- **新增**: EKS Pod action 前置条件参考和必需工作流步骤 ([0b0f5a9](https://github.com/panlm/skills/commit/0b0f5a9))
- **新增**: eks-workload-best-practice-assessment 前置条件增加 jq ([0cafbd4](https://github.com/panlm/skills/commit/0cafbd4))
- **新增**: aws-best-practice-research 实时评估前置条件增加 jq ([c82891c](https://github.com/panlm/skills/commit/c82891c))
- **新增**: eks-app-log-analysis 前置条件增加可选的 Container Insights 和 EKS 控制平面日志 ([1c3dce2](https://github.com/panlm/skills/commit/1c3dce2))
- **变更**: 最小权限细节移至各 skill README，前置条件改为项目列表格式 ([f404556](https://github.com/panlm/skills/commit/f404556))
- **变更**: 更新 README — 调整 skill 排序，新增其他分类 ([e9915be](https://github.com/panlm/skills/commit/e9915be))

---

## [2026-03-24 ~ 2026-03-30] — 第 13 周

**约 30 次提交** | 贡献者: panlm

### aws-fis-experiment-prepare / execute（新 Skill）

- **新增**: 创建 FIS 实验准备和执行 skill ([2bcc0c5](https://github.com/panlm/skills/commit/2bcc0c5))
- **新增**: CFN 自愈部署循环 ([1a2e1db](https://github.com/panlm/skills/commit/1a2e1db))
- **新增**: 资源-Action 兼容性验证（在文件生成前） ([e53160f](https://github.com/panlm/skills/commit/e53160f))
- **新增**: 实验报告增加时间线章节 ([48e4a4b](https://github.com/panlm/skills/commit/48e4a4b))
- **新增**: prepare skill 增加 Scenario Library 文档要求 ([1f46a03](https://github.com/panlm/skills/commit/1f46a03))
- **变更**: 停止条件默认为 `source:none`，扩展 dashboard 指标 ([9eddecd](https://github.com/panlm/skills/commit/9eddecd))
- **变更**: 时间线整合到按服务划分的影响分析章节 ([34f9e6a](https://github.com/panlm/skills/commit/34f9e6a))
- **变更**: 时间戳要求精确到秒，不要毫秒 ([35621b2](https://github.com/panlm/skills/commit/35621b2))
- **变更**: 时间线表格使用仅时间格式（HH:MM:SS UTC）提升可读性 ([d3d24b6](https://github.com/panlm/skills/commit/d3d24b6))
- **变更**: Key Findings 和 Observations 合并为按服务的单一表格 ([a99c321](https://github.com/panlm/skills/commit/a99c321))
- **回退**: Key Findings 恢复为表格下方的项目列表 ([3cac040](https://github.com/panlm/skills/commit/3cac040))
- **变更**: 更新报告输出为本地 md 文件，FIS skill 增加 README ([481b83e](https://github.com/panlm/skills/commit/481b83e))
- **文档**: 更新设计文档反映 CFN 自愈部署 ([49d750e](https://github.com/panlm/skills/commit/49d750e))

### aws-best-practice-research（原 eks-workload-best-practice-assessment）

- **变更**: 3 份报告输出合并为单份评估报告，减少冗余 ([73d2492](https://github.com/panlm/skills/commit/73d2492))
- **修复**: Kiro CLI 工具错误 — 报告生成必须用 Write 工具替代 bash heredoc ([6875d1e](https://github.com/panlm/skills/commit/6875d1e))
- **回退**: 撤销"拆分 Step 6/7：在生成 markdown 报告前输出结构化 JSON" ([69cc3e4](https://github.com/panlm/skills/commit/69cc3e4))
- **变更**: 将 audit 重命名为 assessment ([23aa04a](https://github.com/panlm/skills/commit/23aa04a))
- **变更**: 拓扑分布约束和 Pod 反亲和性提升为高优先级 ([2ceffac](https://github.com/panlm/skills/commit/2ceffac))

### aws-service-chaos-research

- **新增**: 创建 aws-service-chaos-research skill ([9553f5a](https://github.com/panlm/skills/commit/9553f5a))
- **重构**: 提取 references/ 目录，新增中英文 README，英文输出模板 ([e1dffd4](https://github.com/panlm/skills/commit/e1dffd4))
- **新增**: Scenario Library 跨引用去重规则 ([b84c6e6](https://github.com/panlm/skills/commit/b84c6e6))
- **变更**: 加强 Scenario Library 去重规则 — 显式示例、优先级表去重、修复残留中文标签 ([295adb2](https://github.com/panlm/skills/commit/295adb2))
- **变更**: 中英文 README 增加 Scenario Library 去重设计决策说明 ([6ba954a](https://github.com/panlm/skills/commit/6ba954a))
- **变更**: 重构输出模板 — Scenario Library 置于按服务章节之前，新增 SVC-# 测试 ID ([c1d74cd](https://github.com/panlm/skills/commit/c1d74cd))
- **变更**: 添加容器/编排平台的范围边界 ([344fc9b](https://github.com/panlm/skills/commit/344fc9b))

### 项目配置与结构

- **新增**: 前置条件增加 context7 MCP 服务器和 OpenCode 配置示例 ([315e067](https://github.com/panlm/skills/commit/315e067))
- **新增**: 根目录增加中文 README 和语言切换链接 ([b10fea7](https://github.com/panlm/skills/commit/b10fea7))
- **变更**: 调整文件夹结构 ([c13a387](https://github.com/panlm/skills/commit/c13a387))
- **变更**: 设计文档移至各 skill 目录内 ([5d773dd](https://github.com/panlm/skills/commit/5d773dd))
- **变更**: 添加剩余 skills 并更新 aws-best-practice-research 引用 ([6bbc2da](https://github.com/panlm/skills/commit/6bbc2da))

---

## [2026-03-23 ~ 2026-03-25] — 第 12-13 周（项目创建）

**约 15 次提交** | 贡献者: panlm

### aws-best-practice-research（首个 Skill）

- **新增**: 初始提交 — agent skills 合集，包含 aws-bestpractice-research ([430b0b1](https://github.com/panlm/skills/commit/430b0b1))
- **新增**: SKILL.md frontmatter 细化，新增中英文 README ([65de4e9](https://github.com/panlm/skills/commit/65de4e9))
- **变更**: 同步 README 与 SKILL.md — 动态服务发现、顺序搜索、新增决策流程图 ([9ded20b](https://github.com/panlm/skills/commit/9ded20b))
- **变更**: 强制严格顺序 MCP 调用 — 添加顶层规则、每步提醒、加强指引 ([65b8bfc](https://github.com/panlm/skills/commit/65b8bfc))
- **变更**: 多服务请求强制按服务顺序处理 ([c00d730](https://github.com/panlm/skills/commit/c00d730))
- **变更**: 并行操作改为顺序执行 ([b4eedd1](https://github.com/panlm/skills/commit/b4eedd1))
- **变更**: MCP 限流错误重试最多 10 次，替代 WebFetch 迁移方案 ([21539bf](https://github.com/panlm/skills/commit/21539bf))
- **变更**: Test ID 格式加强 — REQUIRED 矩阵按服务分列，具体 ID 示例 ([e0db6dc](https://github.com/panlm/skills/commit/e0db6dc))
- **修复**: Test ID 采用修正 — 移除所有参考表的 # 列，增加 Red Flag 警告，加强格式规则 ([d76a805](https://github.com/panlm/skills/commit/d76a805))
- **回退**: 撤销"用 WebFetch 替代 aws___read_documentation" ([8dda32e](https://github.com/panlm/skills/commit/8dda32e))
- **杂项**: 重命名 aws-knowledge-mcp-server 并添加源码链接 ([d77259c](https://github.com/panlm/skills/commit/d77259c))
- **杂项**: 移除过时的 SKILL.md.orig ([e944b59](https://github.com/panlm/skills/commit/e944b59))
- **杂项**: 重命名文件夹 ([31ddd0d](https://github.com/panlm/skills/commit/31ddd0d))
