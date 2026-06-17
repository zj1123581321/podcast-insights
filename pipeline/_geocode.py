# -*- coding: utf-8 -*-
"""步骤7 的纯函数：Nominatim 响应解析 + 断点续跑编排。

不触网、不读盘。真正的 HTTP（含 User-Agent、≤1req/s、429/5xx 退避）在
7_geocode.py 的 fetch_fn 里，通过依赖注入传进来，便于单测。
"""


def province_of(display_name: str) -> str:
    """从 Nominatim display_name 提取省级标签（国内）或国家（海外），用于前端按省过滤。

    display_name 形如「大理白族自治州, 云南省, 中国」「上海市, 中国」「东京都, 日本」。
    国内：取以 省/自治区/特别行政区 结尾的段；直辖市/SAR 无省段则取首段。
    海外：取末段国家名。`;` 分隔的繁简变体只留第一个。
    """
    if not display_name:
        return ""
    parts = [p.strip() for p in display_name.split(",") if p.strip()]
    if not parts:
        return ""
    last = parts[-1]
    domestic = ("中国" in last) or ("中國" in last)
    if domestic:
        for p in parts:
            if p.endswith(("省", "自治区", "自治區", "特别行政区", "特別行政區")):
                return p.split(";")[0]
        return parts[0].split(";")[0]   # 直辖市 / 特别行政区无省段
    return last.split(";")[0]            # 海外 → 国家


def parse_nominatim(payload):
    """Nominatim 搜索响应（dict 列表）→ {lat,lng,display_name,province,status} 或 None。

    取首条；lat/lon 是字符串需转 float；缺字段/非法数值 → None。
    """
    if not payload:
        return None
    top = payload[0]
    try:
        dn = top.get("display_name", "")
        return {
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "display_name": dn,
            "province": province_of(dn),
            "status": "ok",
        }
    except (KeyError, ValueError, TypeError):
        return None


def apply_overrides(cache: dict, overrides: dict) -> int:
    """把人工坐标覆盖写进 cache（key=city_key），用于 Nominatim 误命中的城市。

    overrides[city] = {lat,lng,display_name,[province]}。province 缺省则从
    display_name 派生。返回写入条数。覆盖是权威值，每次运行都重写。
    """
    n = 0
    for city, co in (overrides or {}).items():
        if "lat" not in co or "lng" not in co:
            continue
        dn = co.get("display_name", city)
        cache[city] = {
            "lat": float(co["lat"]),
            "lng": float(co["lng"]),
            "display_name": dn,
            "province": co.get("province") or province_of(dn),
            "status": "override",
        }
        n += 1
    return n


def geocode_cities(cities, cache: dict, fetch_fn, parse_fn=parse_nominatim) -> dict:
    """对 cities 逐个地理编码，结果就地写入 cache（key=城市名）。

    断点续跑：已在 cache 的城市直接跳过（不调用 fetch_fn）。
    失败语义（无结果 / fetch 抛错 / 解析失败）一律**不写缓存**，
    这样下次重跑会自动重试，不会把空洞固化下来。

    返回 {"added","failed","skipped"} 计数。
    """
    added = failed = skipped = 0
    for city in cities:
        if city in cache:
            skipped += 1
            continue
        try:
            payload = fetch_fn(city)
        except Exception:
            failed += 1
            continue
        parsed = parse_fn(payload)
        if parsed is None:
            failed += 1
            continue
        cache[city] = parsed
        added += 1
    return {"added": added, "failed": failed, "skipped": skipped}
