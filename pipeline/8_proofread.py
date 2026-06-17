#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""步骤8：用每集作者手写 description 校对 ASR 听岔的店名/地名/物品名。

LLM 判断在 workflow 里并发完成（pipeline/8_proofread.workflow.js），本 CLI 负责
确定性的两端：
  --build-inputs   汇总每集 {vol, description, items[{id,name,quote}]} ->
                   data/<key>/proofread/{vol:03d}.json （供 workflow 的 agent 逐集读取）
  --apply FILE     读取 workflow 产出的修正数组，按置信阈值分流：
                     高置信 -> 就地改 extracted/*.json（留 name_original + name_corrected）
                     低置信 -> data/<key>/corrections_review.json（人工过目）
                   同时落 corrections_applied.json（已改留档，便于回溯）。

阈值默认 0.85（保守，护住「对照原文核验过」的招牌）；可用 --threshold 调。

用法：
  PODCAST=feihua python pipeline/8_proofread.py --build-inputs
  PODCAST=feihua python pipeline/8_proofread.py --apply data/feihua/corrections_raw.json
"""
import argparse
import glob
import json
import re

import _common as C
import _proofread as P

CFG = C.load_config()
KEY = CFG["key"]
DD = C.data_dir(KEY)
EXTRACTED = DD / "extracted"
EPISODES_META = DD / "episodes" / "episodes.json"
INPUTS_DIR = DD / "proofread"
THRESHOLD_DEFAULT = float(CFG.get("proofread_threshold", 0.85))


def _vol_of(name):
    m = re.search(r"VOL\.?\s*(\d+)", name or "", re.I)
    return int(m.group(1)) if m else None


def load_extracted():
    """{vol: extracted dict}（按文件名 vol 排序读取）。"""
    out = {}
    for fp in sorted(glob.glob(str(EXTRACTED / "*.json"))):
        try:
            d = json.loads(open(fp, encoding="utf-8").read())
        except Exception:
            continue
        ep = d.get("episode", {})
        vol = ep.get("vol") or _vol_of(ep.get("title", ""))
        if vol:
            out[int(vol)] = d
    return out


def desc_by_vol(extracted):
    """eid->description（episodes.json）映射到 vol。"""
    meta = {}
    if EPISODES_META.exists():
        try:
            for e in json.loads(EPISODES_META.read_text(encoding="utf-8")):
                if e.get("eid"):
                    meta[e["eid"]] = e.get("description", "") or ""
        except Exception:
            pass
    out = {}
    for vol, d in extracted.items():
        out[vol] = meta.get(d.get("episode", {}).get("eid"), "")
    return out


def build_inputs():
    extracted = load_extracted()
    descs = desc_by_vol(extracted)
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    n_items = 0
    for vol, d in sorted(extracted.items()):
        inp = P.build_episode_input(vol, descs.get(vol, ""), d)
        n_items += len(inp["items"])
        (INPUTS_DIR / f"{vol:03d}.json").write_text(
            json.dumps(inp, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build-inputs] {len(extracted)} 集 / {n_items} 条 -> {INPUTS_DIR}")


def apply_file(raw_path, threshold):
    raw = json.loads(open(raw_path, encoding="utf-8").read())
    # 兼容 {"corrections":[...]} 或直接 [...]。
    payload = raw.get("corrections", raw) if isinstance(raw, dict) else raw
    corrections = P.parse_corrections(payload)
    auto, review = P.partition_corrections(corrections, threshold)
    print(f"[apply] 收到 {len(payload)} 条，规整后 {len(corrections)} 条；"
          f"阈值 {threshold} -> 自动改 {len(auto)} / 待审 {len(review)}")

    extracted = load_extracted()
    applied, skipped = P.apply_corrections(extracted, auto)
    print(f"[apply] 就地应用 {applied} 条，跳过 {skipped} 条（漂移/越界）")

    # 落盘被改的 extracted 文件
    touched = {P.parse_id(c["id"])[0] for c in auto if P.parse_id(c["id"])}
    for vol in sorted(touched):
        if vol in extracted:
            (EXTRACTED / f"{vol:03d}.json").write_text(
                json.dumps(extracted[vol], ensure_ascii=False, indent=2), encoding="utf-8")

    (DD / "corrections_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    (DD / "corrections_applied.json").write_text(
        json.dumps(auto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[apply] 审核单 -> {DD/'corrections_review.json'}（{len(review)} 条）")
    print(f"[apply] 已改留档 -> {DD/'corrections_applied.json'}（{len(auto)} 条）")
    print("[next] 重跑 6_aggregate + 7_geocode 重生成前端数据")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-inputs", action="store_true")
    ap.add_argument("--apply", metavar="FILE")
    ap.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT)
    args = ap.parse_args()
    if args.build_inputs:
        build_inputs()
    elif args.apply:
        apply_file(args.apply, args.threshold)
    else:
        ap.error("需指定 --build-inputs 或 --apply FILE")


if __name__ == "__main__":
    main()
