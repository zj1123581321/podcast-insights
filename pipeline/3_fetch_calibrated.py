#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步骤3：把每集"校对过"的转录稿(?raw=calibrated)拉到本地为 TXT。
  data/<key>/episodes/view_urls.json  ->  data/<key>/transcripts/{vol:03d}_{title}.txt

命名用零填充的 VOL 号前缀，便于按集顺序排序；标题里若无 VOL 号则回退为序号。
view 路由是公开的，无需鉴权；只需 VIEW_API_BASE（缺省取 TRANSCRIBE_API_BASE）。

用法：  PODCAST=feihua python pipeline/3_fetch_calibrated.py
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

import _common as C

C.load_dotenv()
CFG = C.load_config()
KEY = CFG["key"]
DD = C.ensure_dirs(KEY)
VIEW_JSON = DD / "episodes" / "view_urls.json"
OUT_DIR = DD / "transcripts"

API_BASE = (os.environ.get("VIEW_API_BASE")
            or os.environ.get("TRANSCRIBE_API_BASE", "")).rstrip("/")

ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]+')
VOL_RE = re.compile(r'VOL[._]?\s*0*(\d+)', re.IGNORECASE)


def vol_num(title, fallback):
    m = VOL_RE.search(title or "")
    return int(m.group(1)) if m else fallback


def clean_title(title):
    t = re.sub(r'[｜|]?\s*VOL[._]?\s*\d+\s*', '', title or '', flags=re.IGNORECASE)
    t = t.strip(' ：:｜|·-')
    return (ILLEGAL.sub('_', t)[:80]) or "untitled"


def token_from_url(view_url):
    return view_url.rstrip('/').split('/view/')[-1].split('?')[0]


def fetch_calibrated(token):
    url = f"{API_BASE}/view/{urllib.parse.quote(token)}?raw=calibrated"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    if not API_BASE:
        raise SystemExit("[fatal] set VIEW_API_BASE or TRANSCRIBE_API_BASE (.env)")
    rows = json.load(open(VIEW_JSON, encoding="utf-8"))
    ok, fail = 0, []
    for i, row in enumerate(rows, 1):
        title = row.get("title", "")
        view_url = row.get("view_url", "")
        if not view_url:
            fail.append((title, "no view_url"))
            continue
        num = vol_num(title, i)
        fpath = OUT_DIR / f"{num:03d}_{clean_title(title)}.txt"
        try:
            code, text = fetch_calibrated(token_from_url(view_url))
            if code != 200 or not text.strip():
                fail.append((fpath.name, f"code={code} len={len(text)}"))
                continue
            fpath.write_text(text, encoding="utf-8")
            ok += 1
            if i % 20 == 0:
                print(f"  {i}/{len(rows)} ... {fpath.name}")
        except Exception as e:
            fail.append((fpath.name, repr(e)[:80]))
        time.sleep(0.2)
    print(f"[done] saved={ok} failed={len(fail)} -> {OUT_DIR}")
    for f in fail[:20]:
        print("  FAIL", f)


if __name__ == "__main__":
    main()
