# -*- coding: utf-8 -*-
"""步骤7 纯函数单测：Nominatim 响应解析 + 断点续跑编排（fetch 注入，不触网）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import _geocode as G  # noqa: E402


# ---- parse_nominatim ----
def test_parse_happy():
    out = G.parse_nominatim([{"lat": "31.23", "lon": "121.47", "display_name": "上海, 中国"}])
    assert out["lat"] == 31.23
    assert out["lng"] == 121.47
    assert out["status"] == "ok"
    assert "上海" in out["display_name"]


def test_parse_empty_list():
    assert G.parse_nominatim([]) is None
    assert G.parse_nominatim(None) is None


def test_parse_missing_or_bad_coords():
    assert G.parse_nominatim([{"display_name": "x"}]) is None
    assert G.parse_nominatim([{"lat": "NaNish", "lon": "1"}]) is None


# ---- geocode_cities：断点续跑 + 失败不写缓存 ----
class _Fetcher:
    """可编排的 fetch_fn：按 city 返回 payload / 抛错，并记录调用次数。"""
    def __init__(self, responses):
        self.responses = responses  # city -> payload | Exception
        self.calls = []

    def __call__(self, city):
        self.calls.append(city)
        r = self.responses.get(city)
        if isinstance(r, Exception):
            raise r
        return r


def test_geocode_happy_writes_cache():
    f = _Fetcher({"上海": [{"lat": "31.2", "lon": "121.4", "display_name": "上海"}]})
    cache = {}
    stats = G.geocode_cities(["上海"], cache, f)
    assert cache["上海"]["lat"] == 31.2
    assert stats["added"] == 1 and stats["failed"] == 0


def test_geocode_no_result_not_cached():
    f = _Fetcher({"火星城": []})
    cache = {}
    stats = G.geocode_cities(["火星城"], cache, f)
    assert "火星城" not in cache          # 无结果不写缓存
    assert stats["failed"] == 1


def test_geocode_network_error_not_cached_resumable():
    f = _Fetcher({"上海": ConnectionError("boom")})
    cache = {}
    stats = G.geocode_cities(["上海"], cache, f)
    assert "上海" not in cache            # 报错不写 → 下次可重试
    assert stats["failed"] == 1


def test_geocode_skips_cached():
    f = _Fetcher({"上海": [{"lat": "1", "lon": "2"}]})
    cache = {"上海": {"lat": 31.2, "lng": 121.4, "status": "ok"}}
    stats = G.geocode_cities(["上海"], cache, f)
    assert f.calls == []                  # 命中缓存，根本不调用 fetch
    assert stats["skipped"] == 1
    assert cache["上海"]["lat"] == 31.2    # 旧值保留


def test_geocode_mixed_batch():
    f = _Fetcher({
        "上海": [{"lat": "31.2", "lon": "121.4"}],
        "空城": [],
        "错城": TimeoutError("t"),
    })
    cache = {}
    stats = G.geocode_cities(["上海", "空城", "错城"], cache, f)
    assert stats == {"added": 1, "failed": 2, "skipped": 0}
    assert set(cache) == {"上海"}
