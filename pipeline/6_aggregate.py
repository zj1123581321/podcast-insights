#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步骤6：对结构化提取结果做确定性收尾（不调用 LLM）。
  data/<key>/extracted/{vol:03d}.json  ->  data/<key>/recommendations_all.{json,md}

三件事：
  1) 合法性/完整性校验：列出缺失或 JSON 非法的集数（供回炉重跑）。
  2) quote 反查：每条推荐的 quote 必须能在对应转录稿里逐字命中，否则标 quote_unverified=true。
     （经验：约两成 quote 是 agent 复述/精简而非逐字，内容多属实，仅作存疑标注。）
  3) 聚合：汇总成 recommendations_all.json + 可读的 recommendations_all.md
     （按 类别 -> verdict 分组，标注集数/主播/是否存疑）。

用法：
  PODCAST=feihua python pipeline/6_aggregate.py            # 校验 + 聚合
  PODCAST=feihua python pipeline/6_aggregate.py --list-bad # 只吐缺失/非法集号（逗号分隔，喂回 workflow 的 vols）
"""
import glob
import json
import os
import re
import sys

import _aggregate as A
import _common as C

CFG = C.load_config()
KEY = CFG["key"]
DD = C.data_dir(KEY)
EXTRACTED = DD / "extracted"
TRANS = DD / "transcripts"
TOTAL = int(os.environ.get("TOTAL", str(CFG.get("total_episodes", 234))))

CATS = ["place", "product", "media"]
CAT_CN = {"place": "实地/出行推荐", "product": "好物推荐", "media": "影视剧推荐"}
VERDICT_ORDER = {"重点推荐": 0, "推荐": 1, "一般": 2, "避雷": 3}
NAME_KEY = A.NAME_KEY
KNOWN_REC = set(CFG.get("hosts", [])) | {"共同"}

# 归一/规范化映射（来自 config），统一传给纯函数 _aggregate.build_row。
MAPS = {
    "prod_norm": CFG.get("category_normalization", {}),
    "media_map": CFG.get("media_type_map", {}),
    "city_overrides": CFG.get("city_canonical", {}).get("overrides", {}),
}


def transcript_path(vol):
    hits = glob.glob(str(TRANS / f"{vol:03d}_*.txt"))
    return hits[0] if hits else None


def load_transcript(vol, cache):
    if vol not in cache:
        p = transcript_path(vol)
        cache[vol] = open(p, encoding="utf-8").read() if p else ""
    return cache[vol]


def norm(s):
    return re.sub(r"\s+", "", s or "")


def quote_hit(quote, text, ntext):
    if not quote:
        return False
    return quote in text or norm(quote) in ntext


def main():
    list_bad = "--list-bad" in sys.argv
    present, missing, invalid = {}, [], []
    for vol in range(1, TOTAL + 1):
        fp = EXTRACTED / f"{vol:03d}.json"
        if not fp.exists():
            missing.append(vol)
            continue
        try:
            present[vol] = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            invalid.append(vol)

    bad = sorted(missing + invalid)
    if list_bad:
        print(",".join(str(v) for v in bad))
        return

    print(f"[check] total={TOTAL} present={len(present)} missing={len(missing)} invalid={len(invalid)}")
    if missing:
        print(f"  missing vols: {missing}")
    if invalid:
        print(f"  invalid vols: {invalid}")

    tcache, rows = {}, []
    counts = {c: 0 for c in CATS}
    unverified = 0
    place_unlocated = 0
    by_rec = {}

    for vol in sorted(present):
        d = present[vol]
        title = d.get("episode", {}).get("title", "")
        text = load_transcript(vol, tcache)
        ntext = norm(text)
        for cat in CATS:
            for idx, item in enumerate(d.get(cat, []) or []):
                verified = quote_hit(item.get("quote", ""), text, ntext)
                if not verified:
                    unverified += 1
                rec = item.get("recommender", "")
                key = rec if rec in KNOWN_REC else "其他"
                by_rec[key] = by_rec.get(key, 0) + 1
                counts[cat] += 1
                row = A.build_row(vol, title, cat, idx, item, verified, MAPS)
                if cat == "place" and row["city_key"] is None:
                    place_unlocated += 1
                rows.append(row)

    distinct_cities = sorted({r["city_key"] for r in rows
                              if r["category"] == "place" and r["city_key"]})

    out_json = DD / "recommendations_all.json"
    out_json.write_text(json.dumps({
        "podcast": {"key": KEY, "name": CFG.get("name", "")},
        "stats": {"episodes_with_data": len(present), "missing": missing,
                  "invalid": invalid, "counts": counts, "total_items": len(rows),
                  "quote_unverified": unverified, "by_recommender": by_rec,
                  "place_unlocated": place_unlocated,
                  "distinct_cities": len(distinct_cities)},
        "items": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# 《{CFG.get('name','')}》推荐总清单\n"]
    lines.append(f"- 覆盖集数：{len(present)}/{TOTAL}　推荐总条数：{len(rows)}"
                 f"（实地 {counts['place']} / 好物 {counts['product']} / 影视剧 {counts['media']}）")
    rec_summary = " / ".join(f"{k} {v}" for k, v in by_rec.items())
    lines.append(f"- 推荐人分布：{rec_summary}　|　quote 存疑 {unverified} 条（⚠ 标注）\n")

    def fmt(r):
        it, cat = r["item"], r["category"]
        flag = " ⚠" if r["quote_unverified"] else ""
        head = f"- **{r['name']}**（VOL.{r['vol']:03d}·{r['recommender']}·{r['verdict']}{flag}）"
        if cat == "place":
            extra = f"　{it.get('city','')}｜{it.get('category','')}｜{it.get('what','')}"
            reason = it.get("reason", "")
        elif cat == "product":
            price = it.get("price_hint", "")
            extra = f"　{it.get('category','')}" + (f"｜{price}" if price else "")
            reason = it.get("why_good", "")
        else:
            extra = f"　{it.get('type','')}｜{it.get('synopsis','')}"
            reason = it.get("why_recommended", "")
        return f"{head}{extra}\n  - 理由：{reason}\n  - 原文：「{it.get('quote','')}」"

    for cat in CATS:
        sub = sorted([r for r in rows if r["category"] == cat],
                     key=lambda r: (VERDICT_ORDER.get(r["verdict"], 9), r["vol"]))
        lines.append(f"\n## {CAT_CN[cat]}（{len(sub)} 条）\n")
        cur = None
        for r in sub:
            if r["verdict"] != cur:
                cur = r["verdict"]
                lines.append(f"\n### {cur}\n")
            lines.append(fmt(r))

    (DD / "recommendations_all.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[aggregate] items={len(rows)} unverified={unverified}")
    print(f"  -> {out_json}")
    print(f"  -> {DD/'recommendations_all.md'}")
    if bad:
        print(f"[!] {len(bad)} 集缺失/非法，建议回炉：{bad}")


if __name__ == "__main__":
    main()
