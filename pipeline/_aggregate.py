# -*- coding: utf-8 -*-
"""步骤6 的纯函数：id 生成、品类归一、media 兜底、城市规范化。

全部无副作用、不触网、不读盘 —— 便于单测，也供 6_aggregate.py 复用。
映射表由调用方从 config/<key>.json 传入（category_normalization /
media_type_map / city_canonical.overrides）。
"""
import re

DEFAULT_CATEGORY = "未分类"

# 通用城市清洗：先去成对括号内容，再按分隔符取首段。
_PAREN_RE = re.compile(r"[（(].*?[)）]")
_SEP_RE = re.compile(r"[·/、]")


def make_id(vol: int, cat: str, idx: int) -> str:
    """确定性深链 id：<vol>-<type>-<idx>。

    idx = 该集该类别数组内的位置（0 起）。ASCII、与名称解耦，
    改名/校正不坏链；只要提取数组顺序稳定，id 即稳定。
    """
    return f"{vol}-{cat}-{idx}"


def normalize_product_category(raw, norm_map: dict) -> str:
    """product 品类归一：命中映射→规范名；未命中→透传原值；空→未分类。"""
    s = (raw or "").strip()
    if not s:
        return DEFAULT_CATEGORY
    return norm_map.get(s, s)


def media_category(item: dict, type_map: dict) -> str:
    """media 的 item.category 全空 → 用 item.type 兜底（可经 type_map 归一）。"""
    cat = (item.get("category") or "").strip()
    if cat:
        return cat
    t = (item.get("type") or "").strip()
    if not t:
        return DEFAULT_CATEGORY
    return type_map.get(t, t)


def canonical_city(raw, overrides: dict):
    """脏 city 值 → 规范城市名（geocode/join 的 key）。

    顺序：空→None；显式 override 优先；否则通用清洗（去括号内容、按
    ·//、取首段）。无法判定时返回 None（前端归入“未定位”）。
    """
    s = (raw or "").strip()
    if not s:
        return None
    if s in overrides:
        return overrides[s] or None
    s = _PAREN_RE.sub("", s).strip()
    s = _SEP_RE.split(s)[0].strip()
    return s or None
