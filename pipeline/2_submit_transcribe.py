#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步骤2：把节目单每一集提交到 VideoTranscriptAPI 做"分说话人转录"，收集 view url。
  data/<key>/episodes/episodes.json  ->  data/<key>/episodes/view_urls.{json,txt}

设计：
- 直接提交小宇宙原始链接(episode_url)，由 VideoTranscriptAPI 自行下载，无需本地下音频。
- 有界并发(默认2，匹配后端并发能力)，轮询到终态再补位 —— 不打爆后端（后端转录是低并发的，
  突发提交会触发 300s 接收超时雪崩，故必须控速）。
- 断点续跑：state 记录每集状态，已 success 的跳过。
- 敏感信息走环境变量：TRANSCRIBE_API_BASE、TRANSCRIBE_TOKEN（Bearer）。

用法：  PODCAST=feihua python pipeline/2_submit_transcribe.py
可调环境变量：CONCURRENCY/POLL_INTERVAL/POLL_TIMEOUT/MAX_RETRY/LIMIT
"""
import json
import os
import time
import urllib.request
import urllib.error

import _common as C

C.load_dotenv()
CFG = C.load_config()
KEY = CFG["key"]
DD = C.ensure_dirs(KEY)
EPISODES = DD / "episodes" / "episodes.json"
VIEW_JSON = DD / "episodes" / "view_urls.json"
VIEW_TXT = DD / "episodes" / "view_urls.txt"
STATE = DD / "state" / "submit_state.json"

API_BASE = os.environ.get("TRANSCRIBE_API_BASE", "").rstrip("/")
TOKEN = os.environ.get("TRANSCRIBE_TOKEN", "")
VIEW_BASE = (os.environ.get("VIEW_API_BASE") or API_BASE).rstrip("/")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "2"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "15"))
POLL_TIMEOUT = float(os.environ.get("POLL_TIMEOUT", "1800"))
MAX_RETRY = int(os.environ.get("MAX_RETRY", "2"))
LIMIT = int(os.environ.get("LIMIT", "0"))

TERMINAL_OK = {"success", "completed", "done"}
TERMINAL_BAD = {"failed", "error"}
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def api_post(path, body):
    req = urllib.request.Request(
        API_BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={**AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, f"ERR {e!r}"


def api_status(task_id):
    req = urllib.request.Request(API_BASE + f"/api/task/{task_id}", headers=AUTH)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
            return d.get("data", d).get("status", "?")
    except Exception:
        return "poll_err"


def load(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default
    return default


def save_state(state):
    tmp = str(STATE) + ".tmp"
    json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def submit(ep):
    """提交一集。注意：API 返回 HTTP 200，业务码在 body.code（200/202 为受理）。"""
    code, payload = api_post("/api/transcribe", {
        "url": ep["episode_url"], "use_speaker_recognition": True})
    biz = payload.get("code") if isinstance(payload, dict) else None
    if (isinstance(payload, dict) and biz in (200, 202)
            and payload.get("data", {}).get("view_token")):
        d = payload["data"]
        return d["task_id"], d["view_token"]
    print(f"    submit not accepted: http={code} biz={biz}")
    return None


def write_outputs(state):
    ok = [v for v in state.values() if v.get("status") == "success"]
    ok.sort(key=lambda x: x.get("pubDate", ""))
    json.dump(ok, open(VIEW_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    with open(VIEW_TXT, "w", encoding="utf-8") as f:
        for v in ok:
            f.write(f"{v.get('view_url','')}\t{v.get('title','')}\n")


def main():
    if not API_BASE or not TOKEN:
        raise SystemExit("[fatal] set TRANSCRIBE_API_BASE and TRANSCRIBE_TOKEN (.env)")
    eps = sorted(json.load(open(EPISODES, encoding="utf-8")),
                 key=lambda x: x.get("pubDate", ""))
    if LIMIT:
        eps = eps[:LIMIT]
    state = load(STATE, {})
    pending = [ep for ep in eps if state.get(ep["eid"], {}).get("status") != "success"]
    print(f"[init] podcast={KEY} concurrency={CONCURRENCY} pending={len(pending)} "
          f"already_success={len(eps) - len(pending)}")

    inflight = {}
    pi = 0

    def start_next():
        nonlocal pi
        while pi < len(pending) and len(inflight) < CONCURRENCY:
            ep = pending[pi]
            pi += 1
            res = submit(ep)
            if not res:
                time.sleep(10)
                pi -= 1
                return
            tid, vt = res
            inflight[tid] = {"ep": ep, "view_token": vt, "started": time.time(), "attempts": 1}
            print(f"[start] {ep.get('title','')[:30]} task={tid[:12]} (inflight={len(inflight)})")

    start_next()
    while inflight or pi < len(pending):
        time.sleep(POLL_INTERVAL)
        for tid in list(inflight.keys()):
            info = inflight[tid]
            ep = info["ep"]
            eid = ep["eid"]
            st = api_status(tid)
            done = None
            if st in TERMINAL_OK:
                done = "success"
            elif st in TERMINAL_BAD or (time.time() - info["started"]) > POLL_TIMEOUT:
                if info["attempts"] <= MAX_RETRY:
                    print(f"[retry] {ep.get('title','')[:26]} (was {st}, attempt {info['attempts']})")
                    del inflight[tid]
                    res = submit(ep)
                    if res:
                        ntid, nvt = res
                        inflight[ntid] = {"ep": ep, "view_token": nvt,
                                          "started": time.time(), "attempts": info["attempts"] + 1}
                    continue
                done = "failed"
            if done:
                vt = info["view_token"]
                state[eid] = {
                    "status": done, "task_id": tid, "view_token": vt,
                    "view_url": f"{VIEW_BASE}/view/{vt}", "attempts": info["attempts"],
                    "title": ep.get("title", ""), "pubDate": ep.get("pubDate", ""), "eid": eid}
                del inflight[tid]
                save_state(state)
                write_outputs(state)
                n_ok = sum(1 for v in state.values() if v.get("status") == "success")
                n_bad = sum(1 for v in state.values() if v.get("status") == "failed")
                print(f"[{done}] {ep.get('title','')[:30]} (ok={n_ok} failed={n_bad} inflight={len(inflight)})")
        start_next()

    n_ok = sum(1 for v in state.values() if v.get("status") == "success")
    n_bad = sum(1 for v in state.values() if v.get("status") == "failed")
    print(f"[done] success={n_ok} failed={n_bad} -> {VIEW_JSON}")


if __name__ == "__main__":
    main()
