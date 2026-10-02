# 本地接词联想实验版

本次在 `da6b2b7` / v0.4.1 基线上加入独立实验方案 `rime_ice_predict`，显示名称为 **雾凇拼音 · 接词实验**。实施前已核对本地与远端 HEAD 均为 `da6b2b7`，原有 52 项 Python 测试通过。日常 `rime_ice` 仍是回退入口；历史数据库、常用语和外观继续使用原文件。

## 开始使用

原生 Keytrack 的「输入与 AI」页面分别提供「本地接词联想」与「Kev 候选建议」。首次安装联想关闭，默认显示 3 项，连续联想最多一轮。关闭或开启本地联想不改变 Kev 开关，也不启动、停止或等待模型服务。设置通过原有私有 stdin/stdout JSON 管道调用内置组件。

源码安装：

```sh
cd /Users/johnliu/keyboard
.venv/bin/python kbd.py setup-prediction
.venv/bin/python kbd.py prediction status
```

鼠须管重新部署完成后，按 `Control+grave` 或 `F4` 打开方案选单，翻到「雾凇拼音 · 接词实验」。保留的「雾凇拼音」方案不启用联想。原生页面的开关开启后，下一次按键生效；也可以使用：

```sh
.venv/bin/python kbd.py prediction on
.venv/bin/python kbd.py prediction off
```

原生安装包附带已经生成的接词库和运行组件。安装时使用当前鼠须管的 `librime-predict.dylib`，不安装或替换引擎插件，不需要在用户机器上编译词库。原生页面若显示尚未安装，点击「备份并安装实验方案」。

## 操作

| 操作 | 结果 |
| --- | --- |
| 普通拼音提交一个词 | 命中本地词库则显示少量带「联想 · 数字/Tab」标记的接词；查不到就继续普通输入 |
| 数字 1–3 | 明确选择对应接词；候选数可设置为 1–5，超出实际菜单的数字先退出联想，再按普通输入处理 |
| Tab | 提交当前高亮接词；提交后不再连续接词 |
| 鼠标点击 | 沿用鼠须管原生候选选择机制；本轮自动化未完成点击提交验证，数字键和 Tab 已实测 |
| 继续输入字母 | 关闭原联想，开始新拼音输入，不提交联想 |
| Escape | 关闭联想并消耗本次 Escape |
| 第一次 Backspace | 只关闭联想，保留刚提交的文字 |
| 再按 Backspace | 没有输入法组合时传给应用，按应用规则删除已提交文字 |
| 空格 | 联想出现后再按空格，先退出联想，再把空格交给应用；连续空格不会选中接词 |
| 标点 | 先退出联想，再按当前方案的中英文标点规则提交 |
| Shift 英文切换、其他快捷键 | 先退出联想，按原方案和应用规则处理 |
| Kev 快捷键 | 普通拼音候选仍按现有方式显示建议、再次触发撤销；本阶段不对联想候选调用模型 |

注意区分两种空格：**普通拼音候选中的空格照常提交该词；随后处于联想状态的空格仅退出并传给应用。** 引擎测试确认它返回“不处理”，应用通常因此插入空格；应用自己的快捷键和编辑行为由应用决定。开始新的普通拼音后，空格恢复常规候选提交。

上游默认可用空格选中零长度联想片段，本实验用独立 Lua 处理器明确退出；清除片段前暂时关闭内部 prediction option，避免上游立即重建同一菜单。上游 translator 的候选上限检查可能多显示一项，最终过滤器严格按控制台的 1–5 项设置裁剪。[上游实现](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/src/predict_translator.cc)

## 配置与处理顺序

实验方案从**已经部署成功的日常方案**制作受管快照，保留最终合并后的字典、输入规则、常用语翻译器、Kev 参数及其他过滤器。重新运行 `setup-prediction` 可以刷新快照。控制台内的 Kev 快捷键修改、首次常用语接入和对应恢复会自动同步实验方案；手动修改日常其他规则后，需要重新运行安装以刷新。

实际部署处理器前四项：

```text
0  lua_processor@*keytrack_logger
1  lua_processor@*kev_hotkey
2  lua_processor@*prediction_guard
3  predictor
   ... 原有处理器，包括 key_binder、speller 等
```

采集器始终第一，Kev 紧随其后。predictor 在 key_binder 之前，符合[上游要求](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/README.md)。没有把上游的 `@before 0` 补丁直接写入现有方案，日常处理链未增加 predictor。内部 prediction option 不显示第二个开关，避免与控制台的持久开关冲突。

| 文件 | 用途 |
| --- | --- |
| `~/Library/Rime/rime_ice_predict.schema.yaml` | 受管实验快照，包含安全处理链和 predictor 配置 |
| `~/Library/Rime/lua/prediction_guard.lua` | 按键退出和明确选择，逐键读取独立开关 |
| `~/Library/Rime/lua/prediction_filter.lua` | 候选上限和联想标记 |
| `~/Library/Rime/keytrack-predict.db` | 原生本地接词库 |
| `~/Library/Rime/default.custom.yaml` 内受管块 | 将实验方案追加到方案选单；保留原方案和原有内容 |
| `~/.keytrack/prediction/control` | 独立持久开关、候选数量及一轮限制，0600 文件 |
| `~/.keytrack/prediction/installed.json` | 管理文件记录、自定义接词库保留状态 |
| `~/.keytrack/prediction/backups/` | 修改前的配置、脚本、词库备份和变化清单 |

控制文件为完整三行：`enabled=0`、`max_candidates=3`、`max_iterations=1`。原子发布，Python 与 Lua 都严格检查；缺失或损坏时 Lua 不启用联想。`prediction off` 可以修复格式损坏的控制文件。符号链接路径被拒绝。

安装会先检查采集器与 Kev 位置、外部同名方案、外部 Lua、同名词库、实验自定义补丁及方案列表追加位置。其他插件占用时拒绝覆盖。所有受影响的既有文件先备份，方案列表入口最后发布；中途失败时恢复已经写入的旧文件。新创建的惰性实验文件保留，遵守本机 Rime 的禁止删除规则。重复安装保持文件内容和备份数量不变，保留当前开关以及明确替换的自定义接词库。

默认接词库为原创 MIT 起步数据，224 个前词、896 条人工词对；适合验证交互，覆盖有限。个人历史没有被用于词库生成或学习。生成版本、许可、文件位置、精确小词库和替换命令见 [词库说明](prediction-data.md)。

## 回退

只停止联想：关闭原生开关，或运行 `kbd.py prediction off`。下一次按键清除联想菜单，普通拼音和普通空格照常工作。

随时切回日常方案：鼠须管 `Control+grave` / `F4` 方案选单选择「雾凇拼音」。这个方案从未增加 predictor，因此不依赖实验文件。

撤回实验入口：

```sh
.venv/bin/python kbd.py prediction rollback
```

这个命令关闭独立开关，备份当前 `default.custom.yaml`，仅移除本实验受管的方案列表块，再请求重新部署。之后切回「雾凇拼音」。不会删除词库、脚本或方案文件，不还原整份旧配置，也不会覆盖安装后新增的用户设置。原生页面会显示可单独重新安装实验方案；日常采集和 Kev 仍保持已安装状态。

如需逐文件恢复旧版实验内容，从 `~/.keytrack/prediction/backups/<时间>/` 取同名文件，先再次备份现状，再只恢复需要的文件并重新部署。`manifest.json` 区分原有文件和本次新建文件。不要用旧整份 `default.custom.yaml` 覆盖已经有新编辑的配置；回退命令可以保留这些编辑。

本机原生程序也已备份。若要恢复实施前的 Keytrack，先关闭联想并撤回实验入口，退出 Keytrack 控制台；把当前 `/Applications/Keytrack.app` 移到一个新的备份位置，再将 `~/.keytrack/backups/local-prediction-20261002-160258/Keytrack.previous.app` 复制回 `/Applications/Keytrack.app` 并重新打开。保留 `~/.keytrack/` 历史和设置，不使用整目录旧备份覆盖它。原生程序回退与 Rime 实验入口回退是两个独立步骤。

## 验证记录（2026-10-02）

自动测试与实际桌面试打分别记录；没有把引擎候选快照当作候选窗显示成功。

- 原基线：52 项 Python 测试通过。
- 最终 Python 回归：83 项通过；两个原生引擎脚本、Lua mock/context、内置程序隔离包校验和 git diff 检查通过。
- `tests/native_prediction_rime.py` 使用隔离 HOME、自造小词库和自造普通候选，动态加载本机实际 librime、Lua、predict 插件。实际编译方案和方案列表补丁，保留原入口。116 次已知按键精确匹配；分钟切换使用可控时钟，两个新桶均为 `capture_version: 3`，释放事件不计数。
- 引擎覆盖：默认关闭、开启命中、无匹配、严格三项标记、一轮上限、数字/Tab 选择、空格连续三次传给应用、不存在的数字标签、继续字母、标点、退格、Escape、Shift 英文切换、常用语、Kev 快捷键/标记/撤销/缓存；本地联想不会新增 Kev 请求。
- 原 `tests/native_kev_rime.py` 继续通过：35 次按键精确记录、原生 AI 标记/撤销、普通 Space、逗号及多行常用语。
- 实际内置程序在隔离 HOME、只有系统 PATH、失效 PYTHONHOME/PYTHONPATH 下完成默认库安装、重复安装、自定义库替换后保留、独立设置、备份恢复与采集测试。
- 本机 Rime 修改前执行 lint；修改后执行其 AGENTS 要求的 `make -C others/script/ lint`。现有 Lua 有 8 项旧警告、0 错误，新增脚本无警告。没有修改中文主词典、OpenCC 或构建源，因此未触发词典生成 build。
- 真实部署日志：`finished updating schemas: 12 success, 0 failure`，`3 tasks ran: 3 success, 0 failure`。第一次因末尾缺少换行失败后已修复，并增加无结尾换行回归测试。

耗时在本机真实引擎中测量；提交按键的时间包含日志观察器、引擎提交、本地查库和菜单计算，不能称为纯 DB 查找耗时。最终一轮 11 次测量的中位数约 **0.24 ms**，最大约 **0.37 ms**；读取候选上下文中位数约 **0.02 ms**，最大约 **0.06 ms**。这是自造小库的热状态实测，不代表更大词库、冷启动或 macOS 绘制时间。

实际鼠须管使用默认 starter 库另测 11 次：从 CGEvent 提交按键按下，到 WindowServer 首次报告鼠须管可见候选窗的新布局，中位数 **34.15 ms**，最大 **43.20 ms**，范围 **26.21–43.20 ms**。每轮先确认普通拼音候选窗存在，再提交 `你好`，轮后截图确认实际显示 `请问 / 很高兴 / 最近`。轮询间隔约 1 ms，窗口查询和系统调度会计入；这个值度量前端可见窗口布局更新，不是逐像素绘制完成时间。它与引擎计算采用不同词库和测量边界，不能相减来估算纯绘制成本，也不包含截图工具往返时间。本地联想全程不等待模型推理。

复现检查：

```sh
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python tests/native_prediction_rime.py
.venv/bin/python tests/native_kev_rime.py
lua tests/kev_rime_lua_mock.lua
lua tests/kev_context_lua.lua
luacheck rime --globals yield ShadowCandidate Candidate --no-max-line-length
.venv/bin/python scripts/check-package.py dist/Keytrack.app
git diff --check
```

下一阶段独立 prediction 请求类型、当前会话前文、候选快照和过期返回丢弃设计见 [Kev 接口设计](prediction-kev-interface.md)。它不会放宽现有非空拼音桥接校验；可靠的应用/窗口/输入会话焦点事件仍是异步应用结果的前置条件。

## 实际桌面验收

已更新 `/Applications/Keytrack.app` 并验证签名；旧应用保存在 `~/.keytrack/backups/local-prediction-20261002-160258/Keytrack.previous.app`。真实 SwiftUI 页面显示独立的联想开关、候选数量和一轮上限，实测「关→开→候选3改4→恢复3→关」正常，Kev 始终保持原来的开启状态，快捷键保持 Control+Shift+k，已有模型接口仍可用。

实际 Rime 上已验证回退后再安装、重复安装保持内容和备份数量不变。日常 `rime_ice.schema.yaml`、`rime_ice.custom.yaml`、`custom_phrase.txt`、`squirrel.custom.yaml` 与常用语数据文件在回退/重装前后哈希一致。交付时联想恢复默认关闭、3 项，实验方案入口保留。

用户已明确授权系统级按键模拟，仅在本次新建的空白文本编辑文稿中试打。每次发送测试键前核对前台为文本编辑；用户使用其他应用时停止发送，待用户明确腾出测试文稿后继续。真实窗口验收结果如下：

- `nihao` 普通空格提交 `你好`，实际候选窗显示 `请问 / 很高兴 / 最近`，三项均带「联想 · 数字/Tab」标记。数字 2 提交 `很高兴`，Tab 提交首项 `请问`，两者之后均未继续第二轮联想。
- 联想后连续三次空格只向文稿加入三个空格；没有提交任何接词。继续字母直接出现普通 `ni hao` 拼音候选。Escape 关闭联想并保留文字；第一次退格只关闭，第二次删除已提交的一个字。
- 逗号按既有规则提交中文逗号；Shift 切到英文后 `abc` 和空格直接输入，再切回中文正常。现有 `shuxuguan` 自定义短语正常上屏 `鼠须管`，未命中接词时没有候选窗。
- 既有 Control+Shift+k 实际显示 `✦ AI ?` 建议标记；再次按快捷键撤销标记，原候选顺序恢复，未提交拼音或接词。
- 在真实 SwiftUI 控制台关闭联想，Kev 仍为开启；继续字母、普通空格提交以及连续空格正常，没有联想候选窗。方案选单切回原「雾凇拼音」，普通输入继续正常。
- 采集器位置在实际部署配置中核对为第一项。真实试打的新分钟数据中，总按键数与有效采集数一致（16:23 为 52/52、16:24 为 89/89、16:25 为 23/23、16:26 为 4/4）；精确已知序列及版本断言另由隔离引擎的 116 次按键、两个 `capture_version: 3` 桶验证。

本轮未完成鼠标点击提交的自动验证：桌面工具点击候选行未触发提交，数字键与 Tab 选择已经完成真实窗口验收。当前界面计时范围见上文，逐像素绘制时间未测。试打完成后已关闭联想、保持三项，并切回日常方案。

手动试打步骤（使用默认 starter 库）：

1. 开启控制台的本地联想，选择「雾凇拼音 · 接词实验」。
2. 输入 `nihao`，普通空格提交 `你好`，应显示 `请问 / 很高兴 / 最近`，每项带「联想」标记。
3. 再连续按三次空格：不应上屏任何接词；接着输入 `nihao` 仍能正常出普通拼音候选。
4. 再提交 `你好`，分别试数字 2、Tab、字母、Escape、第一次与第二次退格、逗号及 Shift 中英切换。
5. 使用现有常用语编码，普通空格应照常提交；在普通拼音候选中按 Kev 快捷键检查标记，再按撤销。
6. 关闭联想、切回「雾凇拼音」，继续普通输入。候选窗显示延迟需要单独计时，不能拿自动化工具的往返时间作为绘制耗时。
