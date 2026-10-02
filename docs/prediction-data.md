# 本地接词库与复现

本实验使用鼠须管已经带有的 `librime-predict`；接词查询在 Rime 引擎内进行。安装使用仓库中已生成的数据库，运行时不下载词库、不启动模型服务，也不等待 Kev。

## 来源与覆盖

| 文件 | 用途 | 来源与许可 |
| --- | --- | --- |
| `data/prediction/starter.ngram.tsv` | 224 个前词、896 条接词记录，每个前词 4 个接词 | 2026-10-02 为此实验原创整理的日常交流、工作与输入法操作词对；MIT，见同目录 `LICENSE.txt` |
| `data/prediction/fixture.ngram.tsv` | 3 个前词、6 条精确测试记录 | 为自动测试自造；MIT |
| `data/prediction/keytrack-predict.db` | 默认实验接词库，18,700 字节 | 从 starter 文件生成 |
| `data/prediction/keytrack-predict-fixture.db` | 隔离引擎测试库，5,272 字节 | 从 fixture 文件生成 |
| `data/prediction/*.manifest.json` | 源文件、工具版本与结果的 SHA-256 | 与数据库同步生成 |

starter 的 `100 / 90 / 80 / 70` 是人工候选顺序权重，**不是语料出现次数或语言模型概率**。它是一份规模适中的实验起步库，适合检查提交、选择、取消与继续输入，覆盖远小于统计接词语料。查不到前词时不产生联想，正常继续输入。原有雾凇拼音词典独立保留。

本次没有从个人输入历史、历史数据库或常用语读取数据。词库不含 `$` 起始记录，因此刚切换方案、空前文时不会展示启动候选。

## 上游读取结果

上游版本固定在 [`920bd41ebf6f9bf6855d14fbe80212e54e749791`](https://github.com/rime/librime-predict/tree/920bd41ebf6f9bf6855d14fbe80212e54e749791)，项目许可为 [BSD-3-Clause](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/LICENSE)。

[`Predictor`](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/src/predictor.cc) 在提交后以**最后一次提交的整个文本**作为查询键。它不分词、不回溯完整会话，也不从输入历史学习。标点、原样直输及英文直通提交会清空预测。命中后创建长度为零、带 `prediction` 与 `placeholder` 标签的片段；[`PredictTranslator`](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/src/predict_translator.cc) 输出类型为 `prediction` 的候选。

[`PredictDb`](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/src/predict_db.cc) 用 Darts 精确匹配前词，以 MARISA 字符串表存放接词，文件头为 `Rime::Predict/1.0`。它不是 SQLite 数据库。[`build_predict`](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/tools/build_predict.cc) 从标准输入接收 `前词 TAB 接词 TAB 权重`，按输入顺序写候选，不负责排序。

[`make_predict_data`](https://github.com/rime/librime-predict/blob/920bd41ebf6f9bf6855d14fbe80212e54e749791/tools/make_predict_data/src/main.rs) 接受两列源数据：

```text
你好 世界<TAB>100
你好 朋友<TAB>90
```

前后词之间是一个 ASCII 空格，`<TAB>` 表示真正的制表符。也支持 `完整短语 TAB 权重`：上游会在每个 Unicode 字符边界切成前缀与后缀；这不等同于分词接词。此实验全部使用显式词对，避免把人工短语切分当作自然接词统计。

重复词对取最大权重；接词按权重降序排列，同权重保持源文件顺序。以 `$` 作为后词的记录被丢弃。本仓库预处理脚本复现这些规则，并提前拒绝空词、歧义空白、控制字符、负数、超出 u32 的权重和列数错误。

## 生成命令

维护者生成需要 Python 3.9 以上、Git、Apple clang++、Boost 头文件和当前鼠须管的 `librime 1.16.0`。安装和日常使用不需要这些编译工具。不同 librime 私有 C++ ABI 不能直接混用，升级引擎版本时应先更新匹配的头文件版本，再重新做隔离测试。

```sh
cd /Users/johnliu/keyboard
.venv/bin/python scripts/build-predict-db.py
.venv/bin/python scripts/build-predict-db.py --fixture
```

脚本在 `.local/prediction-build/` 缓存固定源码，检查缓存的提交和未修改状态，编译**原版** `tools/build_predict.cc` 与 `src/predict_db.cc`，链接现有鼠须管 librime。辅助编译关闭日志宏；无需构建 glog 或替换鼠须管插件。

| 依赖源码 | 固定提交 |
| --- | --- |
| librime-predict | `920bd41ebf6f9bf6855d14fbe80212e54e749791` |
| librime 1.16.0 头文件 | `a251145d3aafa33871824a40bbec04c966bd8b56` |
| darts-clone | `87b71afd6cf784953e3c08f24c64203397f3b724` |
| marisa-trie 头文件 | `3e87d53b78e15f2f43783d5e376561a8c9722051` |

首次生成会从上表对应 GitHub 仓库拉取源码。拉取先在临时目录完成，检查固定版本后再写入缓存；失败可直接重试，已有干净缓存保持原样。已有缓存时可以禁止网络访问：

```sh
.venv/bin/python scripts/build-predict-db.py --offline
.venv/bin/python scripts/build-predict-db.py --fixture --offline
```

只检查或导出预处理数据无需下载和编译：

```sh
.venv/bin/python scripts/build-predict-db.py --preprocess-only > /tmp/keytrack-predict.tsv
```

上游 Rust 转换工具没有随仓库固定 Cargo.lock，因此正常生成使用标准库 Python 实现，省去随时间漂移的 Rust 依赖解析。此次已实际运行该固定版本的 Rust 工具，对 starter 源的两种预处理结果进行逐字节比较，结果完全一致。两个数据库各重复构建一次，SHA-256 均保持一致：

```text
starter  cc1a47780029f38f85cefd69773ab5e5b9d57f8f13e437187d3519f8ab3bd207
fixture  67f2b18ebeb1a501d82579c697ff8d2952841afd6d051fabee5a0e8f4de472ad
```

清单记录当前机器的编译器、架构与 librime 文件哈希。相同受控环境下可以复现；不同引擎或架构需重新构建并做引擎兼容验证，不承诺跨版本二进制哈希相同。

## 替换接词库

准备有明确来源和许可的两列 `.ngram.tsv`，另存其来源说明。自定义生成必须提供真实的 SPDX 许可标识，不能沿用 starter 的 MIT 标签冒充其许可：

```sh
.venv/bin/python scripts/build-predict-db.py \
  --input /absolute/path/custom.ngram.tsv \
  --output /absolute/path/custom-predict.db \
  --license MIT --offline
.venv/bin/python kbd.py setup-prediction --db-file /absolute/path/custom-predict.db
```

`--input` 可重复传入多个源文件；`--max-candidates` 控制数据库每个键保留的数量，默认 8，与界面默认显示 3 个不同。输出数据库和清单必须与输入源分开保存，路径冲突时脚本拒绝生成。生成先写临时文件，确认文件头后替换输出文件；安装流程会备份被本实验管理的旧接词库，并拒绝初次覆盖不属于本实验的同名文件。

实验方案 ID 为 `rime_ice_predict`。安装到 Rime 用户目录的固定名称为 `keytrack-predict.db`，`predictor/db` 引用该名称。替换后重新部署鼠须管，切换到实验方案、开启联想，再用已知键验证新库。切换原 `rime_ice` 方案即可回到原输入入口；关闭本地联想可保留实验方案继续普通输入。完整配置回退以安装记录的备份为准。

精确测试使用 fixture：提交 `你好` 应出现 `世界 / 朋友 / 今天` 三项；库中保留第四项是为了检测候选上限是否真正生效。选择 `世界` 后不再显示 `欢迎`，验证最多一轮；提交未收录的词时不出现菜单。上游 translator 的候选上限检查在追加后执行，可能多出一项，因此实际显示上限由本实验过滤器再限制。

## 个性化学习另行实现

现有按键与提交历史继续只承担原来的记录、查询和统计用途。本次没有学习程序或后台训练任务。

下一阶段可另设默认关闭的“个性化接词学习”：仅在明确开启后收集同一会话内相邻词对；标点、英文切换、应用切换及超时划定边界；只保留本地聚合计数，不保存完整前文。独立数据目录、导出和清空入口使学习数据能够单独删除。候选应经过最小出现次数、重复合并与长度限制，再写入新的个人 DB；来源清单与通用 starter 分离，替换前经过相同隔离输入测试。它不应扫描既有历史数据库作为默认导入步骤。
