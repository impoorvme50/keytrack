# keytrack

给自己用的本地输入回看工具——不只统计哪个键按得最多，而是能直观看到「今天输入了什么」。

> **伦理声明**：本工具是**本机自用**的自我量化工具——只记录你自己在你自己设备上的
> 输入，全部数据存在本机 SQLite，不联网上传。请勿将其用于记录他人设备或他人输入。
> 隐私设计：按键只按分钟聚合计数（不存按键时间线），macOS 安全输入框（密码等）
> 不经过输入法，天然不会被记录。

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

## 统计口径（v0.4.1）

按键采集器位于输入处理链最前面，只观察并透传按键。大写、Shift 标点与组合键主键归到 ANSI 物理键；修饰键不随每次组合键重复计算。范围仅覆盖鼠须管收到的按键，不代表整台 Mac 的输入。

v0.4.0 及更早的采集位置可能漏记字母和空格。升级后保留全部历史，并根据分钟桶的采集版本区分旧记录、当天混合记录和已校验记录。旧/混合记录不显示速度、活跃时间、退格占比与手指百分比；历史漏采无法补回。键盘热力图仍显示已收到的次数，并注明不完整。上屏字数来自独立的上屏记录，不受这次按键漏采影响。

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
| `kbd ergo [day]` | 按标准指法估算按键分布与按键熵（仅使用已校验的记录） |
| `kbd record [-v] [--pynput]` | 前台采集（agent 已装时不用手动跑；--pynput 仅当还用别的输入法） |
| `kbd ingest` | 手动补录一次 |
| `kbd setup-ime` | 安装/更新鼠须管采集钩子并触发部署 |
| `kbd install-agent` / `uninstall-agent` / `status` | 常驻 helper 管理 |
| `kbd doctor [--json]` | 只读检查实际服务状态、Lua 安装版本、部署钩子与本机模型接口 |
| `kbd ui` | 打开 SwiftUI 原生输入控制台：统计、常用语、外观、AI 开关和备份 |
| `kbd console [--demo] [--no-open]` | 在浏览器打开本地控制台；演示模式使用独立的自造数据 |
| `kbd probe` | 探测辅助功能可读性（诊断遗留） |

终端外的全局 `kbd` 命令由 `/opt/homebrew/bin/kbd` 包装脚本提供。

独立安装版可从 [v0.4.1 下载页](https://github.com/impoorvme50/keytrack/releases/tag/v0.4.1) 获取（Apple 芯片，macOS 26 及以上）：将应用拖入「应用程序」，打开后点「完成本机安装」。界面和采集自带运行组件，不再依赖源码目录、Python 安装或 Homebrew；输入法需要已有鼠须管，可选 AI 沿用现有本机 Kev 模型。当前为本机自用/实验版，未做 Apple Developer ID 签名和公证。开发构建用 `./scripts/build-console.sh`，打包用 `./scripts/package-console.sh`。用法见 [输入控制台](docs/console.md)，版本变化见 [更新记录](CHANGELOG.md)。

## 查询接口（做看板 / Swift 状态栏用）

1. **CLI JSON**：`kbd today --json` —— 结构见 `keytrack/query.py:day_report`
2. **Python API**：`from keytrack import query; query.day_report(date)`
3. **直接读 SQLite**（Swift 推荐 GRDB / SQLite.swift）：schema 见 [docs/SCHEMA.md](docs/SCHEMA.md)

## Kev 候选建议（实验，默认关闭）

[Kev](https://github.com/jaredpalmer/kev) 是本地决策模型：它可以从给定候选中选择，不能生成新的候选。先在 `127.0.0.1:8009` 启动 Kev 服务，再安装只针对雾凇拼音的候选建议钩子：

```bash
.venv/bin/python kbd.py install-kev-agent /path/to/Kev  # 安装可开关的 0.8B 服务
.venv/bin/python kbd.py setup-kev-rime
.venv/bin/python kbd.py kev on       # 开启；需要时在候选菜单按 Control+Shift+k
.venv/bin/python kbd.py kev off      # 关闭；无需重新部署输入法
.venv/bin/python kbd.py kev status   # 查看当前状态，也可用 kev toggle 切换
```

`install-kev-agent` 安装只监听本机回环地址的 Kev 0.8B 服务，使用 bf16；本机实测运行时 RSS 约 1.6 GB。默认安装后不启动。`kev off` 会关闭输入法建议，并禁用本项目的 Kev 常驻服务（下次登录也不会自启）；`kev on` 会恢复启动。如果 Kev 是用其他命令手动启动的，需自行停止。彻底移除登录服务用 `.venv/bin/python kbd.py uninstall-kev-agent`。

开启后，**平时输入不会调用 Kev**，候选顺序和按键行为保持原样。需要建议时，在拼音候选菜单按 `Control+Shift+k`：鼠须管会把当前拼音、本会话短期语境和前五个候选送到本机 Kev，最多等待 2.5 秒。模型返回后，建议项会显示 `✦ AI`；把握不足的建议显示 `✦ AI ?`，保持原顺序。只有判断概率至少 0.90、领先第二名至少 0.30 时，才把第 2–5 项建议提升到首位。此时再按一次 `Control+Shift+k` 可撤销建议。空格、标点、退格和其他普通按键始终只需按一次。模型不可用时，首项显示 `AI 暂不可用`，候选保持原样；可再次按快捷键重试。

语境只在当前 Rime 会话内存中保留最近 160 个字符，连续上屏的短词会拼成前文；停顿 60 秒，或按退格、光标移动、回车、快捷命令等编辑键后清空。它不读取历史输入日志，也不能确认鼠标移动后的真实光标位置。相同拼音、语境和候选的成功结果最多缓存 30 秒，最多 8 条；再次触发可省去模型请求，失败结果不缓存。首次或不同请求仍会同步等待模型。

安装脚本会备份有改动的 Lua 脚本和 `rime_ice.custom.yaml`，不会改动其他输入方案或 keytrack 采集钩子。请求和响应只在本机 `~/.keytrack/kev-rime/` 的私有目录短暂保存；开关状态保存在该目录的 `enabled` 文件中。关闭状态下 `Control+Shift+k` 也不由 Kev 拦截。

遇到没有建议或感觉服务没运行时，用 `kbd doctor` 检查；它区分实际进程、已加载的服务、已安装的脚本和模型接口，不读取输入内容。`--json` 便于脚本使用，出现错误返回非零退出码。AIME 参考与本轮边界见 [对照记录](docs/aime-reference.md)。

Kev 当前模型主要用英文任务训练，中文五候选判断效果仍属实验性质；高门槛也不能保证推荐正确。开关变更在下一次开始拼音组合时生效。

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
