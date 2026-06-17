# podcast-insights

把播客单集 → 校对转录稿 → **结构化推荐数据** 的流程固化下来，并在此基础上做查询/可视化。

首个数据集是小宇宙播客 **《肥话连篇》**（`config/feihua.json`）。流程按"多播客"设计：
新增一档播客只需加一份 `config/<key>.json`，数据落在 `data/<key>/`，脚本用 `PODCAST=<key>` 切换。

> 本仓库**不含任何密钥**。所有敏感信息（小宇宙 token、转录服务 token）从 `.env` 读取，`.env` 已 gitignore。

---

## 目录结构

```
podcast-insights/
├── config/<key>.json        # 每档播客的配置（pid、主播名、人名归一规则…）
├── pipeline/                # 固化的 6 步流程
│   ├── _common.py           # 共享：配置/路径/.env
│   ├── 1_fetch_episodes.py      # 小宇宙 API 拉全部单集
│   ├── 2_submit_transcribe.py   # 提交 VideoTranscriptAPI 分说话人转录
│   ├── 3_fetch_calibrated.py    # 下载校对稿 TXT
│   ├── 4_normalize_names.py     # 主播人名 ASR 误写归一
│   ├── 5_extract.workflow.js    # 结构化提取（Claude Code Workflow，Sonnet）
│   └── 6_aggregate.py           # 校验 + quote 反查 + 聚合总清单
├── data/<key>/
│   ├── episodes/            # episodes.json、view_urls.{json,txt}
│   ├── transcripts/         # {vol:03d}_{title}.txt（gitignore，可再生）
│   ├── extracted/           # {vol:03d}.json（结构化推荐，入库）
│   └── recommendations_all.{json,md}   # 聚合产物
├── docs/pipeline.md         # 流程详解 + 各步契约/坑
└── web/                     # 后续查询/可视化（占位）
```

## 快速开始

```bash
cp .env.example .env        # 填写 token
python -m pip install requests   # 步骤1 需要；其余步骤仅用标准库

# 默认 PODCAST=feihua
python pipeline/1_fetch_episodes.py
python pipeline/2_submit_transcribe.py
python pipeline/3_fetch_calibrated.py
python pipeline/4_normalize_names.py --apply
# 步骤5 在 Claude Code 里用 Workflow 工具跑（见 docs/pipeline.md）
python pipeline/6_aggregate.py
```

## 增量更新（节目有新集时）

每步都**断点续跑**：已完成的单集自动跳过。直接重跑 1→6 即可，只处理新增集。

## 当前数据（feihua）

234 集全部完成；935 条推荐（实地 412 / 好物 263 / 影视剧 260）。
详见 `data/feihua/recommendations_all.md`。

## 后续规划

- `web/` 静态网页：推荐清单的查询 / 过滤（按类别、主播、推荐-避雷）。
- 进阶：结合地图对"实地推荐"做可视化。

详细流程、数据契约与已知坑见 [docs/pipeline.md](docs/pipeline.md)。
