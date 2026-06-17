#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""podcast-insights 流水线共享工具：配置加载 + 数据目录解析 + .env 读取。

多播客设计：每个播客一份 config/<key>.json，数据落在 data/<key>/ 下。
默认处理 PODCAST 环境变量指定的播客（缺省 feihua）。
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_ROOT = PROJECT_ROOT / "data"


def load_dotenv() -> None:
    """加载项目根的 .env（优先 python-dotenv，缺失则极简解析）。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv as _load  # type: ignore
        _load(env_path)
        return
    except Exception:
        pass
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def podcast_key() -> str:
    return os.environ.get("PODCAST", "feihua").strip()


def load_config(key: str | None = None) -> dict:
    key = key or podcast_key()
    path = CONFIG_DIR / f"{key}.json"
    if not path.exists():
        raise SystemExit(f"[config] not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def data_dir(key: str | None = None) -> Path:
    return DATA_ROOT / (key or podcast_key())


def ensure_dirs(key: str | None = None) -> Path:
    d = data_dir(key)
    for sub in ("episodes", "transcripts", "extracted", "state"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d
