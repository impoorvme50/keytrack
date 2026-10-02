# 可选候选释义

2026-10-03，本机 0.4.4 提供默认关闭的英文／日文候选释义。在「输入与 AI → 候选释义」选择一种语言，点击「保存并应用」；只查询应用附带的本地词表，未收录的词保留原注释。

首版收录 120 个完整汉字词，由本项目独立编写简短中英日译法，MIT 许可。它是入门词表，多义词只选常用义，未作专业辞典审校；不会根据上下文生成解释，也不附日语读音。来源、覆盖与源 SHA 见 [词表说明](../data/annotations/README.md) 和 [来源清单](../data/annotations/manifest.json)。不访问历史、网络或模型服务，不新增个人学习或词汇掌握统计。

## 输入与注释边界

- 只按当前显示的完整候选文字精确匹配；不拆词、去后缀或读取包装前的文字。Emoji、繁体转换及常用语未精确匹配时保留原注释。
- 共享注释模块接入已有 Kev／联想过滤器，不增加过滤器或按键处理器。普通输入的候选文字、类型、质量、顺序、数量与上屏规则保持。
- 原注释、`✦ AI`、`联想 · 数字/Tab` 优先保留。释义带 `EN:`／`日:`，最多 24 个 Unicode 字符，超长加省略号；组合注释超过 64 字时先省略释义，原标记不会被截断。
- 每轮至多检查 64 个候选；后续继续原样输出。词表初始化时只载入一次；每轮从 Rime 的内存配置读取语言，不在按键链读取释义控制文件、启动进程或等待模型。
- 预测 segment 沿用原有 `prediction` 类型归一化：librime-predict 依靠该类型控制最多一轮。释义模块本身保留类型；取消这项既有处理会导致二轮联想，已用隔离引擎复现并回归。

## 安装、保存与恢复

默认开关缺失即关闭。应用升级不自动重装 Rime、替换默认接词 DB 或开启释义。释义关闭时，已验证的前版过滤器仍视为兼容，本机原联想开关继续可用；只有显式启用释义才更新这两个过滤器。显式启用时，保存事务会备份，安装 `keytrack_comments.lua`、编译词表并更新已有两个末尾过滤器，同时将语言写入日常方案的独立受管 patch 与已安装的实验 snapshot，重新部署后生效。`~/.keytrack/annotations/control` 仅供控制台显示和备份：`language=en` 或 `language=ja`，Lua 不读取它。不改变 Kev、联想及采集开关。

新旧设置文件兼容；旧客户端保存其他设置时保留当前语言。脚本只接受当前发布字节或明确记录的前版 SHA；独立修改会拒绝覆盖。控制、脚本和设置参与版本复核，外部变化要求刷新。私有路径拒绝符号链接和非普通文件；macOS 的 `/var`、`/tmp` 精确系统别名除外。

恢复备份只恢复释义语言和原有受管设置，保留当前脚本版本和后来独立修改。旧备份没有释义字段时关闭释义；不会把新的过滤器还原成空模块。需要立即回退时选择「关闭」并保存；如需完整退回应用，可退出后使用 `.local/qingjian-round3/Keytrack-0.4.3-previous.app` 替换 `/Applications/Keytrack.app`。启用时的脚本原字节也保存在控制台自动备份内，手动恢复应先退出输入会话并检查之后的独立修改。

## 验证记录

全部测试使用公开词和自造数据。原生设置演示中已验证：默认关闭、英文／日文预览保留标记、保存与刷新、恢复到关闭，AI／联想开关不变。样例预览与真正的鼠须管候选菜单分别验收。

隔离 librime 对 off／en／ja 各运行相同的 75 个键事件，逐项比较候选、上屏与 capture_v3 计数；数字、Tab、空格、标点、Escape、退格、Shift、AI 热键及撤销／重用保持一致。缺词表、损坏词表、异常内存配置、FIFO 控制文件不阻塞、长注释、64 项上限及 Emoji／OpenCC 包装另有合成契约检查。

178 项 Python 回归、原生模型 32 个断言和原常用语 49 个断言通过。新的语言 patch 与快捷键、常用语、联想 snapshot 的保存／恢复一起检查。完整引擎契约、计时边界与复现见 [Lua／native 验证](candidate-glossary-native-checks.md)。

**实际鼠须管候选窗、点击和四类应用尚未验收。** 释义作为默认关闭的本机可选功能交付；不能将设置预览或隔离引擎通过写成实际菜单已通过。异步 Kev 和自动跨提交学习继续未启用。

## 本机交付

`/Applications/Keytrack.app` 已更新为 0.4.4，签名完整性通过；旧 0.4.3 应用完整保存在 `.local/qingjian-round3/Keytrack-0.4.3-previous.app`。此次只替换应用，14 个设置、常用语、Rime 配置／过滤器、默认 DB 与 AI／联想／释义控制路径的 SHA 或不存在状态保持一致；本机释义仍关闭，原已开启的联想继续被新版识别为兼容。

`dist/Keytrack-0.4.4-apple-silicon.dmg` SHA-256：`02d444a428b932c8e1001ff5c55f84bf9ff5c4217c10366ab37acc56cc622cca`，附 `.sha256` 文件。镜像校验、镜像内应用签名，以及源码外、只读且含空格挂载路径中的独立运行检查全部通过。未发布远程版本。

SwiftUI 演示的两语切换、保存／刷新和恢复在自造环境中走通；最终运行组件完成包级检查。首次交付时锁屏阻止了最后的窗口重开，用户解锁后已完成补验：退出旧进程、重开 `/Applications/Keytrack.app`，生产窗口显示释义入口与 120 词说明；英文／日文公开样例正确保留 AI／联想标记，「放弃修改」恢复关闭，原 Kev／联想开关均保持开启。

解锁后的检查没有保存生产偏好、启用释义或查询历史原文。15 个受保护路径（原 14 项加常用语 Lua 数据）前后 SHA／不存在状态一致。TextEdit 两次启动超时；改用 Keytrack 搜索框逐键输入公开的 `nihao`，切源快捷键前后仍为英文文本，没有取得实际鼠须管候选窗。已请求用户手动切换中文输入源，该菜单验收仍单独保持未完成。日常 Rime 组件会在用户显式启用释义时更新。

复现：

```sh
.venv/bin/python scripts/build-glossary.py --check
.venv/bin/python -m unittest discover -s tests
.venv/bin/python tests/native_glossary_rime.py
xcrun swiftc -swift-version 5 -target arm64-apple-macosx26.0 \
  -module-cache-path /private/tmp/keytrack-swift-cache \
  macos/ConsoleModel.swift tests/native_glossary_model.swift \
  -framework AppKit -framework SwiftUI -o /private/tmp/keytrack-glossary-model
/private/tmp/keytrack-glossary-model
scripts/build-console.sh
.venv/bin/python scripts/check-package.py dist/Keytrack.app
scripts/package-console.sh
```
