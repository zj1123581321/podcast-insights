#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步骤4：把转录稿里主播名的 ASR 误写归一为规范名（就地修改 data/<key>/transcripts/*.txt）。

归一规则来自 config/<key>.json：
  - name_normalization：{规范名: [变体, ...]}，正文+标签全局替换。
  - label_normalization：{"昵称：": "规范名："}，仅替换说话人标签处（带冒号），
    避免动到正文里的口语昵称。

跑前会做一次"演练"统计要替换多少；--apply 才真正写盘。跑后报告每个规范名的覆盖文件数。

用法：
  PODCAST=feihua python pipeline/4_normalize_names.py          # 演练（dry-run）
  PODCAST=feihua python pipeline/4_normalize_names.py --apply  # 实际写盘
"""
import glob
import os
import sys
from collections import Counter

import _common as C

CFG = C.load_config()
KEY = CFG["key"]
DD = C.data_dir(KEY)
TRANS = str(DD / "transcripts")

APPLY = "--apply" in sys.argv

# 展平成 (变体 -> 规范名) 的有序列表（保留 config 中的顺序，顺序敏感）
GLOBAL_REPL = []
for canon, variants in CFG.get("name_normalization", {}).items():
    for v in variants:
        GLOBAL_REPL.append((v, canon))
LABEL_REPL = list(CFG.get("label_normalization", {}).items())
HOSTS = CFG.get("hosts", [])


def main():
    files = sorted(glob.glob(TRANS + "/*.txt"))
    if not files:
        raise SystemExit(f"[fatal] no transcripts under {TRANS}")
    totals = Counter()
    changed = 0
    for fp in files:
        t = open(fp, encoding="utf-8").read()
        orig = t
        for a, b in GLOBAL_REPL:
            c = t.count(a)
            if c:
                t = t.replace(a, b)
                totals[a] += c
        for a, b in LABEL_REPL:
            c = t.count(a)
            if c:
                t = t.replace(a, b)
                totals[a] += c
        if t != orig:
            changed += 1
            if APPLY:
                open(fp, "w", encoding="utf-8").write(t)

    mode = "APPLIED" if APPLY else "DRY-RUN (use --apply to write)"
    print(f"[{mode}] files_total={len(files)} files_to_change={changed}")
    for k, v in totals.most_common():
        print(f"  {k} -> {dict(GLOBAL_REPL).get(k) or dict(LABEL_REPL).get(k)}: {v}")

    # 覆盖率自检（按当前磁盘内容统计；--apply 后即为最终结果）
    print("=== host coverage (files containing canonical name) ===")
    for h in HOSTS:
        n = sum(1 for fp in files if h in open(fp, encoding="utf-8").read())
        print(f"  {h}: {n}/{len(files)}")


if __name__ == "__main__":
    main()
