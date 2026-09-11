# Agent Rules for panlm-skills

## 开源 repo 隐私规则

**本 repo 是公开开源的。写入任何文件前，先确认内容不含隐私信息。**

禁止出现在 repo 任何文件里（含 SKILL.md、README、references/、示例、注释、commit message）：

- 真实姓名、邮箱、手机号、企业微信/飞书/Slack 账号
- 内部系统 URL、内网域名、内部工单/wiki 链接
- 文档/表格/知识库的真实 ID（飞书 doc token、Asana gid、Notion page id、Confluence pageId 等）
- AWS account id、ARN 中的 account 段、access key、密钥、token、私有 S3 bucket 名
- 本机绝对路径中的用户名（`/Users/<name>/...`）、主机名、机器 ID
- 客户名、项目代号、未公开的产品名
- 公司内部流程细节、未公开的组织结构

处理方式：

- 需要举例 → 用占位符（`<YOUR_DOC_ID>`、`example.com`、`123456789012`、`~/path/to/repo`）
- 需要真实值才能跑 → 从环境变量或本地未跟踪配置文件读取，repo 里只留字段名和说明
- 已经写进去了 → 立刻改掉；若已 commit，明确告知用户需要重写历史，不要只做一次新 commit 掩盖

不确定某项是否算隐私 → 当作隐私处理，并问用户。

## Skill 编辑规则

**严禁直接修改系统目录下的 skill 文件。** 所有 skill 的编辑、创建、调试工作必须在当前 repo (`panlm-skills`) 中进行。

不允许直接写入或修改以下任何系统目录中的文件：
- `~/.config/opencode/skills/`
- `~/.agent/skills/`
- `~/.claude/skills/`
- `~/.kiro/skills/`
- 以及其他类似的系统级 skill 安装目录

修改完成后，由用户自行决定是否将改动同步到系统目录。

## README 同步规则

**更新完 SKILL.md 或 references/ 下的文件后，必须同步更新对应的 README.md 和 README_CN.md。** 不要遗漏。

## Git 提交规则

**不要主动执行 git commit 或 git push。** 只有在用户明确要求时才进行提交和推送。

提交和推送时始终使用 `--no-verify` 参数：
```bash
git commit -m "commit message"
git push --no-verify
```
