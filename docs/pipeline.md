# 流程详解 / 数据契约 / 已知坑

6 步流水线，每步读上一步产物、写下一步输入。所有步骤**断点续跑**。

```
1 fetch_episodes ─ episodes.json
2 submit_transcribe ─ view_urls.{json,txt}     （提交转录，收集 view token）
3 fetch_calibrated ─ transcripts/{vol}_{title}.txt
4 normalize_names ─ 就地修订 transcripts
5 extract.workflow ─ extracted/{vol}.json       （Claude Workflow，Sonnet）
6 aggregate ─ recommendations_all.{json,md}
```

---

## 步骤1 fetch_episodes — 小宇宙节目单

- API：`/v1/search/create`（按名搜 pid）、`/v1/episode/list`（`loadMoreKey` 分页）、`/app_auth_tokens.refresh`。
- **Android 客户端配方（关键）**：UA `Xiaoyuzhou/2.102.2(android 36)`、`Content-Type: application/json;charset=utf-8`。
  刷新 token 时**只带** `x-jike-device-id` + `x-jike-refresh-token`、body `{}`、**不带** access-token；新 token 在响应 **body** 里。
- **refresh token 一次性轮换**：每次刷新使旧的失效，新 token 持久化到 `data/<key>/episodes/.token_state.json`。
  ⚠ 不要和别的在用服务共用同一 refresh token，会互相顶掉。
- pid 优先取 `config.xyz_pid`，否则按 `config.name` 搜索。

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

## 步骤6 aggregate — 校验 + 反查 + 聚合

- 合法性/完整性校验：列缺失/非法集；`--list-bad` 吐逗号分隔集号，直接喂回 workflow 的 `vols`。
- **quote 反查**：每条 quote 必须在对应转录稿逐字命中（含去空白宽松匹配），否则标 `quote_unverified=true`。
  经验：约 **23%** 是 agent 复述/精简而非逐字摘录，内容多属实，仅作 ⚠ 存疑标注、不删。
- 产物：
  - `recommendations_all.json`：`{podcast, stats, items[]}` 扁平总表（每条含 vol/类别/主播/verdict/quote_unverified + 原始 item）。
  - `recommendations_all.md`：可读总清单，按 类别 → verdict 分组。

---

## 数据契约速查

| 文件 | 生产者 | 关键字段 |
|---|---|---|
| `episodes/episodes.json` | 步骤1 | `eid, title, pubDate, episode_url, audio_url` |
| `episodes/view_urls.json` | 步骤2 | `view_url, view_token, title, pubDate` |
| `transcripts/{vol}_{t}.txt` | 步骤3 | front-matter + 说话人标签正文 |
| `extracted/{vol}.json` | 步骤5 | `episode, place[], product[], media[]` |
| `recommendations_all.json` | 步骤6 | `stats, items[]`（web 查询/可视化的数据源） |

## 新增一档播客

1. 写 `config/<key>.json`（key、name、xyz_pid、hosts、name_normalization…）。
2. `.env` 里 `PODCAST=<key>`（或每条命令前临时 `PODCAST=<key>`）。
3. 跑 1→6；步骤5 的 Workflow args 改成对应 baseDir/hosts/total。
