# -*- coding: utf-8 -*-
"""步骤6 纯函数单测：id 生成、品类归一、media 兜底、城市规范化。

被测对象是 pipeline/_aggregate.py 的纯函数（不触网、不读盘）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import _aggregate as A  # noqa: E402


# ---- make_id：确定性、ASCII、与名称解耦 ----
def test_make_id_shape():
    assert A.make_id(12, "place", 3) == "12-place-3"
    assert A.make_id(1, "media", 0) == "1-media-0"


def test_make_id_deterministic():
    assert A.make_id(7, "product", 2) == A.make_id(7, "product", 2)


def test_make_id_is_ascii():
    s = A.make_id(234, "place", 11)
    assert s.isascii()


# ---- normalize_product_category：known→映射，unknown→透传，空→未分类 ----
def test_normalize_known():
    assert A.normalize_product_category("护肤", {"护肤": "护肤品"}) == "护肤品"


def test_normalize_unknown_passthrough():
    assert A.normalize_product_category("食品", {}) == "食品"


def test_normalize_empty():
    assert A.normalize_product_category("", {}) == "未分类"
    assert A.normalize_product_category(None, {}) == "未分类"


def test_normalize_strips_whitespace():
    assert A.normalize_product_category(" 护肤 ", {"护肤": "护肤品"}) == "护肤品"


# ---- media_category：category 空则用 type 兜底 ----
def test_media_uses_type_when_category_empty():
    assert A.media_category({"category": "", "type": "电影"}, {}) == "电影"


def test_media_keeps_category_when_present():
    assert A.media_category({"category": "剧集", "type": "x"}, {}) == "剧集"


def test_media_type_mapped():
    assert A.media_category({"category": "", "type": "美剧"}, {"美剧": "剧集"}) == "剧集"


def test_media_all_empty():
    assert A.media_category({"category": "", "type": ""}, {}) == "未分类"


# ---- canonical_city：脏值规范化 ----
def test_city_empty_is_none():
    assert A.canonical_city("", {}) is None
    assert A.canonical_city(None, {}) is None
    assert A.canonical_city("   ", {}) is None


def test_city_clean_passthrough():
    assert A.canonical_city("上海", {}) == "上海"


def test_city_strip_parenthetical():
    assert A.canonical_city("上海（武宁路附近）", {}) == "上海"
    assert A.canonical_city("大理（大理古城内）", {}) == "大理"


def test_city_split_on_middot_and_slash():
    assert A.canonical_city("东京·银座", {}) == "东京"
    assert A.canonical_city("东京/箱根", {}) == "东京"
    assert A.canonical_city("上海·富民路", {}) == "上海"


def test_city_override_wins():
    ov = {"东京大手町/涩谷": "东京", "江苏苏州（阳澄湖美人腿半岛）": "苏州"}
    assert A.canonical_city("东京大手町/涩谷", ov) == "东京"
    assert A.canonical_city("江苏苏州（阳澄湖美人腿半岛）", ov) == "苏州"


def test_city_override_checked_before_cleanup():
    # 通用清洗会得到“东京银座”，override 必须优先返回“东京”
    ov = {"东京银座（GINZA SIX旁）": "东京"}
    assert A.canonical_city("东京银座（GINZA SIX旁）", ov) == "东京"
