# 下一阶段：Kev 接词候选排序接口

本次本地联想由 `librime-predict` 直接查询本地词库，候选出现不调用 Kev，也不等待模型。这里定义下一阶段的接口，不启用新的模型调用。现有拼音候选快捷键、桥接协议及 AI 开关继续独立工作。

## 请求类型

现有 `kev_rime_bridge.py` 的请求必须带非空 `input`，验证规则是 1–40 个拼音字符。联想候选没有当前拼音，因此不能伪造拼音或放宽现有请求校验。新增独立 `prediction` 分支，拼音请求保持现有兼容协议；未来统一路由可将旧请求归为 `pinyin`。

```json
{
  "type": "prediction",
  "version": 1,
  "request_id": "06bac495-4c06-45db-87f6-a0915d413be8",
  "session_id": "903ac52b-503e-4a57-8682-d35009b827e2",
  "session_generation": 18,
  "focus_generation": 4,
  "schema_id": "rime_ice_predict",
  "prediction_generation": 7,
  "candidate_fingerprint": "sha256:...",
  "previous_text": "去医院看",
  "trigger_text": "看",
  "candidates": [
    {"id": "p1", "text": "医生", "source": "librime-predict"},
    {"id": "p2", "text": "电影", "source": "librime-predict"},
    {"id": "p3", "text": "书", "source": "librime-predict"}
  ]
}
```

`session_id` 由输入会话创建时随机生成，不使用应用名称或历史数据库标识。`session_generation` 在输入、移动光标、退出、切换方案或提交后递增；`prediction_generation` 每次新建或清除联想递增。`focus_generation` 在应用、窗口、输入框或输入会话激活状态变化时递增，并由鼠须管前端的激活/失活事件提供。若无法可靠获得这些前端事件，下一阶段不得应用异步返回结果。

`previous_text` 仅来自当前会话的短期提交上下文，沿用 160 字和 60 秒失效上限；`trigger_text` 是本次提交的词。不要读取按键采集日志、历史输入数据库或常用语内容来填充请求。`candidate_fingerprint` 是规范化编码后的方案 ID、触发词和有序候选 ID/文本的 SHA-256；实现时固定 UTF-8、JSON 字段顺序与转义规则。候选 ID 属于本次快照，不是数据库主键。

请求限制：完整 UTF-8 消息不超过 16 KiB，候选数 2–5、每项非空且最多 48 字，候选 ID 唯一；未知类型、版本、字段类型或超限内容直接拒绝。联想分支不接受 `input` 字段。单个候选无需排序请求。

## 响应及适用条件

```json
{
  "type": "prediction",
  "version": 1,
  "request_id": "06bac495-4c06-45db-87f6-a0915d413be8",
  "session_id": "903ac52b-503e-4a57-8682-d35009b827e2",
  "session_generation": 18,
  "focus_generation": 4,
  "prediction_generation": 7,
  "candidate_fingerprint": "sha256:...",
  "order": ["p2", "p1", "p3"]
}
```

`order` 必须是请求候选 ID 的完整排列，不能增删文字或自动提交候选。接词排序只在用户主动按 Kev 快捷键时请求；是否启用本地联想与是否启用 Kev 分别检查。开关关闭、只有一个候选或非联想状态直接返回，无模型调用。模型服务未运行或请求失败时保留当前本地顺序。

响应到达时，在输入线程上一次性重新核对：当前会话仍激活，所有 generation 与快照一致，本地联想和 Kev 开关仍开着，当前菜单仍是原联想菜单，用户尚未移动选择或确认候选，fingerprint 仍一致，且请求未超时。任一项失败就丢弃，不能重新开启菜单或覆盖新的拼音候选。用户继续输入、删除、Escape、空格退出、标点、切换英文、切换应用/窗口/输入框、切换方案或关闭任一开关，都使待处理请求失效。

不要只比较候选文字：用户输入后又回到相同词语也属于新会话状态。取消可以中止后台任务，但无论取消是否成功，返回结果仍须按上述快照校验。相同会话只保留一个待处理请求；第二次快捷键撤销已应用排序并递增 generation，或取消正在处理的请求。

## 传输及用户交互

沿用 Keytrack 的私有 stdin/stdout JSON 管道：原生 SwiftUI 控制台只读写设置，内置组件负责验证和本地服务请求。新的异步桥接不能在 Rime 按键处理器中同步等待。请求/结果的临时文件若需要保留，须放在 `~/.keytrack/kev-rime/` 并使用 `0700` 目录、`0600` 文件、随机名称、原子发布和读后删除；stdout 仅输出协议，诊断写 stderr。不要引入 WebKit、Electron、监听端口或新的后台模型服务。

排序结果保留「联想」标记，可附加 `✦ AI` 表示用户触发过 Kev；选择仍使用本地联想的明确选择方式，空格不因 AI 排序变为提交接词。再次快捷键撤销只恢复同一快照的原顺序。排序不增加连续联想轮数，按键采集器仍排第一、Kev 热键处理器紧随其后。

下一阶段验收须覆盖请求校验、普通拼音请求兼容、主动触发、无服务回退、顺序完整性、撤销，以及输入后回到同文本、跨应用、关闭开关、选中后返回、乱序响应等过期结果场景；同时重新验证真实鼠须管候选窗口。仅桥接或引擎测试通过不能代替前端焦点事件和真实菜单验证。
