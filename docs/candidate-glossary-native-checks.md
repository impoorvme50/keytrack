# 候选释义 Lua / native 验证

2026-10-03，方案 E 默认为关闭。只按当前 `candidate.text` 完整匹配本地词表，不回溯 genuine candidate、拆分或查后缀；未匹配文字原样保留。没有新增 filter、processor、网络调用或用户历史读取。

## 引擎接入边界

`keytrack_comments.init(env)` 延迟加载一次词表；`begin_round(env)` 每轮从 Rime 已加载的内存配置读取 `keytrack_glossary/language`，只有字符串 `en`、`ja` 开启释义，缺配置、异常类型、异常值、读取异常和 `off` 均关闭。释义键路径不打开文件、不启动进程。UI 的控制状态由后端保存；语言写入受管理的 daily custom patch 和 prediction snapshot，保存并重新部署后生效。`decorate(candidate, env, options)` 返回原 candidate 或真实 ShadowCandidate；`compose` 保留原注释和 mandatory 提示，再考虑可选释义。

此前每轮 `io.open(control)` 的实现已移除，因为控制路径若是 FIFO 会在打开时阻塞，`pcall` 和读取字节上限无法消除该问题。Lua 不再读取 `HOME/.keytrack/annotations/control`；该文件仅作为 UI 严格状态和备份。这一修正不扩大到 Kev / prediction 原有控制文件。

普通候选由原有 `kev_filter` 注释，预测 segment 由最后的 `prediction_filter` 注释。普通候选的文字、类型、quality、顺序和数量均保留；关闭时无需修改注释的候选保持原对象。每轮只检查前 64 个普通候选，之后原样透传，避免未匹配候选无限查表。释义组件包含 `EN:` 或 `日:` 前缀，最多 24 个 Unicode 字符；总注释超过 64 字符时省略释义，不截断原注释、AI 或联想提示。

预测 segment 保留既有的 `type="prediction"` 归一化行为。这是此前保障 `max_iterations=1` 的引擎契约：实验中保留 OpenCC 包装后的 `simplified` 类型，Tab 上屏「世界」会继续出现「欢迎」。恢复既有类型后，单轮规则再次通过。共享注释模块和所有普通候选均不改类型。

可选模块缺失、空文件、初始化异常、异常返回值均 fail-open。模块生成的 Shadow 用弱表记录原注释，保证幂等与切换语言；不会解析并删除用户普通注释。词表 SHA-256：`8b71cca6dec6dcac7340d159d2f20e41b0649e471ec87f723d1cfd357a51dd96`。

## 合成与真实引擎结果

13 项 Lua 合成契约通过：默认关闭精确不变、内存配置切换、长注释及 Unicode 截尾、缺失/坏词表、缺失/坏配置、64 项预算、Emoji/OpenCC 精确文字、AI/联想组合、坏模块及坏返回值不丢候选。测试 HOME 的注释 control 是没有 writer 的真实 FIFO；普通过滤的默认关闭和英文模式仍完成。直接在 `begin_round` / `decorate` 调用期间禁止 `io.open`、`io.popen`、`os.execute`，证明释义处理不引入文件读取或进程。

在独立临时 HOME、合成翻译器和 fixture DB 中，off/en/ja 三个真实 Squirrel/librime 会话各跑 75 个按键事件。默认关闭会话省略语言配置；英文、日文会话通过 schema 内存配置开启。三者注释 control 都是没有 writer 的 FIFO，候选文字、顺序、数量、上屏结果及采集按键计数完全一致；数字、Tab、Space、Esc、退格、标点、Shift 和 AI 热键通过，capture_version 均为 3，AI 桥各调用一次。最终测试 filter 还检查 yield 的是实际 userdata、普通候选类型和 quality 保留。原有 native_prediction_rime 的 116 键以及 native_kev_rime 的 35 键回归通过。

改为读取内存配置后，普通无 AI 路径在 off/en/ja 各采样 1000 个真实按键，计时包含 `process_key` 和 `get_context`，排除 macOS 候选窗口。以下为 2026-10-03 修正后的单次本机观测，代替旧文件读取版本的计时；非性能保证，也不据此比较微小差异：

| 语言 | median (ms) | p95 (ms) | max (ms) | 释义出现 / 候选出现 |
|---|---:|---:|---:|---:|
| off | 0.248 | 0.289 | 0.494 | 0 / 4998，0% |
| en | 0.272 | 0.369 | 0.681 | 3332 / 4998，66.67% |
| ja | 0.260 | 0.307 | 0.516 | 3332 / 4998，66.67% |

此分母是同一合成菜单反复出现的候选条次，菜单中四个完整词有释义、两个 Emoji 文字未匹配；不能视为真实输入或整个词库的覆盖率。没有测量真实候选窗口，未访问真实输入历史。

## 复现

```sh
python3 -m unittest discover -s tests -p test_comments_lua.py
lua tests/kev_rime_lua_mock.lua
python3 tests/native_glossary_rime.py
python3 tests/native_glossary_rime.py --benchmark
python3 tests/native_prediction_rime.py
python3 tests/native_kev_rime.py
```

native 脚本需要本机 Squirrel 提供的 librime/Lua/predict 插件和仓库 fixture DB；不部署到真实 Rime 目录。计时数值随本机负载变动。
