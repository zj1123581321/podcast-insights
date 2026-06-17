#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤7：给 place 的规范城市做城市级地理编码（构建期，仅一次性）。

  data/<key>/recommendations_all.json  ->  data/<key>/geo.json   (key=city_key -> {lat,lng,...})

设计：
  - 只 geocode 去重后的 **city_key**（步骤6 已规范化），不碰 412 个店名。
  - geocoder = Nominatim（开源、无 key）。遵守使用政策：单线程、≤1 req/s、
    真 User-Agent、429/5xx 退避并停。结果持久化到 geo.json；**命中缓存跳过**（断点续跑）。
  - 失败/无结果不写缓存 → 下次重跑自动重试，不固化空洞。
  - 纯逻辑在 _geocode.py（已单测）；本文件只负责 HTTP + 落盘。

用法：
  PODCAST=feihua python pipeline/7_geocode.py
  PODCAST=feihua python pipeline/7_geocode.py --limit 10   # 只处理前 N 个未缓存城市（试跑）
"""
import json
import sys
import time
import urllib.parse
import urllib.request

import _common as C
import _geocode as G

CFG = C.load_config()
KEY = CFG["key"]
DD = C.data_dir(KEY)
AGG = DD / "recommendations_all.json"
GEO = DD / "geo.json"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim 政策要求真实可联系的 User-Agent。
UA = "podcast-insights-geocoder/1.0 (https://github.com/zj1123581321/podcast-insights)"
RATE_SECONDS = 1.1          # ≤1 req/s
RETRY_BACKOFF = [5, 15, 30]  # 429/5xx 退避秒数；耗尽则停。


def distinct_city_keys() -> list[str]:
    if not AGG.exists():
        raise SystemExit(f"[geocode] 先跑步骤6生成 {AGG}")
    data = json.loads(AGG.read_text(encoding="utf-8"))
    keys = {r.get("city_key") for r in data.get("items", [])
            if r.get("category") == "place" and r.get("city_key")}
    return sorted(keys)


def load_cache() -> dict:
    if GEO.exists():
        return json.loads(GEO.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    GEO.write_text(json.dumps(cache, ensure_ascii=False, indent=2,
                              sort_keys=True), encoding="utf-8")


def _query(city, extra):
    """单次 Nominatim 查询（含 429/5xx 退避）。返回 payload(list)。"""
    params = {"q": city, "format": "jsonv2", "limit": 1, "accept-language": "zh-CN,en"}
    params.update(extra)
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{NOMINATIM}?{qs}", headers={"User-Agent": UA})
    last_err = None
    for backoff in [0] + RETRY_BACKOFF:
        if backoff:
            time.sleep(backoff)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            time.sleep(RATE_SECONDS)
            return payload
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504):
                continue
            raise
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError(f"geocode failed: {city}")


def make_fetch(overseas):
    """构造 fetch_fn(city) -> Nominatim payload。

    海外城市（config.geocode_overseas）走全球查询；其余城市强制
    countrycodes=cn。裸城市名 Nominatim 会模糊匹配，cn-优先回退法不可靠
    （「东京」在 cn 下会被匹配到衢州东京镇），故用显式名单确定性切分。
    单线程、≤1req/s、429/5xx 退避。
    """
    overseas = set(overseas or [])

    def fetch(city):
        extra = {} if city in overseas else {"countrycodes": "cn"}
        return _query(city, extra)
    return fetch


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    cities = distinct_city_keys()
    cache = load_cache()
    # 人工坐标覆盖（误命中城市）优先写入，使其跳过 Nominatim。
    n_ov = G.apply_overrides(cache, CFG.get("city_coords", {}))
    if n_ov:
        print(f"[geocode] 应用人工坐标覆盖 {n_ov} 城")
    todo = [c for c in cities if c not in cache]
    if limit is not None:
        todo = todo[:limit]
    print(f"[geocode] 规范城市 {len(cities)}，已缓存 {len(cache)}，本次待处理 {len(todo)}")

    stats = G.geocode_cities(todo, cache, make_fetch(CFG.get("geocode_overseas", [])))
    # 回填 province（从已存 display_name 派生，无需重新触网；老缓存也补齐）
    for entry in cache.values():
        if "province" not in entry:
            entry["province"] = G.province_of(entry.get("display_name", ""))
    save_cache(cache)

    missing = [c for c in cities if c not in cache]
    print(f"[geocode] +{stats['added']} 新增 / {stats['failed']} 失败 / {stats['skipped']} 跳过")
    print(f"  -> {GEO}（共 {len(cache)} 城）")
    if missing:
        print(f"[!] {len(missing)} 城未定位（重跑可重试）：{missing}")


if __name__ == "__main__":
    main()
