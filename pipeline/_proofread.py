# -*- coding: utf-8 -*-
"""步骤8（校对）的纯函数：抽条、解析 LLM 输出、按置信分流、就地应用。

背景：ASR 常把店名/地名/物品名听岔（如「萧四女」实为「肖四女」）。每集作者
手写的 description 是干净文本，配合该条 quote 的上下文，能让 LLM 判断哪个
名字 ASR 错了并给出正名。本模块只做确定性的数据搬运与校验，LLM 调用在
workflow / CLI 里完成。

全部无副作用（apply_corrections 例外：显式就地改传入 dict），便于单测。
"""
import re

NAME_KEY = {"place": "name", "product": "name", "media": "title"}
CATS = ["place", "product", "media"]
_ID_RE = re.compile(r"^(\d+)-(place|product|media)-(\d+)$")


def episode_items(vol, extracted):
    """抽该集所有条目为 [{id, category, name, quote}]，供 agent 校对。

    id 与聚合层一致（<vol>-<cat>-<idx>），改名不破链。
    """
    out = []
    for cat in CATS:
        for idx, item in enumerate(extracted.get(cat, []) or []):
            out.append({
                "id": f"{vol}-{cat}-{idx}",
                "category": cat,
                "name": item.get(NAME_KEY[cat], ""),
                "quote": item.get("quote", ""),
            })
    return out


def build_episode_input(vol, description, extracted):
    """组装单集校对输入（喂给 agent）。"""
    return {"vol": vol, "description": description or "",
            "items": episode_items(vol, extracted)}


def parse_corrections(payload):
    """规整 + 校验 agent 输出；丢弃非法/无效项。

    丢弃条件：空 id、空新名、新名==旧名、置信非数。置信夹到 [0,1]。
    """
    out = []
    for c in (payload or []):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", "")).strip()
        new = (c.get("new_name") or "").strip()
        old = (c.get("old_name") or "").strip()
        try:
            conf = float(c.get("confidence"))
        except (TypeError, ValueError):
            continue
        if conf != conf:  # NaN
            continue
        if not cid or not new or new == old:
            continue
        conf = max(0.0, min(1.0, conf))
        out.append({"id": cid, "old_name": old, "new_name": new,
                    "confidence": conf, "evidence": (c.get("evidence") or "").strip()})
    return out


def partition_corrections(corrections, threshold):
    """按置信阈值分流：>=阈值自动应用，其余进人工审核单。"""
    auto = [c for c in corrections if c["confidence"] >= threshold]
    review = [c for c in corrections if c["confidence"] < threshold]
    return auto, review


def parse_id(cid):
    """'35-place-2' -> (35,'place',2)；非法 -> None。"""
    m = _ID_RE.match(cid or "")
    if not m:
        return None
    return int(m.group(1)), m.group(2), int(m.group(3))


def apply_corrections(extracted_by_vol, corrections):
    """就地把 corrections 应用到 extracted dict。返回 (applied, skipped)。

    安全护栏：仅当当前名字与 old_name 一致才改（防数据漂移误伤）；
    定位失败/越界/非法 id 一律跳过。改动记录 name_original + name_corrected=True。
    """
    applied = skipped = 0
    for c in corrections:
        loc = parse_id(c.get("id", ""))
        if not loc:
            skipped += 1
            continue
        vol, cat, idx = loc
        ex = extracted_by_vol.get(vol)
        if not ex:
            skipped += 1
            continue
        arr = ex.get(cat) or []
        if idx >= len(arr):
            skipped += 1
            continue
        item = arr[idx]
        key = NAME_KEY[cat]
        if item.get(key, "") != c.get("old_name", ""):
            skipped += 1
            continue
        item["name_original"] = item.get(key, "")
        item[key] = c["new_name"]
        item["name_corrected"] = True
        applied += 1
    return applied, skipped
