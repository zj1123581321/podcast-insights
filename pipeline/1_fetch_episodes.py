#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步骤1：抓取小宇宙(xiaoyuzhoufm)某节目的全部历史单集 -> data/<key>/episodes/episodes.json

两种取数方式：

1. API 模式（默认，全量回填）：参考 ultrazg/xyz 的 API
   （/v1/search/create、/v1/episode/list、/app_auth_tokens.refresh），直连官方 API 分页拉全历史。
   - 敏感信息(access/refresh token)全部走环境变量，禁止硬编码（仓库开源）。
   - Android 客户端配方刷新 token：仅需 device-id + refresh-token、body={}、不带 access-token。
   - refresh token 是一次性轮换的：刷新成功后旧 token 立即失效，新 token 持久化到
     data/<key>/episodes/.token_state.json（已 gitignore），避免与生产端共用同一 token 互相失效。
   - 节目 pid 优先取 config 的 xyz_pid，否则按 name 搜索。

2. 公开页模式（--public，增量、无 token）：抓节目主页 /podcast/<pid> 的 __NEXT_DATA__，
   里面内嵌完整单集对象（字段与 API 一致），用同一个 slim() 提取后【合并】进 episodes.json。
   - 只需 config.xyz_pid，不需要任何 token。
   - 公开页仅含最近一批（~15 集），故为【增量】：只把 episodes.json 里没有的 eid 补进去。
   - 适合"节目更新了几集"的日常增量；要回填全部历史仍走 API 模式。

用法：
  PODCAST=feihua python pipeline/1_fetch_episodes.py            # API 全量
  PODCAST=feihua python pipeline/1_fetch_episodes.py --public   # 公开页增量（无 token）
环境变量见 .env.example（XYZ_REFRESH_TOKEN / XYZ_ACCESS_TOKEN / XYZ_DEVICE_ID；--public 全都不需要）
"""
import argparse
import json
import os
import re
import sys
import time
import random

import requests

import _common as C

BASE_URL = "https://api.xiaoyuzhoufm.com"
SEARCH_PATH = "/v1/search/create"
EPISODE_LIST_PATH = "/v1/episode/list"
REFRESH_PATH = "/app_auth_tokens.refresh"
REQUEST_TIMEOUT = 20
PAGE_SLEEP = 0.4

C.load_dotenv()
CFG = C.load_config()
KEY = CFG["key"]
DD = C.ensure_dirs(KEY)
OUT_DIR = DD / "episodes"
TOKEN_STATE = OUT_DIR / ".token_state.json"

_ACCESS = ""
_REFRESH = ""
_DEVICE = ""


def _gen_device_id() -> str:
    chars = "0123456789abcdef"
    segs = [8, 4, 4, 4, 12]
    return "-".join("".join(random.choice(chars) for _ in range(n)) for n in segs)


def init_identity() -> None:
    global _ACCESS, _REFRESH, _DEVICE
    state = {}
    if TOKEN_STATE.exists():
        try:
            state = json.loads(TOKEN_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    _ACCESS = state.get("accessToken") or os.environ.get("XYZ_ACCESS_TOKEN", "").strip()
    _REFRESH = state.get("refreshToken") or os.environ.get("XYZ_REFRESH_TOKEN", "").strip()
    _DEVICE = (os.environ.get("XYZ_DEVICE_ID", "").strip()
               or state.get("deviceId") or _gen_device_id())


def save_identity() -> None:
    try:
        TOKEN_STATE.write_text(json.dumps({
            "accessToken": _ACCESS, "refreshToken": _REFRESH, "deviceId": _DEVICE,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[token] warn: save state failed: {exc}")


def build_headers() -> dict:
    return {
        "Content-Type": "application/json;charset=utf-8",
        "User-Agent": "Xiaoyuzhou/2.102.2(android 36)",
        "os": "android", "os-version": "36", "manufacturer": "Xiaomi",
        "model": "23127PN0CC", "applicationid": "app.podcast.cosmos",
        "app-version": "2.102.2", "app-buildno": "1395",
        "x-jike-device-id": _DEVICE, "x-jike-access-token": _ACCESS,
    }


def refresh_access_token() -> bool:
    global _ACCESS, _REFRESH
    if not _REFRESH:
        print("[token] no refresh token available")
        return False
    print("[token] refreshing access token ...")
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "User-Agent": "Xiaoyuzhou/2.102.2(android 36)",
        "x-jike-device-id": _DEVICE, "x-jike-refresh-token": _REFRESH,
    }
    resp = requests.post(BASE_URL + REFRESH_PATH, headers=headers, json={}, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        print(f"[token] refresh failed: status={resp.status_code} body={resp.text[:160]}")
        return False
    body = resp.json()
    new_token = body.get("x-jike-access-token", "")
    new_refresh = body.get("x-jike-refresh-token", "")
    if new_token:
        _ACCESS = new_token
        if new_refresh:
            _REFRESH = new_refresh
        save_identity()
        print("[token] refreshed successfully (state persisted)")
        return True
    print("[token] refresh 200 but no access token in response")
    return False


def post_json(path: str, body: dict) -> dict:
    url = BASE_URL + path
    for attempt in range(2):
        resp = requests.post(url, headers=build_headers(), json=body, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 401 and attempt == 0 and refresh_access_token():
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"POST {path} failed: status={resp.status_code} body={resp.text[:300]}")
        return resp.json()
    raise RuntimeError(f"POST {path} failed after token refresh")


def unwrap(obj: dict) -> dict:
    return obj["data"] if isinstance(obj.get("data"), dict) else obj


def search_pid(name: str) -> str:
    print(f"[search] querying podcast by name: {name!r}")
    payload = unwrap(post_json(SEARCH_PATH, {"keyword": name, "type": "PODCAST"}))
    items = [it for it in (payload.get("data") or []) if it.get("type") == "PODCAST"]
    if not items:
        raise RuntimeError("no podcast found")
    exact = [pc for pc in items if pc.get("title") == name]
    chosen = exact[0] if exact else items[0]
    print(f"[search] chosen pid={chosen.get('pid')} title={chosen.get('title')!r}")
    return chosen["pid"]


def slim(ep: dict) -> dict:
    enclosure = ep.get("enclosure") or {}
    media = ep.get("media") or {}
    eid = ep.get("eid", "")
    return {
        "eid": eid, "title": ep.get("title", ""), "pubDate": ep.get("pubDate", ""),
        "description": (ep.get("description") or "").strip(),
        "duration": ep.get("duration"), "isPrivateMedia": ep.get("isPrivateMedia", False),
        "audio_url": enclosure.get("url") or media.get("source", {}).get("url", ""),
        "episode_url": f"https://www.xiaoyuzhoufm.com/episode/{eid}" if eid else "",
        "playCount": ep.get("playCount"), "commentCount": ep.get("commentCount"),
    }


def fetch_all(pid: str) -> list:
    all_eps, key, total, page = [], None, None, 0
    while True:
        page += 1
        body = {"pid": pid, "order": "desc"}
        if key:
            body["loadMoreKey"] = key
        payload = unwrap(post_json(EPISODE_LIST_PATH, body))
        eps = payload.get("data") or []
        all_eps.extend(eps)
        if total is None:
            total = payload.get("total")
        key = payload.get("loadMoreKey")
        print(f"[episodes] page={page} got={len(eps)} accumulated={len(all_eps)}"
              + (f"/{total}" if total else ""))
        if not key or not eps:
            break
        time.sleep(PAGE_SLEEP)
    if total is not None and len(all_eps) != total:
        print(f"[episodes] WARNING: fetched {len(all_eps)} but server total={total}")
    return all_eps


# ── 公开页模式（无 token）───────────────────────────────────────────────
PODCAST_PAGE = "https://www.xiaoyuzhoufm.com/podcast/{pid}"
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _extract_next_data(html_text: str) -> dict:
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        raise RuntimeError("公开页未找到 __NEXT_DATA__（页面结构可能已改版）")
    return json.loads(m.group(1))


def _walk_episodes(obj, pid: str, acc: dict) -> None:
    """深搜 __NEXT_DATA__，收集属于本 pid 的完整单集对象（按 eid 去重）。"""
    if isinstance(obj, dict):
        if obj.get("eid") and obj.get("title") and obj.get("pubDate") \
                and (not pid or obj.get("pid") == pid):
            acc.setdefault(obj["eid"], obj)
        for v in obj.values():
            _walk_episodes(v, pid, acc)
    elif isinstance(obj, list):
        for v in obj:
            _walk_episodes(v, pid, acc)


def fetch_public(pid: str) -> list:
    url = PODCAST_PAGE.format(pid=pid)
    print(f"[public] GET {url}")
    resp = requests.get(url, headers={"User-Agent": WEB_UA}, timeout=REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"公开页请求失败 status={resp.status_code}")
    data = _extract_next_data(resp.text)
    acc: dict = {}
    _walk_episodes(data, pid, acc)
    eps = list(acc.values())
    print(f"[public] 页面含本节目单集 {len(eps)} 集（公开页仅最近一批）")
    return eps


def run_public() -> int:
    pid = (CFG.get("xyz_pid") or "").strip()
    if not pid:
        print("[fatal] --public 需要 config.xyz_pid（无 token 无法按名搜索）", file=sys.stderr)
        return 2
    print(f"[init] podcast={KEY} pid={pid} mode=public(no-token)")
    raw = fetch_public(pid)
    if not raw:
        print("[public] 没抓到单集，页面结构可能已改版", file=sys.stderr)
        return 1

    ep_path = OUT_DIR / "episodes.json"
    existing = []
    if ep_path.exists():
        try:
            existing = json.loads(ep_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    have = {e.get("eid") for e in existing}
    added = [slim(e) for e in raw if e.get("eid") not in have]
    merged = existing + added
    merged.sort(key=lambda e: e.get("pubDate") or "", reverse=True)  # 新→旧，对齐 API 原生序
    ep_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] +{len(added)} 新集 / 共 {len(merged)} -> {ep_path}")
    for e in sorted(added, key=lambda x: x.get("pubDate") or ""):
        print(f"   + {(e.get('pubDate') or '')[:10]}  {e.get('title','')}")
    if not added:
        print("   （无新增；episodes.json 已是最新）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取小宇宙节目单集清单")
    parser.add_argument("--public", action="store_true",
                        help="公开页增量模式（无需 token，只补最近新增的单集）")
    args = parser.parse_args()
    if args.public:
        return run_public()

    init_identity()
    if not _ACCESS and not _REFRESH:
        print("[fatal] need XYZ_ACCESS_TOKEN or XYZ_REFRESH_TOKEN (.env)", file=sys.stderr)
        return 2
    print(f"[init] podcast={KEY} device-id={_DEVICE}")
    if not _ACCESS and not refresh_access_token():
        print("[fatal] failed to obtain access token via refresh", file=sys.stderr)
        return 2

    pid = (CFG.get("xyz_pid") or "").strip() or search_pid(CFG["name"])
    print(f"[search] using pid={pid}")
    raw = fetch_all(pid)
    slim_eps = [slim(e) for e in raw]

    (OUT_DIR / "episodes_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "episodes.json").write_text(
        json.dumps(slim_eps, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] total={len(slim_eps)} -> {OUT_DIR/'episodes.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
