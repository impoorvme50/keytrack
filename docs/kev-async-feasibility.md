# Kev 异步接入能力核验

日期：2026-10-02。阶段 A 的核验已完成；阶段 C 暂不启用。

当前安装的鼠须管 1.1.2 可以在引擎线程重新计算候选，但现有 Lua／Rime 接口未提供完整的输入框焦点边界，也未提供后台结果唤醒鼠须管并刷新静止候选窗的接入点。两项必需关卡均未满足。保留当前主动热键路径；公共接词库和外观工作可以独立继续。

这次只读取已安装的输入法，并在独立进程、临时 HOME 中加载其引擎和 Lua 插件。未修改 `~/Library/Rime`，未部署、重启或替换输入法；未读输入历史或请求模型；未复制青简代码。启动真实候选窗、跨输入框和跨应用验收仍未进行，隔离引擎结果不计作这些验收通过。

## 版本与证据范围

| 项目 | 本轮证据 |
| --- | --- |
| 鼠须管版本 | `/Library/Input Methods/Squirrel.app/Contents/Info.plist` 的 `CFBundleVersion` 为 `1.1.2` |
| librime 版本 | 实际加载已安装引擎后，Lua `rime_api.get_rime_version()` 返回 `1.16.0` |
| 鼠须管源代码 | 官方 `1.1.2` 标签解析为 `876adebaf2f612951dcdca8a591de65401222b9a`；本轮读取该提交的控制器和应用代理 |
| Lua 接口 | 安装插件中的实际对象探测；另参考官方 `hchunhui/librime-lua` 的 `6f30968058a3ca83c47949308ef0ddc51a11a264`。未确认安装插件的源提交，因此上游源代码不替代运行时探测 |
| 本地缓存 | `.local/prediction-build/librime` 为 `a251145d3aafa33871824a40bbec04c966bd8b56`，与安装库不视为同一构建；通知语义再对照官方 `1.16.0` 源码 |

安装二进制的 SHA-256：

```text
Squirrel          d90d5798f9e362f9416456dc2833322429d3374952fb8043fd3639f50819ba16
librime.1.dylib    abb06aa5b3f53de375bc401512b49a7a31b7ed5ee62b2ef7a438512abee5958f
librime-lua.dylib  a0862901b4d36d35aba7012f05c132dd087890cca564609c5d1ea3ba9de7c12b
```

## 关卡结论

| 关卡 | 结论 | 可用能力与缺口 |
| --- | --- | --- |
| 可靠识别应用、窗口、输入框和激活／失活，并推进焦点版本 | **未满足** | 鼠须管控制器收到 IMK 激活／失活事件，但没有向 Rime／Lua发布焦点版本、客户端或输入框标识。引擎通知不能覆盖同一输入框离开后再返回的全部边界 |
| 后台结果唤醒输入线程，静止时安全更新真实候选窗 | **未满足** | 引擎内刷新方法可用；鼠须管没有将结果／属性通知分发到当前控制器的 `rimeUpdate()`。未找到公开的异步结果接入和线程调度接口 |
| 在所属引擎线程重新计算候选 | **隔离验证通过** | `property_update_notifier` 回调可以调用 `refresh_non_confirmed_composition()`；无需追加引擎按键即可改变隔离菜单 |
| 无阻塞请求发布 | **尚未实现／未验证** | 当前 `kev_hotkey.lua` 通过 `os.execute` 同步调用桥接。没有可据此声明通过的有界 IPC 或非阻塞发布机制 |
| 自动跨提交个人学习 | **保持未启用** | 依赖可靠会话边界，当前焦点关卡未满足；提交间时间窗或前台应用采样不能补齐该证据 |

“未满足”针对当前已安装前端和已有接入方式；不表示修改前端后仍不可实现。两个关卡未满足时，不能以“下一次按键再显示”、模拟释放键、轮询候选内容或自动重新部署作为替代实现。

## 焦点与输入会话

官方 [SquirrelInputController.swift](https://github.com/rime/squirrel/blob/876adebaf2f612951dcdca8a591de65401222b9a/sources/SquirrelInputController.swift#L155-L183) 中，`activateServer` 接收客户端并设置键盘布局、清空前端 preedit；`deactivateServer` 隐藏面板、结束组合并清空客户端引用。这些分支没有设置 Rime 焦点属性，也没有向 Lua发布激活／失活事件。

同一文件的 [会话创建与应用选项](https://github.com/rime/squirrel/blob/876adebaf2f612951dcdca8a591de65401222b9a/sources/SquirrelInputController.swift#L312-L344) 将客户端 bundle ID 用于应用配置，并持有一个私有 Rime session。按键事件中应用变化会更新选项，但没有窗口或输入框 ID。不能从“同一个 Rime session”“相同候选文字”推断它是同一次焦点会话。

隔离探测实际安装的 Lua `Context`：

```text
可用：commit_notifier, select_notifier, update_notifier, delete_notifier,
      option_update_notifier, property_update_notifier, unhandled_key_notifier
可用方法：refresh_non_confirmed_composition
返回 nil：activate_notifier, deactivate_notifier, focus_notifier,
          session_id, client, abort_notifier
```

其中 C++ `Context` 的 abort 通知确实存在，但本机插件没有暴露该字段。引擎更新、删除、提交或中英切换事件仍有价值，却不能证明没有引擎状态变化的焦点切换都被捕获。[librime 1.16.0 Context](https://github.com/rime/librime/blob/1.16.0/src/rime/context.h#L78-L89) 与 [Lua Context 绑定](https://github.com/hchunhui/librime-lua/blob/6f30968058a3ca83c47949308ef0ddc51a11a264/src/types.cc#L734-L804) 支持这一接口区别。

另一个容易混淆的名字是 `Session::Activate()`：它只更新 librime 的会话活跃时间，用于回收过期会话；`GetSession()` 也会调用它。它不是 IMK 输入框激活事件，更没有对应输入框失活通知。[librime 1.16.0 Service](https://github.com/rime/librime/blob/1.16.0/src/rime/service.cc#L24-L30)

## 引擎刷新与真实候选窗刷新

隔离探测使用两项自造候选“测试甲”“测试乙”：先用一次引擎 `process_key` 建立组合，然后在同一个所属线程设置 `probe_result=ready`。Lua 属性通知调用刷新方法，菜单顺序改变为“测试乙”“测试甲”。结果设置之后调用 `process_key` 的次数为 **0**。

这证明已安装引擎和 Lua 插件支持主动重新计算菜单。调用由探测程序在所属线程明确发起，并没有后台结果自行唤醒输入线程，也没有启动鼠须管候选面板。

鼠须管 [Rime 通知处理](https://github.com/rime/squirrel/blob/876adebaf2f612951dcdca8a591de65401222b9a/sources/SquirrelApplicationDelegate.swift#L219-L260) 处理部署提示、方案提示和模式状态提示，忽略 `property`。这条路径没有寻找当前控制器、校验客户端或更新候选菜单。其 [分布式通知](https://github.com/rime/squirrel/blob/876adebaf2f612951dcdca8a591de65401222b9a/sources/SquirrelApplicationDelegate.swift#L204-L210) 只提供重新部署和同步，并非结果到达后的候选刷新通道。

真正更新候选的 [rimeUpdate](https://github.com/rime/squirrel/blob/876adebaf2f612951dcdca8a591de65401222b9a/sources/SquirrelInputController.swift#L386-L508) 读取提交、状态和 context 后更新客户端及面板。它由按键处理、候选点击、翻页、光标操作等前端路径调用。现有 chord timer 也能调它，但该路径模拟和弦释放事件，并不是通用后台结果入口，不能用于本方案的静止刷新验收。

本次属性通知回调在发起 API 调用的所属线程内完成，与 [librime `Service::Notify`](https://github.com/rime/librime/blob/1.16.0/src/rime/service.cc#L148-L155) 的直接调用一致。其互斥锁保护通知调用，不能将后台线程切换成输入线程。因此不能让 worker 直接调用 Rime／Lua／AppKit，并把“通知已回调”当作安全线程唤醒。

## 可重复探测

在项目目录运行：

```sh
python3 tests/native_async_capability_probe.py
```

脚本输出版本、二进制哈希、实际 Lua 字段、菜单前后快照和明确的前端证明状态。它只依赖 Python 标准库及本机鼠须管安装文件，使用临时配置与合成文本，不访问现有 Rime 数据。退出前销毁隔离会话并完成引擎 finalize。

本轮断言通过；日志提示临时目录没有 `rime.lua`，脚本仍成功加载独立 `lua_translator@*probe`，并且得到了所需候选。输出中 `frontend_focus_boundary_proven` 和 `idle_real_candidate_window_refresh_proven` 均为 `false`，不把引擎通过包装成桌面验收通过。

## 后续实施条件

若继续阶段 C，需要单独评估鼠须管前端适配：在 IMK 生命周期及客户端变化时发布不可复用的焦点版本；在前端所属线程接收有界结果事件，校验完整版本和候选快照后应用，并调用当前控制器的候选更新。还要实测同一应用不同窗口、同一窗口不同输入框、离开后返回、静止候选窗和输入法切换。是否需要更深入的输入框事件支持，必须由这些测试决定，不能仅依据 `activateServer` 方法存在就判定关卡完成。

这可能涉及前端源码维护、构建、签名、安装、更新与回退。普通项目安装流程继续使用现有输入法；本轮不交付自定义输入法二进制。可靠焦点和静止窗口刷新通过之前，不加入自动应用异步结果或自动跨提交学习。
