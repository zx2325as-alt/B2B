"""
chat_analysis 结构化协议
- LLM 输出原生嵌套 JSON（emotions/strategy/tags 等），不再要求中文标签拼接串
- normalize_chat_analysis：校验数值范围 + 派生 legacy 展示字段（emotion_label/subtext 等），
  保证旧前端展示与历史数据消费逻辑兼容
- extract_emotion_struct：统一读取入口——新消息读 analysis_json，老消息回退正则解析
"""
from __future__ import annotations

import re
from typing import Any

EMOTION_KEYS = ("intended", "surface", "deep", "suppressed")
EMOTION_LABELS_CN = {
    "intended": "试图激发",
    "surface": "表层",
    "deep": "深层",
    "suppressed": "压抑",
}


def _clamp_score(value: Any, low: int = 0, high: int = 10) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_chat_analysis(result: dict[str, Any]) -> dict[str, Any]:
    """
    输入：guardrails 校验后的结构化分析结果
    输出：补全数值边界 + 派生 legacy 字段后的完整结果（可直接入库/推给前端）
    """
    normalized = dict(result or {})

    emotions_raw = normalized.get("emotions") or {}
    emotions: dict[str, dict[str, Any]] = {}
    for key in EMOTION_KEYS:
        item = emotions_raw.get(key) or {}
        if not isinstance(item, dict):
            item = {}
        emotions[key] = {
            "label": _clean_text(item.get("label")),
            "score": _clamp_score(item.get("score")),
        }
    normalized["emotions"] = emotions

    monologue_raw = normalized.get("inner_monologue") or {}
    if not isinstance(monologue_raw, dict):
        monologue_raw = {"first_reaction": _clean_text(monologue_raw), "defense": "", "tendency": ""}
    monologue = {
        "first_reaction": _clean_text(monologue_raw.get("first_reaction")),
        "defense": _clean_text(monologue_raw.get("defense")),
        "tendency": _clean_text(monologue_raw.get("tendency")),
    }
    normalized["inner_monologue"] = monologue

    strategy_raw = normalized.get("strategy") or {}
    if not isinstance(strategy_raw, dict):
        strategy_raw = {}
    strategy = {
        "short_term": _clean_text(strategy_raw.get("short_term")),
        "long_term": _clean_text(strategy_raw.get("long_term")),
        "consistency_note": _clean_text(strategy_raw.get("consistency_note")),
    }
    normalized["strategy"] = strategy

    tags_raw = normalized.get("tags") or {}
    if not isinstance(tags_raw, dict):
        tags_raw = {}
    tags = {
        "primary": _clean_text(tags_raw.get("primary")),
        "secondary": _clean_text(tags_raw.get("secondary")),
        "relation": _clean_text(tags_raw.get("relation")),
    }
    normalized["tags"] = tags

    normalized["reply"] = _clean_text(normalized.get("reply"))

    # ── 派生 legacy 展示字段（兼容旧前端与历史消费逻辑） ──
    normalized["emotion_label"] = "｜".join(
        f"{EMOTION_LABELS_CN[key]}:{emotions[key]['label'] or '无'}({emotions[key]['score']})"
        for key in EMOTION_KEYS
    )
    normalized["emotion_score"] = round(emotions["deep"]["score"] / 10, 2)
    normalized["inner_monologue_text"] = "\n".join(
        part for part in [
            f"第一反应：{monologue['first_reaction']}" if monologue["first_reaction"] else "",
            f"防御机制：{monologue['defense']}" if monologue["defense"] else "",
            f"行为倾向：{monologue['tendency']}" if monologue["tendency"] else "",
        ] if part
    )
    normalized["subtext"] = "\n".join(
        part for part in [
            f"短期策略：{strategy['short_term']}" if strategy["short_term"] else "",
            f"长期策略：{strategy['long_term']}" if strategy["long_term"] else "",
            f"一致性说明：{strategy['consistency_note']}" if strategy["consistency_note"] else "",
        ] if part
    )
    normalized["psychological_tag"] = "|".join(
        part for part in [
            f"主:{tags['primary']}" if tags["primary"] else "",
            f"次:{tags['secondary']}" if tags["secondary"] else "",
            f"关系:{tags['relation']}" if tags["relation"] else "",
        ] if part
    )
    return normalized


# ─── legacy 解析（仅用于无 analysis_json 的历史消息） ─────────────────────────

_LEGACY_EMOTION_PATTERNS = {
    "intended": r"试图激发[:：]\s*([^\(\)\]\[｜|]+)\((\d+)\)",
    "surface": r"表层[:：]\s*([^\(\)\]\[｜|]+)\((\d+)\)",
    "deep": r"深层[:：]\s*([^\(\)\]\[｜|]+)\((\d+)\)",
    "suppressed": r"压抑[:：]\s*([^\(\)\]\[｜|]+)\((\d+)\)",
}


def parse_legacy_emotion_label(label: str | None) -> dict[str, dict[str, Any]]:
    result = {key: {"label": "", "score": 0} for key in EMOTION_KEYS}
    if not label:
        return result
    for key, pattern in _LEGACY_EMOTION_PATTERNS.items():
        matched = re.search(pattern, label)
        if matched:
            result[key] = {"label": matched.group(1).strip(), "score": int(matched.group(2))}
    return result


def parse_legacy_strategy_text(strategy_text: str | None) -> dict[str, str]:
    lines = [line.strip() for line in (strategy_text or "").splitlines() if line.strip()]

    def _pick(prefix: str) -> str:
        return next((line.replace(prefix, "", 1).strip() for line in lines if line.startswith(prefix)), "")

    return {
        "short_term": _pick("短期策略："),
        "long_term": _pick("长期策略："),
        "consistency_note": _pick("一致性说明："),
    }


def extract_emotion_struct(analysis_json: dict[str, Any] | None, legacy_label: str | None) -> dict[str, dict[str, Any]]:
    """统一读取情绪结构：优先 analysis_json，老数据回退正则"""
    if analysis_json and isinstance(analysis_json.get("emotions"), dict):
        emotions = analysis_json["emotions"]
        return {
            key: {
                "label": _clean_text((emotions.get(key) or {}).get("label")),
                "score": _clamp_score((emotions.get(key) or {}).get("score")),
            }
            for key in EMOTION_KEYS
        }
    return parse_legacy_emotion_label(legacy_label)


def extract_strategy_struct(analysis_json: dict[str, Any] | None, legacy_subtext: str | None) -> dict[str, str]:
    """统一读取策略结构：优先 analysis_json，老数据回退文本解析"""
    if analysis_json and isinstance(analysis_json.get("strategy"), dict):
        strategy = analysis_json["strategy"]
        return {
            "short_term": _clean_text(strategy.get("short_term")),
            "long_term": _clean_text(strategy.get("long_term")),
            "consistency_note": _clean_text(strategy.get("consistency_note")),
        }
    return parse_legacy_strategy_text(legacy_subtext)
