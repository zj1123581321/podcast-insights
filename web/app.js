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
    geo: {},
    stats: {},
    tab: "map",
    tabs: [
      { k: "map", label: "地图" },
      { k: "list", label: "列表" },
      { k: "taste", label: "口味画像" },
      { k: "blacklist", label: "红黑榜" },
    ],
    verdicts: VERDICT,
    filters: { q: "", category: "", recommender: "", verdicts: [] },
    route: { city: "", item: "" },
    charts: { map: null, taste: null, tasteVerdict: null },

    async init() {
      try {
        const [data, geo, china] = await Promise.all([
          fetch(DATA).then((r) => r.json()),
          fetch(GEO).then((r) => r.json()),
          fetch(CHINA_GEOJSON).then((r) => r.json()),
        ]);
        this.items = data.items || [];
        this.stats = data.stats || {};
        this.geo = geo || {};
        echarts.registerMap("china", china);
        this.loading = false;
        this.applyHash();
        window.addEventListener("hashchange", () => this.applyHash());
        // tab 切换后 ECharts 实例需 resize / 懒初始化（隐藏时尺寸为 0）
        this.$watch("tab", () => this.$nextTick(() => this.renderActive()));
        this.$watch("filters", () => this.$nextTick(() => this.renderActive()), { deep: true });
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
    get dirty() {
      const f = this.filters;
      return !!(f.q || f.category || f.recommender || f.verdicts.length);
    },
    get activeCity() {
      return this.route.city || "";
    },
    get filtered() {
      const f = this.filters;
      const q = f.q.trim();
      return this.items.filter((it) => {
        if (f.category && it.category !== f.category) return false;
        if (f.recommender && it.recommender !== f.recommender) return false;
        if (f.verdicts.length && !f.verdicts.includes(it.verdict)) return false;
        if (this.route.city && it.display_city !== this.route.city) return false;
        if (q) {
          const hay = `${it.name} ${this.reasonOf(it)} ${it.item.quote || ""} ${it.item.category || ""}`;
          if (!hay.includes(q)) return false;
        }
        return true;
      });
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
    shopUrl(it) {
      const q = `${it.display_city || ""} ${it.name}`.trim();
      return "https://www.amap.com/ssr/search?query=" + encodeURIComponent(q);
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
      this.filters = { q: "", category: "", recommender: "", verdicts: [] };
    },

    // ---- 路由（CJK 城市名经 encode；item id 为 ASCII） ----
    setTab(k) {
      this.tab = k;
    },
    applyHash() {
      const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
      const [kind, val] = h.split("/");
      if (kind === "city") {
        this.route = { city: (val || "").normalize("NFC"), item: "" };
        this.tab = "list";
      } else if (kind === "item") {
        this.route = { city: "", item: val || "" };
        this.tab = "list";
        this.$nextTick(() => {
          const el = document.getElementById("item-" + val);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
        });
      } else {
        this.route = { city: "", item: "" };
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
