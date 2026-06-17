# -*- coding: utf-8 -*-
"""校对纯函数单测：抽条、解析校验、置信分流、就地应用。

被测对象是 pipeline/_proofread.py（不触网、不读盘、无副作用除显式就地改 dict）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import _proofread as P  # noqa: E402


def _extracted():
    return {
        "episode": {"vol": 35, "title": "VOL.035"},
        "place": [
            {"name": "萧四女跷脚牛肉", "quote": "去吃了跷脚牛肉"},
            {"name": "厦门沙茶面", "quote": "录吃沙茶面"},
        ],
        "product": [{"name": "维他气泡柠檬茶", "quote": "维他柠檬茶很好喝"}],
        "media": [{"title": "非常律师禹英隅", "quote": "在追禹英禑"}],
    }


# ---- episode_items：抽出 id/category/name/quote ----
def test_episode_items_ids_and_name_key():
    items = P.episode_items(35, _extracted())
    ids = [i["id"] for i in items]
    assert ids == ["35-place-0", "35-place-1", "35-product-0", "35-media-0"]
    # media 取 title 作为 name
    media = [i for i in items if i["category"] == "media"][0]
    assert media["name"] == "非常律师禹英隅"
    assert media["quote"] == "在追禹英禑"


def test_build_episode_input_shape():
    inp = P.build_episode_input(35, "本期描述", _extracted())
    assert inp["vol"] == 35
    assert inp["description"] == "本期描述"
    assert len(inp["items"]) == 4


# ---- parse_corrections：规整 + 丢弃非法 ----
def test_parse_corrections_valid():
    out = P.parse_corrections([
        {"id": "35-place-0", "old_name": "萧四女跷脚牛肉", "new_name": "肖四女跷脚牛肉",
         "confidence": 0.9, "evidence": "描述写作肖四"},
    ])
    assert len(out) == 1
    assert out[0]["new_name"] == "肖四女跷脚牛肉"
    assert out[0]["confidence"] == 0.9


def test_parse_corrections_drops_empty_or_noop():
    out = P.parse_corrections([
        {"id": "1-place-0", "old_name": "a", "new_name": "", "confidence": 0.9},   # 空新名
        {"id": "1-place-1", "old_name": "x", "new_name": "x", "confidence": 0.9},  # 无变化
        {"id": "", "old_name": "a", "new_name": "b", "confidence": 0.9},           # 空 id
        {"id": "1-place-2", "old_name": "a", "new_name": "b", "confidence": "NaN"},  # 置信非数
    ])
    assert out == []


def test_parse_corrections_clamps_confidence():
    out = P.parse_corrections([
        {"id": "1-place-0", "old_name": "a", "new_name": "b", "confidence": 1.7},
        {"id": "1-place-1", "old_name": "a", "new_name": "b", "confidence": -0.3},
    ])
    assert out[0]["confidence"] == 1.0
    assert out[1]["confidence"] == 0.0


def test_parse_corrections_handles_none():
    assert P.parse_corrections(None) == []


# ---- partition_corrections：按阈值分流 ----
def test_partition_by_threshold():
    cs = [
        {"id": "a", "confidence": 0.9},
        {"id": "b", "confidence": 0.85},
        {"id": "c", "confidence": 0.6},
    ]
    auto, review = P.partition_corrections(cs, 0.85)
    assert [c["id"] for c in auto] == ["a", "b"]   # >= 阈值
    assert [c["id"] for c in review] == ["c"]


# ---- parse_id ----
def test_parse_id_ok():
    assert P.parse_id("35-place-2") == (35, "place", 2)
    assert P.parse_id("1-media-0") == (1, "media", 0)


def test_parse_id_bad():
    assert P.parse_id("35-foo-2") is None
    assert P.parse_id("nope") is None
    assert P.parse_id("") is None


# ---- apply_corrections：就地改 + 留痕 + 防漂移 ----
def test_apply_corrections_mutates_and_records():
    ex = {35: _extracted()}
    corr = [{"id": "35-place-0", "old_name": "萧四女跷脚牛肉",
             "new_name": "肖四女跷脚牛肉", "confidence": 0.9, "evidence": "e"}]
    applied, skipped = P.apply_corrections(ex, corr)
    assert (applied, skipped) == (1, 0)
    item = ex[35]["place"][0]
    assert item["name"] == "肖四女跷脚牛肉"
    assert item["name_original"] == "萧四女跷脚牛肉"
    assert item["name_corrected"] is True


def test_apply_corrections_media_uses_title():
    ex = {35: _extracted()}
    corr = [{"id": "35-media-0", "old_name": "非常律师禹英隅",
             "new_name": "非常律师禹英禑", "confidence": 0.95, "evidence": "e"}]
    applied, _ = P.apply_corrections(ex, corr)
    assert applied == 1
    assert ex[35]["media"][0]["title"] == "非常律师禹英禑"


def test_apply_corrections_skips_on_drift():
    # old_name 与现有不符（数据漂移）→ 跳过，不误改
    ex = {35: _extracted()}
    corr = [{"id": "35-place-0", "old_name": "对不上的旧名",
             "new_name": "随便", "confidence": 0.99, "evidence": "e"}]
    applied, skipped = P.apply_corrections(ex, corr)
    assert (applied, skipped) == (0, 1)
    assert ex[35]["place"][0]["name"] == "萧四女跷脚牛肉"  # 未动


def test_apply_corrections_skips_unknown_location():
    ex = {35: _extracted()}
    corr = [
        {"id": "99-place-0", "old_name": "x", "new_name": "y", "confidence": 1},   # vol 不存在
        {"id": "35-place-9", "old_name": "x", "new_name": "y", "confidence": 1},   # idx 越界
        {"id": "bad-id", "old_name": "x", "new_name": "y", "confidence": 1},       # 非法 id
    ]
    applied, skipped = P.apply_corrections(ex, corr)
    assert (applied, skipped) == (0, 3)
