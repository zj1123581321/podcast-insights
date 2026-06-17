# -*- coding: utf-8 -*-
"""步骤7 纯函数单测：Nominatim 响应解析 + 断点续跑编排（fetch 注入，不触网）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import _geocode as G  # noqa: E402


# ---- province_of ----
def test_province_with_province_segment():
    assert G.province_of("大理白族自治州, 云南省, 中国") == "云南省"
    assert G.province_of("秦皇岛市, 河北省, 中国") == "河北省"
    assert G.province_of("黔东南苗族侗族自治州, 贵州省, 中国") == "贵州省"


def test_province_municipality():
    assert G.province_of("上海市, 中国") == "上海市"
    assert G.province_of("北京市, 中国") == "北京市"


def test_province_overseas_is_country():
    assert G.province_of("东京都/東京都, 日本") == "日本"
    assert G.province_of("大倫敦;大伦敦, 英格兰;英格蘭, 英国;英國") == "英国"


def test_province_empty():
    assert G.province_of("") == ""
    assert G.province_of(None) == ""


# ---- parse_nominatim ----
def test_parse_happy():
    out = G.parse_nominatim([{"lat": "31.23", "lon": "121.47", "display_name": "上海市, 中国"}])
    assert out["lat"] == 31.23
    assert out["lng"] == 121.47
    assert out["status"] == "ok"
    assert "上海" in out["display_name"]
    assert out["province"] == "上海市"


def test_parse_empty_list():
    assert G.parse_nominatim([]) is None
    assert G.parse_nominatim(None) is None


def test_parse_missing_or_bad_coords():
    assert G.parse_nominatim([{"display_name": "x"}]) is None
    assert G.parse_nominatim([{"lat": "NaNish", "lon": "1"}]) is None


# ---- apply_overrides：人工坐标覆盖 ----
def test_apply_overrides_sets_coords_and_province():
    cache = {}
    n = G.apply_overrides(cache, {"上虞": {"lat": 30.03, "lng": 120.87,
                                          "display_name": "上虞区, 绍兴市, 浙江省, 中国"}})
    assert n == 1
    assert cache["上虞"]["lat"] == 30.03
    assert cache["上虞"]["province"] == "浙江省"
    assert cache["上虞"]["status"] == "override"


def test_apply_overrides_overwrites_wrong_cached():
    cache = {"上虞": {"lat": 35.85, "lng": 114.17, "province": "河南省", "status": "ok"}}
    G.apply_overrides(cache, {"上虞": {"lat": 30.03, "lng": 120.87,
                                      "display_name": "上虞区, 绍兴市, 浙江省, 中国"}})
    assert cache["上虞"]["province"] == "浙江省"   # 误命中被覆盖


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
