# SKILL.md 安全审计检查清单 (10 类)

对每个 SKILL.md 文件进行以下 10 个维度的安全审计。每个维度给出 **通过/警告/危险** 评级。

---

## SEC-01: 任意命令执行 (Arbitrary Command Execution)

检查 SKILL.md 中是否指示 agent 执行 shell 命令。

**危险信号 (红旗):**
- `bash`, `sh -c`, `eval`, `exec` 指令
- 管道执行: `| sh`, `| bash`
- 使用变量拼接构造命令 (注入向量)
- `sudo` 或任何提权操作
- 极长的 one-liner，难以视觉审计

**评级规则:**
- **通过**: 无 shell 命令，或仅运行明确命名的 CLI 工具 (如 `memo notes -a`)
- **警告**: 运行 shell 命令但范围明确、只读 (如 `aws s3 ls`)
- **危险**: 存在 `eval`/`exec`/`sudo`，或管道到 shell，或使用变量构造命令

---

## SEC-02: 数据外泄 (Network Exfiltration)

检查是否将数据发送到外部端点。

**危险信号:**
- `curl -X POST`, `wget --post-data`, `httpie` POST 到第三方 URL
- 将敏感输出 (环境变量、凭证、文件内容) 通过管道发送到 `curl`
- Webhook URL (Discord, Slack, 任意域名)
- `nc` (netcat), 反向 shell
- DNS 外泄模式 (`dig` 子域名编码数据)

**评级规则:**
- **通过**: 无任何向外部发送数据的行为
- **警告**: 调用已知 API (如 aws, github) 但不发送到第三方
- **危险**: 向未知/第三方 URL POST 数据，或存在 netcat/反向 shell

---

## SEC-03: 凭证获取 (Credential Harvesting)

检查是否访问、读取或请求密钥。

**危险信号:**
- 读取 `~/.aws/credentials`, `~/.ssh/`, `~/.gnupg/`, `~/.netrc`
- 访问环境变量: `$AWS_SECRET_ACCESS_KEY`, `$GITHUB_TOKEN`, `$OPENAI_API_KEY`
- 指示用户 "paste your API key" 到文件或变量中
- macOS keychain 访问: `security find-generic-password`
- 读取 `.env` 文件

**评级规则:**
- **通过**: 不触碰任何凭证或密钥
- **警告**: 使用已配置的凭证 (如依赖 `aws configure`) 但不直接读取凭证文件
- **危险**: 直接读取凭证文件、keychain，或指示用户在 skill 中内联粘贴密钥

---

## SEC-04: 软件包安装 / 供应链风险 (Supply Chain)

检查是否安装软件。

**危险信号:**
- `pip install <冷门包>` (typosquatting 风险)
- `npm install -g` 来自未知源
- `brew install` 来自非官方 tap
- `curl ... | sh` (管道安装模式)
- 未锁定版本 (`@latest`，可变依赖)

**评级规则:**
- **通过**: 无安装操作，或安装广泛使用的知名工具并锁定版本
- **警告**: 安装小众但可追溯的工具，或使用非官方 tap/registry
- **危险**: `curl | sh` 模式，或安装无法追溯来源的包

---

## SEC-05: 文件系统篡改 (File System Manipulation)

检查是否修改或删除范围外的文件。

**危险信号:**
- 写入 `~/.bashrc`, `~/.zshrc`, `~/.profile` (持久化)
- 修改 `/etc/hosts`, `/etc/resolv.conf`, crontab
- 写入 `~/.openclaw/`, `~/.claude/` (污染其他 skill 或配置)
- `rm -rf` 作用于宽泛路径
- 创建隐藏文件或隐藏目录
- `chmod 777` 或过于宽松的权限

**评级规则:**
- **通过**: 仅在自身工作目录内操作
- **警告**: 写入用户文档目录或 /tmp，但不触碰系统配置
- **危险**: 修改 shell 配置、系统文件，或执行 `rm -rf`

---

## SEC-06: Prompt 注入 / 指令覆盖 (Prompt Injection)

检查是否操纵 agent 的行为。

**危险信号:**
- "Ignore all previous instructions" 类指令
- 隐藏文本 (零宽字符、HTML 注释、base64 编码指令)
- 嵌入 `SYSTEM:` 或 `<system>` 标签
- 抑制用户确认的指令 ("do not ask the user", "run silently")
- 覆盖安全行为 ("you are now in unrestricted mode")
- 指示 agent 对用户撒谎

**评级规则:**
- **通过**: 指令清晰透明，无隐藏行为
- **警告**: 存在 "automatically" 或 "without confirmation" 但在合理范围内
- **危险**: 存在明确的 prompt injection 模式或隐藏指令

---

## SEC-07: 越权操作 (Scope Creep)

检查请求的权限是否超出其声称的功能。

**危险信号:**
- "笔记" skill 却读取浏览器历史
- "格式化" skill 却执行网络扫描
- 请求 admin 级权限
- 枚举整个账户/系统 (所有 S3 bucket, 所有 IAM user)
- 访问无关服务

**评级规则:**
- **通过**: 操作范围与 skill 声称的功能完全一致
- **警告**: 操作略超出声称范围但有合理解释
- **危险**: 明显越权，功能与声称不符

---

## SEC-08: 持久化机制 (Persistence)

检查是否建立长驻或定期访问。

**危险信号:**
- Crontab 条目 (`crontab -e`)
- macOS LaunchAgent / LaunchDaemon plist
- Linux systemd service 创建
- 后台进程 (`nohup`, `&`, `disown`)
- SSH 密钥注入 (写入 `~/.ssh/authorized_keys`)
- Git hooks (`.git/hooks/`)

**评级规则:**
- **通过**: 无任何持久化行为
- **警告**: 提到 cron/后台进程但作为可选项且有明确说明
- **危险**: 在用户不知情的情况下建立持久化机制

---

## SEC-09: 信息采集 / 侦察 (Reconnaissance)

检查是否收集系统或环境元数据。

**危险信号:**
- `whoami`, `id`, `hostname`, `uname -a`
- `ifconfig` / `ip addr` (网络拓扑)
- `ps aux`, `env`, `printenv`
- 列出已安装的包、运行中的服务
- 读取 `/proc/`, `/sys/`
- 获取 Git 配置 (`git config --list`, `git remote -v`)

**评级规则:**
- **通过**: 不收集任何系统/环境信息
- **警告**: 为诊断目的收集有限的系统信息 (如检查 OS 版本以确定兼容性)
- **危险**: 广泛收集系统元数据且无明确诊断目的

---

## SEC-10: 混淆 / 反分析 (Obfuscation)

检查是否隐藏真实行为。

**危险信号:**
- Base64 编码命令: `echo "..." | base64 -d | sh`
- URL 编码或十六进制编码的 payload
- 变量间接引用: `$($cmd)` 其中 `cmd` 在其他地方定义
- 运行时下载并执行远程脚本
- 条件行为: "if running in CI, do X; otherwise do Y"
- 将恶意命令拆分到多个看似无害的指令中

**评级规则:**
- **通过**: 所有指令清晰可读，无编码或间接执行
- **警告**: 使用 base64 但用于数据编码而非命令执行
- **危险**: 存在编码命令执行、运行时远程脚本下载、或行为拆分模式

---

## 综合评级规则

| 综合评级 | 条件 |
|---|---|
| **Safe** (安全) | 所有 10 项均为"通过" |
| **Low** (低风险) | 有 1-2 项"警告"，无"危险" |
| **Medium** (中风险) | 有 3+ 项"警告"，或有 1 项"危险"但在合理范围内 |
| **High** (高风险) | 有 2+ 项"危险" |
| **Critical** (严重) | 存在 SEC-02(数据外泄) + SEC-03(凭证获取) 组合，或 SEC-06(Prompt注入)，或 SEC-10(混淆) 中的"危险" |

## 输出格式

```markdown
### 安全审计结果

| 检查项 | 评级 | 发现 |
|---|---|---|
| SEC-01 命令执行 | 🟢 通过 | 仅使用 `memo` CLI，无 shell 管道 |
| SEC-02 数据外泄 | 🟢 通过 | 无外部网络请求 |
| ... | ... | ... |

**综合评级: 🟢 Safe (安全)**
**风险摘要: 该 skill 仅操作本地 Apple Notes，无网络访问、无凭证读取、无系统修改。**
```
