/* 《肥话连篇》推荐可视化 — 纯静态、零 build。
 * Alpine 管外壳/过滤/路由；ECharts 画地图与统计图。运行时零第三方调用
 * （底图为随站打包的合规 GeoJSON）。数据由 pipeline 离线再生。 */

const DATA = "../data/feihua/recommendations_all.json";
const GEO = "../data/feihua/geo.json";
const CHINA_GEOJSON = "./china.geojson";

const VERDICT = [
  { k: "重点推荐", color: "#1a7f37" },
  { k: "推荐", color: "#4caf50" },
  { k: "一般", color: "#9e9e9e" },
  { k: "避雷", color: "#e53935" },
];
const VCOLOR = Object.fromEntries(VERDICT.map((v) => [v.k, v.color]));

function feihua() {
  return {
    loading: true,
    loadError: "",
    items: [],
    epMeta: [],
    geo: {},
    stats: {},
    tab: "map",
    tabs: [
      { k: "map", label: "地图" },
      { k: "list", label: "列表" },
      { k: "taste", label: "口味画像" },
      { k: "blacklist", label: "红黑榜" },
      { k: "about", label: "关于" },
    ],
    verdicts: VERDICT,
    filters: { q: "", category: "", recommender: "", verdicts: [], vol: "", year: "", province: "", city: "", sort: "" },
    route: { item: "" },
    searchOpen: "",
    charts: { map: null, taste: null, tasteVerdict: null, tasteTimeline: null },

    async init() {
      try {
        const [data, geo, china] = await Promise.all([
          fetch(DATA).then((r) => r.json()),
          fetch(GEO).then((r) => r.json()),
          fetch(CHINA_GEOJSON).then((r) => r.json()),
        ]);
        this.items = data.items || [];
        this.epMeta = data.episodes || [];
        this.stats = data.stats || {};
        this.geo = geo || {};
        // 图表库可选：缺失也不应整站白屏（列表/过滤照常用）。
        if (typeof echarts !== "undefined") echarts.registerMap("china", china);
        else this.loadError = "图表库 echarts 未加载，地图/统计图不可用，列表仍可用。";
        this.loading = false;
        this.applyHash();
        window.addEventListener("hashchange", () => this.applyHash());
        // tab 切换后 ECharts 实例需 resize / 懒初始化（隐藏时尺寸为 0）
        this.$watch("tab", () => this.$nextTick(() => this.renderActive()));
        this.$watch("filters", () => this.$nextTick(() => this.renderActive()), { deep: true });
        // 选了省份后，若当前城市不属于该省，清掉城市，避免矛盾筛选。
        this.$watch("filters.province", (p) => {
          if (p && this.filters.city && this.cityProvince(this.filters.city) !== p) this.filters.city = "";
        });
        this.$nextTick(() => this.renderActive());
      } catch (e) {
        this.loading = false;
        this.loadError =
          "数据加载失败（需经 http 服务访问，勿用 file:// 直接打开；本地跑 python -m http.server）。" + e;
      }
    },

    // ---- 派生 ----
    get headline() {
      const c = this.stats.counts || {};
      return `${this.stats.total_items || 0} 条 · 实地 ${c.place || 0}/好物 ${c.product || 0}/影视 ${c.media || 0}`;
    },
    get recommenders() {
      return [...new Set(this.items.map((i) => i.recommender).filter(Boolean))];
    },
    get episodes() {
      const m = new Map();
      for (const it of this.items) if (!m.has(it.vol)) m.set(it.vol, it.ep_title || "");
      return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([vol, title]) => ({ vol, title }));
    },
    // 年份选项（按发布日期，新→旧）。
    get years() {
      const s = new Set();
      for (const it of this.items) {
        const y = (it.pub_date || "").slice(0, 4);
        if (y) s.add(y);
      }
      return [...s].sort((a, b) => b.localeCompare(a));
    },
    // vol -> 单集元数据（标题/日期/描述/链接），单集 banner 用。
    get epByVol() {
      const m = {};
      for (const e of this.epMeta) m[e.vol] = e;
      return m;
    },
    // 当前若按单集筛选，返回该集元数据（顶部展示发布日期+描述背景）。
    get activeEpisode() {
      return this.filters.vol ? this.epByVol[Number(this.filters.vol)] || null : null;
    },
    get provinces() {
      const s = new Set();
      for (const it of this.items) {
        const p = this.cityProvince(it.display_city);
        if (p) s.add(p);
      }
      return [...s].sort();
    },
    get cities() {
      const counts = {};
      for (const it of this.items) {
        const c = it.display_city;
        if (!c) continue;
        if (this.filters.province && this.cityProvince(c) !== this.filters.province) continue;
        counts[c] = (counts[c] || 0) + 1;
      }
      return Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
    },
    cityProvince(c) {
      return c && this.geo[c] ? this.geo[c].province || "" : "";
    },
    get dirty() {
      const f = this.filters;
      return !!(f.q || f.category || f.recommender || f.verdicts.length || f.vol || f.year || f.province || f.city || f.sort);
    },
    // 当前生效的筛选，渲染成一行可逐个移除的 chip（让用户随时看清状态、随时回退）。
    get activeFilters() {
      const f = this.filters, out = [];
      if (f.category) out.push({ k: "category", label: "类型：" + this.catLabel(f.category) });
      if (f.recommender) out.push({ k: "recommender", label: "主播：" + f.recommender });
      if (f.vol) out.push({ k: "vol", label: "单集：VOL." + String(f.vol).padStart(3, "0") });
      if (f.year) out.push({ k: "year", label: "年份：" + f.year });
      if (f.province) out.push({ k: "province", label: "省份：" + f.province });
      if (f.city) out.push({ k: "city", label: "城市：" + f.city });
      for (const v of f.verdicts) out.push({ k: "verdict:" + v, label: v });
      if (f.q) out.push({ k: "q", label: "搜索：" + f.q });
      return out;
    },
    clearFilter(k) {
      const f = this.filters;
      if (k === "q") f.q = "";
      else if (k === "category") f.category = "";
      else if (k === "recommender") f.recommender = "";
      else if (k === "vol") f.vol = "";
      else if (k === "year") f.year = "";
      else if (k === "province") { f.province = ""; f.city = ""; }
      else if (k === "city") f.city = "";
      else if (k.startsWith("verdict:")) this.toggleVerdict(k.slice(8));
    },
    get activeCity() {
      return this.filters.city || "";
    },
    get filtered() {
      const f = this.filters;
      const q = f.q.trim();
      const rows = this.items.filter((it) => {
        if (f.category && it.category !== f.category) return false;
        if (f.recommender && it.recommender !== f.recommender) return false;
        if (f.verdicts.length && !f.verdicts.includes(it.verdict)) return false;
        if (f.vol && it.vol !== Number(f.vol)) return false;
        if (f.year && (it.pub_date || "").slice(0, 4) !== f.year) return false;
        if (f.city && it.display_city !== f.city) return false;
        if (f.province && this.cityProvince(it.display_city) !== f.province) return false;
        if (q) {
          const hay = `${it.name} ${this.reasonOf(it)} ${it.item.quote || ""} ${it.item.category || ""}`;
          if (!hay.includes(q)) return false;
        }
        return true;
      });
      if (f.sort === "vol-desc") rows.sort((a, b) => b.vol - a.vol);
      else if (f.sort === "vol-asc") rows.sort((a, b) => a.vol - b.vol);
      else if (f.sort === "date-desc") rows.sort((a, b) => (b.pub_date || "").localeCompare(a.pub_date || ""));
      else if (f.sort === "date-asc") rows.sort((a, b) => (a.pub_date || "").localeCompare(b.pub_date || ""));
      return rows;
    },
    get blacklist() {
      return this.items
        .filter((it) => it.verdict === "避雷" || it.verdict === "一般")
        .sort((a, b) => (a.verdict === b.verdict ? a.vol - b.vol : a.verdict === "避雷" ? -1 : 1));
    },
    get overseas() {
      const set = new Set();
      for (const it of this.items) {
        const ck = it.display_city;
        if (!ck || !this.geo[ck]) continue;
        if (!this.inChina(this.geo[ck])) set.add(ck);
      }
      return [...set].sort();
    },
    // 当前筛选下能在地图（中国底图）上落点的城市数；为 0 时地图给出解释而非空白。
    get mapCityCount() {
      const s = new Set();
      for (const it of this.filtered) {
        const ck = it.display_city;
        if (ck && this.geo[ck] && this.inChina(this.geo[ck])) s.add(ck);
      }
      return s.size;
    },

    // ---- 工具 ----
    inChina(g) {
      // 用 geocoder 返回的国家标注判定（比经纬度盒子可靠：曼谷在盒内但属泰国）。
      const dn = g && g.display_name ? g.display_name : "";
      return dn.includes("中国") || dn.includes("中國");
    },
    verdictColor(v) {
      return VCOLOR[v] || "#9e9e9e";
    },
    catLabel(c) {
      return { place: "实地", product: "好物", media: "影视剧" }[c] || c;
    },
    reasonOf(it) {
      const m = it.item || {};
      return m.reason || m.why_good || m.why_recommended || m.synopsis || "";
    },
    // 按品类给不同搜索源：实地→地图/探店，好物→电商，影视剧→影评库。
    // 全是 https 网页链接（桌面/手机/微信都能开）；点评 web 搜索有登录墙，
    // 故点评走 scheme 唤端（best-effort，仅手机+装了App+非微信内置浏览器有效）。
    searchSources(it) {
      const enc = encodeURIComponent;
      const name = it.name || "";
      const city = it.display_city || "";
      const xhs = (kw) => "https://www.xiaohongshu.com/search_result/?keyword=" + enc(kw);
      if (it.category === "product") {
        return [
          { label: "淘宝", url: "https://s.m.taobao.com/h5?q=" + enc(name) },
          { label: "京东", url: "https://so.m.jd.com/ware/search.action?keyword=" + enc(name) },
          { label: "小红书", url: xhs(name) },
        ];
      }
      if (it.category === "media") {
        return [
          { label: "豆瓣", url: "https://m.douban.com/search/?query=" + enc(name) },
          { label: "小红书", url: xhs(name) },
        ];
      }
      // place（默认）
      const q = `${city} ${name}`.trim();
      const amap = "https://www.amap.com/search?query=" + enc(q);
      return [
        { label: "高德地图", url: amap },
        { label: "小红书", url: xhs(`${name} ${city}`.trim()) },
        { label: "大众点评App", scheme: "dianping://searchshoplist?keyword=" + enc(name), fallback: amap },
      ];
    },
    toggleSearch(id) {
      this.searchOpen = this.searchOpen === id ? "" : id;
    },
    // 唤起本地 App：Android 用 intent:// 带 fallback（系统自动降级）；
    // iOS/其他尝试 scheme，~1.4s 仍停留在页面则退回网页兜底。
    openApp(scheme, fallback) {
      const ua = navigator.userAgent || "";
      if (/Android/i.test(ua)) {
        const tail = scheme.replace(/^[a-z]+:\/\//i, "");
        window.location.href =
          "intent://" + tail +
          "#Intent;scheme=dianping;package=com.dianping.v1;S.browser_fallback_url=" +
          encodeURIComponent(fallback) + ";end";
        return;
      }
      let left = false;
      const onHide = () => { left = true; };
      document.addEventListener("visibilitychange", onHide);
      window.location.href = scheme;
      setTimeout(() => {
        document.removeEventListener("visibilitychange", onHide);
        if (!left && !document.hidden) window.location.href = fallback;
      }, 1400);
    },
    cityCount(c) {
      return this.items.filter((i) => i.display_city === c).length;
    },

    // ---- 过滤交互 ----
    toggleVerdict(k) {
      const i = this.filters.verdicts.indexOf(k);
      if (i >= 0) this.filters.verdicts.splice(i, 1);
      else this.filters.verdicts.push(k);
    },
    resetFilters() {
      this.filters = { q: "", category: "", recommender: "", verdicts: [], vol: "", year: "", province: "", city: "", sort: "" };
      if (location.hash) location.hash = "#/";
    },

    // ---- 路由（CJK 城市名经 encode；item id 为 ASCII） ----
    setTab(k) {
      this.tab = k;
    },
    applyHash() {
      const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
      const [kind, val] = h.split("/");
      if (kind === "city") {
        this.filters.city = (val || "").normalize("NFC");
        this.route.item = "";
        this.tab = "list";
      } else if (kind === "item") {
        this.route.item = val || "";
        this.tab = "list";
        this.$nextTick(() => {
          const el = document.getElementById("item-" + val);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      } else {
        this.route.item = "";
      }
    },
    goCity(c) {
      location.hash = c ? "#/city/" + encodeURIComponent(c) : "#/";
    },
    goItem(id) {
      location.hash = "#/item/" + id;
    },

    // ---- ECharts ----
    renderActive() {
      if (this.tab === "map") this.renderMap();
      if (this.tab === "taste") this.renderTaste();
      // tab 刚显示时容器宽度可能尚未稳定，下一帧再 resize 一次。
      setTimeout(() => {
        for (const c of Object.values(this.charts)) c && c.resize();
      }, 60);
    },
    ensureChart(key, id) {
      if (typeof echarts === "undefined") return null;
      const el = document.getElementById(id);
      if (!el) return null;
      if (!this.charts[key]) this.charts[key] = echarts.init(el);
      else this.charts[key].resize();
      return this.charts[key];
    },
    renderMap() {
      const chart = this.ensureChart("map", "map");
      if (!chart) return;
      const byCity = {};
      for (const it of this.filtered) {
        const ck = it.display_city;
        if (!ck || !this.geo[ck] || !this.inChina(this.geo[ck])) continue;
        (byCity[ck] ||= []).push(it);
      }
      const data = Object.entries(byCity).map(([city, list]) => {
        const g = this.geo[city];
        const bad = list.filter((x) => x.verdict === "避雷").length;
        return {
          name: city,
          value: [g.lng, g.lat, list.length],
          bad,
          itemStyle: { color: bad ? "#e76f51" : "#2a9d8f" },
        };
      });
      chart.setOption({
        tooltip: {
          trigger: "item",
          formatter: (p) =>
            p.data && p.data.value
              ? `${p.name}<br/>推荐 ${p.data.value[2]} 条${p.data.bad ? `（含避雷 ${p.data.bad}）` : ""}`
              : p.name,
        },
        geo: {
          map: "china",
          roam: true,
          itemStyle: { areaColor: "#eef1f0", borderColor: "#cdd5d2" },
          emphasis: { itemStyle: { areaColor: "#e0e7e4" }, label: { show: false } },
        },
        series: [
          {
            type: "scatter",
            coordinateSystem: "geo",
            symbolSize: (v) => Math.min(48, 10 + Math.sqrt(v[2]) * 6),
            data,
          },
        ],
      }, true);
      chart.off("click");
      chart.on("click", (p) => {
        if (p.data && p.data.name) this.goCity(p.data.name);
      });
    },
    renderTaste() {
      // 推荐人 × 类型 堆叠柱
      const chart = this.ensureChart("taste", "taste");
      if (chart) {
        const recs = this.recommenders;
        const cats = ["place", "product", "media"];
        const series = cats.map((c) => ({
          name: this.catLabel(c),
          type: "bar",
          stack: "x",
          data: recs.map((r) => this.items.filter((i) => i.recommender === r && i.category === c).length),
        }));
        chart.setOption({
          title: { text: "主播口味画像（推荐人 × 类型）", left: "center", top: 8, textStyle: { fontSize: 14 } },
          tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
          legend: { top: 36 },
          grid: { top: 80, left: 48, right: 24, bottom: 30, containLabel: true },
          xAxis: { type: "category", data: recs },
          yAxis: { type: "value" },
          series,
        }, true);
      }
      // 时间线：推荐条数按年月分布（看节目推荐节奏）
      const tl = this.ensureChart("tasteTimeline", "tasteTimeline");
      if (tl) {
        const byMonth = {};
        for (const it of this.items) {
          const ym = (it.pub_date || "").slice(0, 7);
          if (ym) byMonth[ym] = (byMonth[ym] || 0) + 1;
        }
        const months = Object.keys(byMonth).sort();
        tl.setOption({
          title: { text: "推荐条数 · 按月分布", left: "center", textStyle: { fontSize: 14 } },
          tooltip: { trigger: "axis", axisPointer: { type: "line" } },
          grid: { top: 48, left: 40, right: 20, bottom: 60, containLabel: true },
          xAxis: { type: "category", data: months, axisLabel: { rotate: 45, fontSize: 10 } },
          yAxis: { type: "value" },
          series: [{ type: "bar", data: months.map((m) => byMonth[m]), itemStyle: { color: "#2a9d8f" } }],
        }, true);
      }
      // verdict 占比饼
      const pie = this.ensureChart("tasteVerdict", "tasteVerdict");
      if (pie) {
        pie.setOption({
          title: { text: "推荐倾向分布", left: "center", textStyle: { fontSize: 14 } },
          tooltip: { trigger: "item" },
          series: [
            {
              type: "pie",
              radius: ["35%", "65%"],
              data: VERDICT.map((v) => ({
                name: v.k,
                value: this.items.filter((i) => i.verdict === v.k).length,
                itemStyle: { color: v.color },
              })),
            },
          ],
        }, true);
      }
    },
  };
}
window.feihua = feihua;
