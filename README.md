# keytrack

给自己用的本地输入回看工具——不只统计哪个键按得最多，而是能直观看到「今天输入了什么」。

## 架构（v2）

```
鼠须管（lua 采集钩子，随输入法常驻，零权限）
├─ 上屏文字 ──────────► ~/.keytrack/ime_commits.jsonl ─┐
└─ 按键按分钟聚合成桶 ──► ~/.keytrack/ime_keys.jsonl ──┤
                                                     ▼
            launchd 常驻 helper（kbd record，登录自启）
            采样前台应用（CGWindowList）+ 吸入合并 ──► ~/.keytrack/keytrack.db
                                                     ▼
            查询：kbd today / --json / Python API / 直接读 SQLite
```

- **采集全在输入法里**：只要用鼠须管打字，文字上屏和按键节奏就在记录，不需要开任何终端、
  不需要任何系统权限（macOS 安全输入框不经过输入法，密码天然不会被记）。
- **常驻 helper** 只负责「应用归属采样 + 及时入库」；就算它没跑，事件也躺在 jsonl 里，
  下次 `kbd today` 时自动补录（补录的应用标 Unknown）。
- **按键节奏**在 lua 里按分钟聚合成 `{分钟, 各键次数}`，不存按键时间线——统计够用，
  隐私守得住。

## 快速开始

```bash
cd ~/keyboard
# 一次性配置（装过鼠须管并启用后）：
.venv/bin/python kbd.py setup-ime        # 装 lua 钩子并部署
.venv/bin/python kbd.py install-agent    # 装 launchd 常驻 helper

# 日常：什么都不用开，正常打字。想看的时候：
.venv/bin/python kbd.py today            # 今天输入了什么
.venv/bin/python kbd.py show yesterday
.venv/bin/python kbd.py today --json     # JSON（给看板/脚本）
```

## 命令一览

| 命令 | 作用 |
|------|------|
| `kbd today / show <day> [--full] [--json]` | 按天回看（查询前自动补录待收事件） |
| `kbd days` | 列出库里有数据的所有日期 |
| `kbd week [--json] [--push-webhook URL]` | 最近 7 天周报，可推 Lark 机器人（只发聚合数字） |
| `kbd heatmap [day]` | 导出键盘热力图 HTML（log 色阶，悬停看占比） |
| `kbd ergo [day]` | 手/指负载均衡 + 按键熵（要不要换双拼的数据支撑） |
| `kbd record [-v] [--pynput]` | 前台采集（agent 已装时不用手动跑；--pynput 仅当还用别的输入法） |
| `kbd ingest` | 手动补录一次 |
| `kbd setup-ime` | 安装/更新鼠须管采集钩子并触发部署 |
| `kbd install-agent` / `uninstall-agent` / `status` | 常驻 helper 管理 |
| `kbd probe` | 探测辅助功能可读性（诊断遗留） |

终端外的全局 `kbd` 命令由 `/opt/homebrew/bin/kbd` 包装脚本提供。

## 查询接口（做看板 / Swift 状态栏用）

1. **CLI JSON**：`kbd today --json` —— 结构见 `keytrack/query.py:day_report`
2. **Python API**：`from keytrack import query; query.day_report(date)`
3. **直接读 SQLite**（Swift 推荐 GRDB / SQLite.swift）：schema 见 [docs/SCHEMA.md](docs/SCHEMA.md)

## 已知边界

- 内容只在**鼠须管激活**时完整；切回别的输入法，那段时间没有内容。
  macOS 会记住每个 App 上次用的输入法——第一次在常用 App 里各切一次鼠须管即可。
- 粘贴、自动填充不经过输入法，会漏。
- 应用归属按「上屏时刻最靠前窗口的属主」标注；菜单栏弹出窗等无普通窗口的场景
  可能归到下层应用。补录的历史事件标 Unknown。
- 按键桶在分钟切换时才落盘，最新一分钟的节奏数据有一分钟级延迟。
- **不要用 NSWorkspace.frontmostApplication 做长驻采样**——无 runloop 的常驻进程
  会拿到过期值（锁屏后停在 loginwindow），本工具用 CGWindowList 直查窗口服务器。

需求与取舍见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)。
