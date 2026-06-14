"""
统一配置加载器
- config.yaml：基础配置（入库，不含密钥）
- config.local.yaml：本地覆盖（gitignore，存放 API Key 等敏感信息）
- 带 mtime 缓存：文件不变不重复解析，文件变更后无需重启即可生效
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

CONF_DIR = Path(__file__).parent.parent / "conf"
CONFIG_FILE = CONF_DIR / "config.yaml"
LOCAL_CONFIG_FILE = CONF_DIR / "config.local.yaml"

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "data": {},
    "base_mtime": None,
    "local_mtime": None,
}


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_config() -> dict[str, Any]:
    base_mtime = _mtime(CONFIG_FILE)
    local_mtime = _mtime(LOCAL_CONFIG_FILE)
    with _lock:
        if (
            _cache["data"]
            and _cache["base_mtime"] == base_mtime
            and _cache["local_mtime"] == local_mtime
        ):
            return _cache["data"]
        data = _deep_merge(_read_yaml(CONFIG_FILE), _read_yaml(LOCAL_CONFIG_FILE))
        _cache["data"] = data
        _cache["base_mtime"] = base_mtime
        _cache["local_mtime"] = local_mtime
        return data


def get_ai_config() -> dict[str, Any]:
    return get_config().get("ai", {}) or {}


def get_graph_config() -> dict[str, Any]:
    return get_config().get("graph", {}) or {}


def get_task_timeout(task_name: str, default: float = 120.0) -> float:
    timeouts = get_ai_config().get("task_timeouts", {}) or {}
    try:
        return float(timeouts.get(task_name, timeouts.get("default", default)))
    except (TypeError, ValueError):
        return default
