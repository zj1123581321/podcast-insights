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
├── pipeline/                # 固化的 7 步流程（纯函数抽到 _*.py，由 tests/ 单测）
│   ├── _common.py           # 共享：配置/路径/.env
│   ├── _aggregate.py        # 步骤6 纯函数：id/品类归一/city 规范化
│   ├── _geocode.py          # 步骤7 纯函数：Nominatim 解析/断点续跑编排
│   ├── 1_fetch_episodes.py      # 小宇宙 API 拉全部单集
│   ├── 2_submit_transcribe.py   # 提交 VideoTranscriptAPI 分说话人转录
│   ├── 3_fetch_calibrated.py    # 下载校对稿 TXT
│   ├── 4_normalize_names.py     # 主播人名 ASR 误写归一
│   ├── 5_extract.workflow.js    # 结构化提取（Claude Code Workflow，Sonnet）
│   ├── 6_aggregate.py           # 校验 + quote 反查 + 聚合 + 前端契约(id/归一/city)
│   └── 7_geocode.py             # city_key → 经纬度（Nominatim，无 key）
├── tests/                   # pytest：纯函数 + 6_aggregate 输出 golden 回归
├── data/<key>/
│   ├── episodes/            # episodes.json、view_urls.{json,txt}
│   ├── transcripts/         # {vol:03d}_{title}.txt（gitignore，可再生）
│   ├── extracted/           # {vol:03d}.json（结构化推荐，入库）
│   ├── recommendations_all.{json,md}   # 聚合产物（含 id/city_key/display_city）
│   └── geo.json             # city_key → 经纬度（入库，供 web 用）
├── docs/pipeline.md         # 流程详解 + 各步契约/坑
└── web/                     # 纯静态可视化站（Alpine + ECharts，零 build）
    ├── index.html / app.js / styles.css
    └── china.geojson        # 审图号 GS(2019)1719 合规底图
```

## 快速开始

```bash
cp .env.example .env        # 填写 token
python -m pip install requests pytest   # 步骤1 需要 requests；测试需要 pytest；其余仅标准库

# 默认 PODCAST=feihua
python pipeline/1_fetch_episodes.py
python pipeline/2_submit_transcribe.py
python pipeline/3_fetch_calibrated.py
python pipeline/4_normalize_names.py --apply
# 步骤5 在 Claude Code 里用 Workflow 工具跑（见 docs/pipeline.md）
python pipeline/6_aggregate.py            # 聚合 + 派生 id/归一/city_key
python pipeline/7_geocode.py              # 城市级地理编码（Nominatim，无 key，~1/s）
python -m pytest                          # 纯函数 + 聚合输出回归

# 本地预览可视化站（不能 file:// 直开，需经 http 服务）
python -m http.server 8099                # 然后访问 http://localhost:8099/web/
```

## 增量更新（节目有新集时）

每步都**断点续跑**：已完成的单集自动跳过。直接重跑 1→6 即可，只处理新增集。

## 当前数据（feihua）

234 集全部完成；935 条推荐（实地 412 / 好物 263 / 影视剧 260）。
实地推荐覆盖 55 个规范城市（85 个原始 city 值经归一），7 条无定位。
详见 `data/feihua/recommendations_all.md`。

## 可视化站（web/）

纯静态、零后端、零 Docker：

- **地图**：实地推荐按城市落点（点击进城市清单），底图为审图号 GS(2019)1719 合规版（含南海诸岛/九段线、台湾）。
- **列表**：按类别 / 城市 / 主播 / verdict 过滤 + 全文搜，单条可生成深链；店名点击跳高德搜索。
- **口味画像**：肥杰 / 惠子 / 共同 的类型分布 + 推荐倾向占比。
- **红黑榜**：避雷 + 一般，"别人替你踩过的坑"。

部署 = 把仓库（或 `web/` + `data/feihua/*.json`）丢到任意静态托管。本地预览见上方快速开始。

## 后续规划

- 按发布日期的时间线（阻塞于 `pubDate` 全空，需先回填）。
- 多播客的 web 端切换（当前 feihua 数据路径硬编码）。

详细流程、数据契约与已知坑见 [docs/pipeline.md](docs/pipeline.md)。
