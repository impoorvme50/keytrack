# 扩充公共接词库：来源、生成与交付状态

2026-10-03。本轮完成公开语料生成、冻结质量评测、DB 构建及隔离引擎计时。新库仍是**候选资源**：真实鼠须管候选窗、点击提交和四类应用验收尚未完成，因此没有替换 `keytrack-predict.db` 或本机正在使用的默认库。异步 AI 与个人学习没有接入。

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

## 处理规则

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

## 编辑抽查与质量

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

命中 +21 个百分点、整体 Top 3 +4.5 个百分点，两项初始数据门槛通过。命中内 Top 3 降到 50%，表明新增覆盖中的候选质量仍有限；短语收益也小，不能宣称已有高质量全面接词。完整逐题结果见 [评测报告](public-prediction-evaluation.md)。

## 引擎性能与验收边界

在 Mac17,4、macOS 27.2、鼠须管 1.1.2／librime 1.16.0 上，用私有 HOME、合成翻译、未修改的生产采集器测量。命中组覆盖 100 个固定键，全部预热一遍后测试 1,000 次；未命中组预热 20 次后测试 1,000 次。

| 边界 | 中位 | p95 | p99 |
| --- | ---: | ---: | ---: |
| 命中提交按键处理，含采集／观察器／查库 | 0.1579 ms | 0.1709 ms | 0.1858 ms |
| 未命中提交按键处理 | 0.0787 ms | 0.0879 ms | 0.1027 ms |

`get_context` 包含 Python 解码和释放，单独报告。新进程首次方案选择为 1.3411 ms、只有 1 个样本，系统文件缓存未受控，不能作为冷磁盘 p95。完整结果见 `data/prediction/public-engine-benchmark.json`。这不是纯 DB 时间，也不包含 macOS 候选窗或逐像素显示时间。

已有真实引擎 fixture 回归本轮重跑通过：116 个按键精确采集，空格退出联想、连续空格、数字／Tab、Escape、退格、标点、英文切换、普通拼音、常用语及 Kev 撤销保持原规则。新 DB 在隔离引擎中抽样的 100 个固定命中键，其前 3 项均与源表一致。

本轮桌面自动化在 TextEdit 中没有成功切入鼠须管中文输入；屏幕显示普通英文文本和系统英文纠正，未出现真实 Rime 菜单。因此候选点击、四类应用与至少 100 次真实窗口计时**均未通过**。不因离线门槛通过就替换默认资源。

## 复现及后续替换

生成工具只处理显式给出的公开文件，先核对 SHA-256；输出不能覆盖输入、源 starter 或脚本。固定原文件下载到 `.local/prediction-corpus/`，从 PyPI 下载 jieba 0.42.1 源包并核对上表哈希，解压到同目录 `tools/` 后：

```sh
.venv/bin/python scripts/generate-public-prediction.py \
  --input .local/prediction-corpus/lccc_base_train.jsonl.gz \
  --sha256 2162e0ed923fba62329cabf7e1493fbe59248afc94a62508e4abdea61e624627 \
  --source-url https://huggingface.co/datasets/silver/lccc/resolve/5bd582fa28cd7143f2f9c852e08e23089d677c44/lccc_base_train.jsonl.gz \
  --revision 5bd582fa28cd7143f2f9c852e08e23089d677c44 \
  --jieba-path .local/prediction-corpus/tools/jieba-0.42.1
.venv/bin/python scripts/evaluate-prediction.py \
  --candidate data/prediction/public.ngram.tsv \
  --json data/prediction/public-evaluation.json \
  --markdown docs/public-prediction-evaluation.md --fail-on-gate
.venv/bin/python scripts/build-predict-db.py --offline \
  --input data/prediction/public.ngram.tsv \
  --output data/prediction/keytrack-predict-public.db --license MIT
.venv/bin/python tests/native_prediction_benchmark.py \
  --db data/prediction/keytrack-predict-public.db \
  --source data/prediction/public.ngram.tsv \
  --output data/prediction/public-engine-benchmark.json
```

默认 `build-predict-db.py` 仍构建 starter。后续先备份本机管理文件，再以显式 DB 路径安装候选库，完成真实窗口及点击验证后才晋升默认公共版本。当前安装器把显式 `--db-file` 视为自定义库，重复安装会保留它；本轮未提前实现阶段 D 的 public/custom/merged 模式迁移。

回退候选库时恢复安装前备份中的 DB 与安装清单，然后部署、重新切换方案，确认读取上一版本。当前默认库没有被替换，无需执行这一步。公共库升级及个人合并仍需后续独立实现。
