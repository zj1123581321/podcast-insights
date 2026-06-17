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

# 省/自治区/国家前缀：形如「江苏南通」「意大利罗马」时剥掉前缀取城市。
# 不含直辖市（北京/上海/天津/重庆）——它们的带后缀写法都用分隔符/括号，
# 若放进来反而会把「上海某路」误切成「某路」。按长度降序匹配（先内蒙古后…）。
_PREFIXES = tuple(sorted([
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建",
    "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "四川",
    "贵州", "云南", "陕西", "甘肃", "青海", "台湾", "内蒙古", "西藏", "宁夏", "新疆",
    "日本", "泰国", "荷兰", "法国", "意大利", "英国", "美国", "德国", "韩国", "新加坡",
], key=len, reverse=True))


def _strip_region_prefix(s: str) -> str:
    """剥省/国前缀：「江苏南通」→「南通」；剩余 <2 字则保留（如「四川」整体）。"""
    for p in _PREFIXES:
        if s.startswith(p) and len(s) - len(p) >= 2:
            return s[len(p):]
    return s


def pub_date_of(raw) -> str:
    """ISO 时间戳 → 「YYYY-MM-DD」；非日期/空 → 空串。

    小宇宙 pubDate 形如 2026-06-14T23:30:00.000Z，前端只需到天。
    """
    s = (raw or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else ""


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
    s = _strip_region_prefix(s)
    return s or None


NAME_KEY = {"place": "name", "product": "name", "media": "title"}


def build_episodes(present: dict, ep_meta_by_eid: dict) -> list:
    """单集元数据数组（前端单集 banner / 时间线用），按 vol 升序。

    present: {vol: 该集 extracted dict}（含 episode.eid/title/source_url）。
    ep_meta_by_eid: {eid: {pubDate, description, ...}}（来自 episodes.json）。
    描述/日期缺失时留空串，不报错。
    """
    out = []
    for vol in sorted(present):
        ep = present[vol].get("episode", {})
        meta = ep_meta_by_eid.get(ep.get("eid"), {})
        out.append({
            "vol": vol,
            "title": ep.get("title", ""),
            "pub_date": pub_date_of(meta.get("pubDate", "")),
            "description": (meta.get("description") or "").strip(),
            "ep_url": ep.get("source_url", ""),
        })
    return out


def build_row(vol, title, cat, idx, item, verified, maps, ep_url="", pub_date=""):
    """组装一条聚合行（前端契约）。

    会就地归一 item.category（product/media），并派生 place 的
    city_key/display_city。其余历史字段保持不变（id 之外新增字段不破坏既有消费者）。

    ep_url：来源单集的小宇宙链接（前端"听原集"用，便于用户核实）。
    maps: {prod_norm, media_map, city_overrides}
    """
    if cat == "product":
        item["category"] = normalize_product_category(item.get("category"), maps.get("prod_norm", {}))
    elif cat == "media":
        item["category"] = media_category(item, maps.get("media_map", {}))

    city_key = display_city = None
    if cat == "place":
        city_key = canonical_city(item.get("city"), maps.get("city_overrides", {}))
        display_city = city_key

    return {
        "id": make_id(vol, cat, idx),
        "vol": vol,
        "ep_title": title,
        "ep_url": ep_url,
        "pub_date": pub_date,
        "category": cat,
        "recommender": item.get("recommender", ""),
        "verdict": item.get("verdict", ""),
        "name": item.get(NAME_KEY[cat], ""),
        "city_key": city_key,
        "display_city": display_city,
        "quote_unverified": (not verified),
        "item": item,
    }
