# 流程详解 / 数据契约 / 已知坑

8 步流水线，每步读上一步产物、写下一步输入。所有步骤**断点续跑**。
纯函数逻辑抽到 `_aggregate.py` / `_geocode.py` / `_proofread.py`（与 `_common.py` 同为可导入模块），
由 `tests/` 单测；`6_/7_/8_` 为薄壳。

```
1 fetch_episodes ─ episodes.json                （含 pubDate + description）
2 submit_transcribe ─ view_urls.{json,txt}     （提交转录，收集 view token）
3 fetch_calibrated ─ transcripts/{vol}_{title}.txt
4 normalize_names ─ 就地修订 transcripts
5 extract.workflow ─ extracted/{vol}.json       （Claude Workflow，Sonnet）
6 aggregate ─ recommendations_all.{json,md}     （+ id / pub_date / episodes / 品类归一 / city 规范化）
7 geocode ─ geo.json                            （city_key → 经纬度，Nominatim）
8 proofread ─ 校对 extracted 名字 + corrections_review.json （Claude Workflow，Sonnet；对照 description 纠 ASR 听岔）
→ web/ 纯静态可视化站（Alpine + ECharts，零 build）

注：步骤8 校对后需重跑 6→7 重生成前端数据。日期/描述来自步骤1 的 episodes.json。
```

---

## 步骤1 fetch_episodes — 小宇宙节目单

- API：`/v1/search/create`（按名搜 pid）、`/v1/episode/list`（`loadMoreKey` 分页）、`/app_auth_tokens.refresh`。
- **Android 客户端配方（关键）**：UA `Xiaoyuzhou/2.102.2(android 36)`、`Content-Type: application/json;charset=utf-8`。
  刷新 token 时**只带** `x-jike-device-id` + `x-jike-refresh-token`、body `{}`、**不带** access-token；新 token 在响应 **body** 里。
- **refresh token 一次性轮换**：每次刷新使旧的失效，新 token 持久化到 `data/<key>/episodes/.token_state.json`。
  ⚠ 不要和别的在用服务共用同一 refresh token，会互相顶掉。
- pid 优先取 `config.xyz_pid`，否则按 `config.name` 搜索。
- `slim()` 保留每集 `pubDate`（发布日期）与 `description`（作者手写简介）：前者给前端做日期筛选/排序、单集 banner；后者既上站做单集背景，也是步骤8 校对 ASR 名字的干净对照源。

## 步骤2 submit_transcribe — 提交转录

- 直接提交小宇宙原始链接（`episode_url`），由 VideoTranscriptAPI 自行下载，本地不下音频。
- **API 契约坑**：`POST /api/transcribe` 返回 **HTTP 200**，业务码在 **body.code**（200/202=受理，503=队列满）。
  别用 HTTP 状态码判断成功，否则会把同一集重复提交。
- **必须控速**：转录后端（FunASR 分说话人）是低并发/串行的，突发提交会触发 300s 接收超时雪崩。
  脚本用有界并发（默认 `CONCURRENCY=2`），轮询到终态再补位。
- 产物 `view_urls.json`：`[{view_url, view_token, title, pubDate, ...}]`，按 pubDate 升序。

## 步骤3 fetch_calibrated — 下载校对稿

- 取 `{VIEW_API_BASE}/view/{token}?raw=calibrated` 纯文本（公开路由，无需鉴权）。
- 命名 `{vol:03d}_{clean_title}.txt`：vol 取自标题里的 `VOL.NNN`，无则回退为序号 → 文件名可直接排序。
- 文件头部是 front-matter（含 `Title`/`Source`），正文是带说话人标签的口语对话。

## 步骤4 normalize_names — 主播人名归一

- ASR 会把主播名写成各种同音误写（肥姐/菲姐/飞姐…→肥杰；惠姐/惠子年…→惠子）。
- 规则来自 `config.<key>.json`：
  - `name_normalization`：`{规范名: [变体…]}`，正文+标签全局替换（**顺序敏感**，靠前先替）。
  - `label_normalization`：`{"昵称：": "规范名："}`，**只**替换说话人标签处（带冒号），不动正文口语昵称。
- 先 dry-run 看统计，`--apply` 才写盘；跑后报告每个规范名的覆盖文件数。
- feihua 现状：肥杰 234/234、惠子 234/234。留作人工定夺的：方言歧义「会子」、口播昵称「惠惠」（正文中）。

## 步骤5 extract.workflow.js — 结构化提取

- **由 Claude Code 的 Workflow 工具运行**（不是独立 python）。在 Claude Code 中：

  ```
  Workflow({
    scriptPath: ".../pipeline/5_extract.workflow.js",
    args: { baseDir: ".../data/feihua", hosts: ["肥杰","惠子"], total: 234 }
  })
  ```

- 每集一个 **Sonnet** agent：自检跳过(已存在且合法的 json) → `ls` 找稿 → Read → 按 schema 提取 → Write `extracted/{vol}.json` → `python3 json.load` 自校验。
- 提取 schema：`episode` + 三类数组 `place/product/media`，字段见脚本内提示词。
  - `recommender ∈ {主播…, "共同"}`，`verdict ∈ {重点推荐,推荐,一般,避雷}`（含**避雷**）。
  - 每条带 `quote`（原文逐字片段，防幻觉锚点）与 `name_corrected`（是否纠了专名 ASR 错字）。
- **JSON 合法性坑**：agent 手写 JSON，字符串里裸 ASCII 双引号会撑破。提示词强制内部引号用「」+ 写后自校验。
- 断点续跑：重跑同 args 会跳过已完成集；失败/缺失集可用 `args.vols=[…]` 定向回炉。

## 步骤6 aggregate — 校验 + 反查 + 聚合 + 前端契约

- 合法性/完整性校验：列缺失/非法集；`--list-bad` 吐逗号分隔集号，直接喂回 workflow 的 `vols`。
- **quote 反查**：每条 quote 必须在对应转录稿逐字命中（含去空白宽松匹配），否则标 `quote_unverified=true`。
  经验：约 **23%** 是 agent 复述/精简而非逐字摘录，内容多属实，仅作 ⚠ 存疑标注、不删。
- **前端契约派生**（纯函数在 `_aggregate.py`，单测覆盖）：
  - `id = <vol>-<type>-<idx>`（idx=该集该类别数组内位置）：深链用，ASCII、与名称解耦，改名/校正不坏链。
  - **品类归一**：product 的 `item.category` 走 `config.category_normalization`（护肤→护肤品…）；
    media 的 `item.category` 全空 → 用 `item.type` 兜底（可经 `media_type_map` 再归一）。**只动 `item.category`，不动外层 type**。
  - **city 规范化** → 每条 place 写 `city_key`/`display_city`。脏值处理顺序：`config.city_canonical.overrides` 优先 →
    去括号内容 → 按 `·//、` 取首段 → 剥省/国前缀（江苏南通→南通；直辖市除外防误切）。无法判定→`null`（前端归"未定位"）。
    实测 85 个原始 city → **55 个规范城市**，7 条无定位。
- **日期注入**：按 `episode.eid` join `episodes/episodes.json`，给每条推荐写 `pub_date`（`pub_date_of` 把 ISO 截到 `YYYY-MM-DD`）。
- **单集元数据**：`build_episodes` 汇出 `episodes` 数组（vol/title/pub_date/description/ep_url，按 vol 升序），前端单集 banner + 时间线用；描述不内联进 935 条 item，避免冗余。
- 产物：
  - `recommendations_all.json`：`{podcast, stats, episodes[], items[]}` 扁平总表。每条 item 含 `id/vol/pub_date/category/recommender/verdict/name/city_key/display_city/quote_unverified + 原始 item`。
    `stats` 增 `place_unlocated`、`distinct_cities`。
  - `recommendations_all.md`：可读总清单，按 类别 → verdict 分组。

## 步骤7 geocode — 城市级地理编码

- 只 geocode 去重后的 **city_key**（约 55 个），**不碰 412 个店名**（地图只到城市级，店名定位甩给高德跳转链接）。
- geocoder = **Nominatim**（开源、无 key）。纯逻辑在 `_geocode.py`（`parse_nominatim` + `geocode_cities`，fetch 注入便于单测）。
- **使用政策**：单线程、≤1 req/s、真 `User-Agent`、429/5xx 退避；命中 `geo.json` 跳过（断点续跑）；失败/无结果**不写缓存**→ 重跑自动重试。
- **误命中坑**：裸城市名 Nominatim 会模糊匹配同名国外地点（云南→新加坡、霞浦→日本；cn-优先回退又把东京匹配到衢州东京镇）。
  解法：`config.geocode_overseas` 显式名单 → 海外城市走全球查询，其余强制 `countrycodes=cn`。
- 产物 `geo.json`：`{city_key: {lat,lng,display_name,status}}`，与 `recommendations_all.json` 解耦，web 端按 `display_city` join。

## 步骤8 proofread — 用描述校对 ASR 听岔的专名

- **动机**：ASR 常把店名/物品/作品名听岔（微煌→威皇、东北林丹→灵丹、都是他的错→她的错）。每集作者手写 `description` 是干净文本，配合该条 `quote` 上下文，能让 LLM 判断哪个名字错了并给正名。
- **纯函数在 `_proofread.py`（单测覆盖）**：`episode_items`/`build_episode_input`（组装单集输入，id 与聚合层一致）、`parse_corrections`（规整校验，丢弃空名/无变化/非数置信）、`partition_corrections`（按阈值分流）、`apply_corrections`（就地改名 + 留 `name_original`/`name_corrected`，名字漂移即跳过防误伤）。
- **两端 + 中间 workflow**：
  - `8_proofread.py --build-inputs` → 每集 `proofread/{vol}.json`（描述 + 条目，gitignore）。
  - `8_proofread.workflow.js`（Claude Workflow，**每集一个 Sonnet agent**，pipeline 并发）：读输入、对照描述纠错、schema 输出 `[{id,old_name,new_name,confidence,evidence}]`。**保守策略**：拿不准不改、只改听岔的字不扩写、地名/城市不校对，护住「对照原文核验过」的招牌。
  - `8_proofread.py --apply corrections_raw.json` → 按阈值（默认 **0.85**）分流：高置信就地改 `extracted/*.json`，低置信进 `corrections_review.json`（人工过目）；改动留档 `corrections_applied.json`。
- **跑完重跑 6→7** 重生成前端数据。feihua 首跑：234 集提出 28 条，自动应用 22 / 待审 6。
- **置信分级**：描述有直接证据→0.85~0.98（自动）；仅 quote+常识→0.5~0.8（待审）。个别描述本身有笔误（如《哪吒之魔童脑海》实为《闹海》）按官方名人工校正。

## web/ — 纯静态可视化站

- **零后端、零 Docker**：geocoding 在构建期跑；线上是静态文件，丢 GitHub Pages / nginx 静态目录即可。
- **零 build**：`index.html` + `app.js` + Alpine/ECharts(**本地 vendor**，`web/vendor/`，不依赖 CDN → 国内网络可用、运行时零第三方)。⚠ `app.js` 必须在 Alpine `<script>` 之前，否则 Alpine 自启动微任务先于 `window.feihua` 定义 → "feihua is not defined"。图表库缺失时降级:列表/过滤仍可用。
- **零 server ≠ 能 file:// 直开**：ES module + fetch 被 CORS 拦，本地开发 `python -m http.server`。
- **运行时零第三方**：底图为随站打包的 `web/china.geojson`（阿里 DataV，**审图号 GS(2019)1719**，含南海诸岛/九段线、台湾、藏南/阿克赛钦按 GB 标准）。⚠ 别换非合规 GeoJSON。
- 五视图：地图（城市气泡 + 海外单列 + 无定位计数）/ 列表（过滤+搜索+深链+店名跳高德）/ 口味画像 / 红黑榜 / 关于（创作历程）。
- **筛选维度**：搜索 / 类型 / 主播 / 单集 / **年份** / 省份 / 城市 / 推荐倾向；排序支持集数与**发布日期**新旧。
- **日期与描述**：卡片显示发布日期；按单集筛选时顶部 banner 展示该集发布日期 + 作者手写简介（数据来自 `recommendations_all.json` 的 `episodes` 数组）；口味画像页有「推荐条数·按月分布」时间线。
- 国内/海外判定用 geocoder 的国家标注（`display_name` 含「中国」），不用经纬度盒子（曼谷在盒内但属泰国）。

---

## 数据契约速查

| 文件 | 生产者 | 关键字段 |
|---|---|---|
| `episodes/episodes.json` | 步骤1 | `eid, title, pubDate, description, episode_url, audio_url` |
| `episodes/view_urls.json` | 步骤2 | `view_url, view_token, title, pubDate` |
| `transcripts/{vol}_{t}.txt` | 步骤3 | front-matter + 说话人标签正文 |
| `extracted/{vol}.json` | 步骤5 | `episode, place[], product[], media[]`（步骤8 就地改名 + `name_original`） |
| `recommendations_all.json` | 步骤6 | `stats, episodes[], items[]`（item 含 id/pub_date/city_key/display_city；web 数据源） |
| `geo.json` | 步骤7 | `{city_key: {lat,lng,display_name}}`（web 按 display_city join） |
| `corrections_review.json` | 步骤8 | 低置信待审修正 `[{id,old_name,new_name,confidence,evidence}]` |
| `corrections_applied.json` | 步骤8 | 已自动应用的修正（留档备查） |

## 测试

`python -m pytest`（纯函数：id、品类归一、city 规范化、pub_date/episodes 派生、Nominatim 解析/断点续跑、校对解析/分流/就地应用 + 6_aggregate 输出 golden 回归）。当前 63 例。web 为展示逻辑，走手动/浏览器 QA。

## 新增一档播客

1. 写 `config/<key>.json`（key、name、xyz_pid、hosts、name_normalization、category_normalization、city_canonical、geocode_overseas…）。
2. `.env` 里 `PODCAST=<key>`（或每条命令前临时 `PODCAST=<key>`）。
3. 跑 1→8（5 与 8 是 Claude Workflow）；步骤5 的 Workflow args 改成对应 baseDir/hosts/total。web 端目前对 feihua 硬编码数据路径，多播客切换见 NOT-in-scope。
