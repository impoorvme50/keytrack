# 公共接词库：来源、精修与交付状态

2026-10-03。当前随 Keytrack 0.4.3 提供的公共候选资源采用保守精修 v3，**仍未替换 starter、fixture、默认 DB 或本机正在使用的库**。原生常用语发现已单独交付；异步 Kev、自动个人学习和候选译词未启用。真实鼠须管候选窗、点击提交及四类应用验收尚未完成。

## 当前候选：保守精修 v3

严格 v2 的覆盖和整体可接受率退步，已归档到 `data/prediction/quality-v2/`，不作为本轮候选升级。v3 从冻结首版完整键表出发，只去掉纯汉字数词、原词典单字语素、机械重复键和独立暴力动作词；保留其他权重、粒度和查键规则。删除规则及复现见 [精修记录](public-prediction-refinement-v3.md)。

另由独立作者编写 60 个日常／工作完整短语键、180 个下一词候选，未读取评测或个人历史来添加答案。按 **starter > 原创补充 > 原公共表** 整键覆盖，不相加权重；starter 的 224 个键原样保留。补充全部生效，其中 4 个覆盖旧键、56 个是新键。

旧表筛选删除 1,955 对、118 个键；合并补充后的最终差异为删除 1,968 对、增加 179 对、净减少 1,789 对。1 个已有词对改用原创来源的排序权重。

| 当前资源 | 值 |
| --- | --- |
| 公共完整键／词对 | 9,998／33,433 |
| DB | 483,908 字节 |
| 源表 SHA-256 | `a47faf822914012f80de1bb95f2257e4ba2bea9b514f5fc83251d344d328f005` |
| DB SHA-256 | `bcefc0b84279c589b1ec45c2c6e9448a4ea64cc8909c9b182076db6ffd9022b9` |
| 原创补充 SHA-256 | `fe4afb9e5bcb263448a956fae6825c476c73b52aac7b1728e6b2a3f2e3bdaab5` |

`data/prediction/public.*` 与 `keytrack-predict-public.*` 是当前候选；`refined.ngram.tsv` 是含首版 starter 的过滤中间表。`lccc.ngram.tsv` 保留首版纯语料统计，仅为历史来源原料，没有改名冒充精修输出。完整来源链、许可、删除原因、补充来源及哈希见 `public.provenance.json`；首版全部资源保存在 `quality-v1/`。

固定编辑抽查涵盖 120 个旧键的 272 个 Top 3 词对，以及原创补充全部 180 对，共 452 对。仍有 5 个机械／词序疑虑和若干弱搭配，原创补充也有需要继续输入才成句的候选。旧已知片段 `方→二八`、`是的是→的` 已清除，`吧来→吧` 仍存在。评分后没有按这些个例改表；详细发现见 `public-review-findings.json`。这是有限抽查，不是全库错误率。

## 三份冻结评测

同样用最后一次**完整上屏文本**精确查键，无运行时分词、尾词回溯或宽松答案。v1、v2 用于回归；v3 在精修规则和原创补充完成之前独立编写并冻结，评分后未改题、答案、规则或补充。每份分开展示，不合并分母。

| 数据集 | 原公共库命中 → v3 | 整体 Top 3 可接受 | 短语 Top 3 可接受 |
| --- | --- | --- | --- |
| v1，200 条回归 | 78/200 → 83/200 | 39/200（19.5%）→ 43/200（21.5%） | 4/80（5%）→ 8/80（10%） |
| v2，100 条回归 | 28/100 → 29/100 | 6/100 → 6/100 | 1/40 → 1/40 |
| v3，100 条新留出 | 23/100 → 24/100 | 4/100 → 4/100 | 0/40 → 0/40 |

v1 的整体 Top 1 从 19/200 到 22/200，命中内 Top 3 从 50% 到 51.81%。新 v3 留出中 Top 1 为 1/100；命中内 Top 3 从 4/23（17.39%）到 4/24（16.67%）。相对 starter 的新留出命中为 10%→24%、整体 Top 3 为 3%→4%，初始门槛通过。边界在三份数据均不出候选。

保守版改善了旧集的短语覆盖，另外两份整体质量持平，**尚未证明泛化可接受率提高**。完整报告见 [v1 与 starter](public-prediction-evaluation.md)、[与首版的 v1 回归](public-prediction-refinement-v3-regression.md)、[v2 回归](public-prediction-refinement-v3-v2.md)、[新 v3 留出](public-prediction-evaluation-v3.md)。

## 当前引擎验证

Mac17,4、macOS 27.2、Squirrel 1.1.2／librime 1.16.0，私有 HOME、合成翻译、未修改的生产采集器。100 个固定命中键预热后测 1,000 次，前 3 项均与源表一致；无匹配另测 1,000 次。

| 按键处理边界，含采集／观察器／查库 | 中位 | p95 | p99 |
| --- | ---: | ---: | ---: |
| 命中 | 0.2825 ms | 0.5098 ms | 0.7006 ms |
| 未命中 | 0.1564 ms | 0.3230 ms | 0.4550 ms |

性能预算通过，结果在 `data/prediction/public-engine-benchmark.json`。不是纯 DB 查询耗时，不包含真实候选窗；新进程首次选方案只有 1 次、1.5416 ms，缓存未受控，不能当冷启动分位数。源表变化和系统负载不同，不用两轮计时相减宣称提速。

fixture 116 个按键及 Kev 35 个按键的隔离引擎回归均通过，普通拼音、空格、标点、退出、撤销和常用语保持原规则。桌面仍没有成功进入鼠须管中文输入，不能把引擎通过当作候选窗、点击或应用兼容验收。

以下“首版”段落保留第一次交付的来源和历史结果；表中同名资源均指 `data/prediction/quality-v1/`，不代表当前候选。

## 固定来源

使用第一方 [thu-coai/LCCC 数据卡](https://huggingface.co/datasets/thu-coai/lccc/blob/9022ba27075f75c2f59d57d7fa5f42e8d1151aec/README.md)，版本 `9022ba27075f75c2f59d57d7fa5f42e8d1151aec`。该版本的 [官方加载描述](https://huggingface.co/datasets/thu-coai/lccc/blob/9022ba27075f75c2f59d57d7fa5f42e8d1151aec/lccc.py) 把实际文件指向 `silver/lccc`。本项目直接解析该文件，不运行其加载脚本，也不使用青简生成数据。

| 项目 | 固定值 |
| --- | --- |
| 实际文件 | [lccc_base_train.jsonl.gz](https://huggingface.co/datasets/silver/lccc/resolve/5bd582fa28cd7143f2f9c852e08e23089d677c44/lccc_base_train.jsonl.gz) |
| 文件仓库版本 | `5bd582fa28cd7143f2f9c852e08e23089d677c44` |
| 压缩文件 | 369,854,377 字节；SHA-256 `2162e0ed923fba62329cabf7e1493fbe59248afc94a62508e4abdea61e624627` |
| 原始对话组 | 6,820,506 |
| 数据许可 | 数据卡 MIT；原文保存在 `data/prediction/licenses/LCCC-MIT.txt` |
| 分词工具 | jieba 0.42.1，MIT；[官方版本](https://github.com/fxsjy/jieba/tree/1e20c89b66f56c9301b0feed211733ffaa1bd72a)，许可原文在 `licenses/jieba-MIT.txt` |
| PyPI 源包 | `jieba-0.42.1.tar.gz`；SHA-256 `055ca12f62674fafed09427f176506079bc135638a14e23e25be909131928db2` |
| 工具原词典 | `dict.txt`；SHA-256 `7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8` |

原始公开对话与维护者工具只保存在忽略的 `.local/prediction-corpus/`。交付包含派生词对、审查样本、许可和清单；没有原始对话、模型权重、个人输入历史或常用语。分词工具是维护者生成依赖，输入法和安装包运行不需要 jieba。

## 首版处理与规模（历史）

`scripts/generate-public-prediction.py` 在离线环境运行。使用种子 `20261002`，按文件原始顺序对每个对话组用独立伪随机序列以 1/32 概率抽样。得到 213,540 组不同对话、628,540 条语句；1 组完全重复对话去重，822 条超长或命中过滤项的语句不参与提取。不是前 213,540 组截取。

原始文件的 ASCII 空格是字符分隔符，重建语句后用显式指定的原词典分词，`HMM=False`。初始化使用全新私有缓存，不复用系统的 `jieba.cache`。清单记录实际加载模块和词典哈希。

标点、英文、数字、未知词及低词频单字均为硬边界，不跨语句或对话轮次。只接受中文词，单字的词典频次至少 10,000；过滤控制字符、异常重复、联系方式提示及明显不适合展示的内容。每个词对至少出现 5 次、来自至少 3 个不同的抽样对话组。这里的对话支持数是公共语料统计，与个人学习的输入会话无关。

前键最多合并 3 个连续前词、12 个汉字，以分词边界结束。例如完整键 `我想去` 可独立查找后词；运行时不做分词或尾词回溯。每键最多 8 项，按统计次数降序、词文字升序打破同分。每键先归一化到整数权重，再交给已有 builder，重复统计已经完成，不依靠 builder 的“取最大值”合并频次。

人工 starter 的 224 个完整前键拥有独立优先权：命中这些键时使用原有全部候选与顺序，替换该键的语料候选，不相加两种权重。因此 corpus 与合并结果分别保留。

| 产物 | 前键 | 词对 | 用途 |
| --- | ---: | ---: | --- |
| `lccc.ngram.tsv` | 10,000 | 35,481 | 独立语料统计结果 |
| `public.ngram.tsv` | 10,060 | 35,222 | 语料与人工 starter 的整键合并结果 |
| `keytrack-predict-public.db` | 同上 | 同上 | 498,340 字节的候选 DB，SHA-256 `dfe7f736d05fe0c551d8e88f8649b3e76849d1885203dc5dd3d96692317a605d` |

starter、fixture 和现有默认 DB 均保持原字节。原始生成参数与产物哈希见 `public.provenance.json`，匹配的引擎、编译器和 DB 哈希见 `keytrack-predict-public.manifest.json`。

## 首版编辑抽查与质量（历史）

`public-review-sample.json` 固定抽取语料中保留次数总和最高的 20 个键，以及其余键中的 100 个均匀随机键。**该文件展示 starter 覆盖之前的语料候选**。本轮检查其全部 Top 3；另检查其中 12 个被 starter 覆盖的键在最终公共库里的 36 个替代候选。最终相同 120 个键共 286 个 Top 3 词对。

发现 3 个明确机械片段，占此次抽查 3/286=1.05%，涉及 3/120=2.5% 的键：`方 → 二八`、`是的是 → 的`、`吧来 → 吧`。保留为已知质量问题。未在此次样本发现明显辱骂、联系方式或身份号码。这是有限编辑抽查，不是全库正确率；弱上下文、口语和不自然片段仍可能出现。

独立 200 条冻结集在首次评分前编写，未根据候选修改题目或答案。最后一次完整上屏文本精确查键，结果为：

| 指标 | Starter | 新公共候选 |
| --- | ---: | ---: |
| 命中 | 36/200，18% | 78/200，39% |
| 整体 Top 1 可接受 | 12/200，6% | 19/200，9.5% |
| 整体 Top 3 可接受 | 30/200，15% | 39/200，19.5% |
| 命中内 Top 3 可接受 | 30/36，83.33% | 39/78，50% |
| 短语 Top 3 可接受 | 0/80 | 4/80，5% |
| 边界不出候选 | 20/20 | 20/20 |

命中 +21 个百分点、整体 Top 3 +4.5 个百分点，两项初始数据门槛通过。命中内 Top 3 降到 50%，表明新增覆盖中的候选质量仍有限；短语收益也小，不能宣称已有高质量全面接词。完整逐题结果见 [首版评测报告](../data/prediction/quality-v1/public-prediction-evaluation.md)。

## 首版引擎性能与验收边界（历史）

在 Mac17,4、macOS 27.2、鼠须管 1.1.2／librime 1.16.0 上，用私有 HOME、合成翻译、未修改的生产采集器测量。命中组覆盖 100 个固定键，全部预热一遍后测试 1,000 次；未命中组预热 20 次后测试 1,000 次。

| 边界 | 中位 | p95 | p99 |
| --- | ---: | ---: | ---: |
| 命中提交按键处理，含采集／观察器／查库 | 0.1579 ms | 0.1709 ms | 0.1858 ms |
| 未命中提交按键处理 | 0.0787 ms | 0.0879 ms | 0.1027 ms |

`get_context` 包含 Python 解码和释放，单独报告。新进程首次方案选择为 1.3411 ms、只有 1 个样本，系统文件缓存未受控，不能作为冷磁盘 p95。完整结果见 `data/prediction/public-engine-benchmark.json`。这不是纯 DB 时间，也不包含 macOS 候选窗或逐像素显示时间。

已有真实引擎 fixture 回归本轮重跑通过：116 个按键精确采集，空格退出联想、连续空格、数字／Tab、Escape、退格、标点、英文切换、普通拼音、常用语及 Kev 撤销保持原规则。新 DB 在隔离引擎中抽样的 100 个固定命中键，其前 3 项均与源表一致。

本轮桌面自动化在 TextEdit 中没有成功切入鼠须管中文输入；屏幕显示普通英文文本和系统英文纠正，未出现真实 Rime 菜单。因此候选点击、四类应用与至少 100 次真实窗口计时**均未通过**。不因离线门槛通过就替换默认资源。

## 当前候选复现及回退

固定首版派生表、来源清单、原创补充和 jieba 0.42.1 原词典，然后在独立目录生成。工具会核对输入与词典哈希，不读取个人历史，不依赖评测答案：

```sh
.venv/bin/python scripts/refine-public-prediction.py \
  --jieba-path .local/prediction-corpus/tools/jieba-0.42.1 \
  --supplement data/prediction/workday-supplement-v1.ngram.tsv \
  --supplement-provenance data/prediction/workday-supplement-v1.manifest.json \
  --output /absolute/path/refinement-repro
.venv/bin/python scripts/build-predict-db.py --offline \
  --input /absolute/path/refinement-repro/public.ngram.tsv \
  --output /absolute/path/refinement-repro/keytrack-predict-public.db --license MIT
.venv/bin/python scripts/evaluate-prediction.py \
  --baseline data/prediction/quality-v1/public.ngram.tsv \
  --candidate /absolute/path/refinement-repro/public.ngram.tsv \
  --dataset data/prediction/evaluation-v3.json
.venv/bin/python tests/native_prediction_benchmark.py \
  --db /absolute/path/refinement-repro/keytrack-predict-public.db \
  --source /absolute/path/refinement-repro/public.ngram.tsv \
  --output /absolute/path/refinement-repro/benchmark.json
```

相同输入的四类表／清单二次生成逐字节一致，DB 在固定引擎和架构重建一致。严格生成器现在默认输出 `quality-v2/`，避免覆盖当前候选；严格规则文档和旧分数只作为未选实验保留。

默认 builder 仍构建 starter。候选晋升前须备份本机 DB／清单、显式安装并完成真实窗口与点击检查。安装器把显式 `--db-file` 视为自定义库，重复安装保留它；public/custom/merged 模式及个人合并仍属后续范围。

本机没有切换预测库，本轮回退只需退回应用。若以后显式试用候选库，恢复安装前 DB 与清单，再部署、切换方案并确认读到旧库。候选资源和个人常用语互相独立。
