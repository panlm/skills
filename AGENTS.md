# Agent Rules for panlm-skills

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

## commit 内容更新到 repo 根下面的 CHANGELOG 文件

将提交内容用中文写入 CHANGELOG，CHANGELOG中按照周分类，按照不同SKILL进行子分类


## Git 提交规则

**不要主动执行 git commit 或 git push。** 只有在用户明确要求时才进行提交和推送。

提交和推送时始终使用 `--no-verify` 参数：
```bash
git commit -m "commit message"
git push --no-verify
```
