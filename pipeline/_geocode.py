# -*- coding: utf-8 -*-
"""步骤7 的纯函数：Nominatim 响应解析 + 断点续跑编排。

不触网、不读盘。真正的 HTTP（含 User-Agent、≤1req/s、429/5xx 退避）在
7_geocode.py 的 fetch_fn 里，通过依赖注入传进来，便于单测。
"""


def parse_nominatim(payload):
    """Nominatim 搜索响应（dict 列表）→ {lat,lng,display_name,status} 或 None。

    取首条；lat/lon 是字符串需转 float；缺字段/非法数值 → None。
    """
    if not payload:
        return None
    top = payload[0]
    try:
        return {
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "display_name": top.get("display_name", ""),
            "status": "ok",
        }
    except (KeyError, ValueError, TypeError):
        return None


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
