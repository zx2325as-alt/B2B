"""
人物档案统一模板与合并策略（唯一权威）
- 新建 / 编辑 / 导入 / AI 建议四条链路共用同一套字段定义与合并规则
- 合并策略：
  - personality_tags：并集（上限 12）
  - core_traits（大五）：已有值与新值 EMA 融合，缺失维度直接补
  - 文本字段：空则填，非空时由调用方决定（导入融合模式下 AI 已合并旧档案，可直接深化覆盖）
- 完整度评分：量化"档案丰满程度"，驱动"逐渐完善"的可见反馈
"""
from __future__ import annotations

import re
from typing import Any

BIG_FIVE_KEYS = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]

# 档案文本字段：(字段名, 所属模块)
PROFILE_TEXT_FIELDS: list[tuple[str, str]] = [
    ("role", "基础信息"),
    ("background", "基础信息"),
    ("motivation", "核心动机"),
    ("weakness", "核心弱点"),
    ("speaking_style", "说话风格"),
]

MAX_TAGS = 12


def merge_tags(old_tags: list | None, new_tags: list | None, cap: int = MAX_TAGS) -> list[str]:
    """标签并集合并：保持原有顺序，新标签追加，去重去空"""
    merged: list[str] = []
    for tag in list(old_tags or []) + list(new_tags or []):
        text = str(tag).strip()
        if text and text not in merged:
            merged.append(text)
    return merged[:cap]


_SENTENCE_SPLIT = re.compile(r"[。！？；;\n]+")

# 扩展人物模型维度：{维度名: (中文名, 条目类型)}
# list[str] / list[dict] 维度按内容去重追加；dict 维度按键填充更新
EXTENDED_DIMENSIONS: dict[str, str] = {
    "values": "价值观",
    "desires": "欲望层次",
    "fears": "恐惧",
    "interpersonal_patterns": "人际模式",
    "key_experiences": "关键经历",
    "speech_fingerprint": "语言指纹",
    "contradictions": "矛盾性",
    "self_image_vs_public": "自我认知与外部印象",
}

_LIST_DIMENSIONS = {"values", "desires", "fears", "interpersonal_patterns", "key_experiences", "contradictions"}
_DICT_DIMENSIONS = {"speech_fingerprint", "self_image_vs_public"}
_MAX_ITEMS_PER_DIMENSION = 10


def _entry_key(entry: Any) -> str:
    """条目去重键：字符串直接用，dict 取主要内容字段拼接"""
    if isinstance(entry, str):
        return re.sub(r"\s", "", entry)[:60]
    if isinstance(entry, dict):
        joined = "|".join(str(entry.get(k, "")) for k in sorted(entry.keys()))
        return re.sub(r"\s", "", joined)[:80]
    return str(entry)[:60]


def merge_extended_profile(old_profile: dict | None, new_profile: dict | None) -> tuple[dict, int]:
    """
    扩展档案合并（只增不减）：
    - 列表维度：按内容去重追加，每维度上限 10 条
    - 字典维度：空键填充、非空键有更长内容时更新
    返回 (合并结果, 新增条目数)
    """
    old = dict(old_profile or {})
    new = new_profile or {}
    added = 0
    for dim in _LIST_DIMENSIONS:
        new_items = new.get(dim)
        if not isinstance(new_items, list):
            continue
        existing = list(old.get(dim) or []) if isinstance(old.get(dim), list) else []
        seen = {_entry_key(item) for item in existing}
        for item in new_items:
            key = _entry_key(item)
            if not key or key in seen:
                continue
            if len(existing) >= _MAX_ITEMS_PER_DIMENSION:
                break
            existing.append(item)
            seen.add(key)
            added += 1
        old[dim] = existing
    for dim in _DICT_DIMENSIONS:
        new_value = new.get(dim)
        if not isinstance(new_value, dict):
            continue
        existing = dict(old.get(dim) or {}) if isinstance(old.get(dim), dict) else {}
        for key, value in new_value.items():
            if value in (None, "", [], {}):
                continue
            current = existing.get(key)
            if current in (None, "", [], {}):
                existing[key] = value
                added += 1
            elif isinstance(value, list) and isinstance(current, list):
                for item in value:
                    if item not in current:
                        current.append(item)
                        added += 1
                existing[key] = current[:_MAX_ITEMS_PER_DIMENSION]
            elif isinstance(value, str) and isinstance(current, str) and len(value) > len(current):
                existing[key] = value
        old[dim] = existing
    return old, added


def render_extended_profile(profile_json: dict | None, limit_per_dim: int = 5) -> str:
    """把扩展档案渲染为可注入 prompt 的文本块（对话上下文用）"""
    profile = profile_json or {}
    lines: list[str] = []

    def _entry_text(entry: Any) -> str:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return "；".join(f"{k}:{v}" for k, v in entry.items() if v)
        return str(entry)

    for dim, label in EXTENDED_DIMENSIONS.items():
        value = profile.get(dim)
        if isinstance(value, list) and value:
            items = "；".join(_entry_text(item) for item in value[:limit_per_dim])
            lines.append(f"- {label}：{items}")
        elif isinstance(value, dict) and any(v for v in value.values()):
            lines.append(f"- {label}：{_entry_text(value)}")
    return "\n".join(lines)


def merge_background(old_text: str | None, new_text: str | None, cap: int = 320) -> str:
    """
    背景故事确定性积累（服务器端保障，不依赖 AI 自觉保留旧事实）：
    - 旧内容一字不丢
    - 新内容按句切分，仅追加旧文中不存在的新句子
    - 即使 AI 融合输出丢掉了旧事实，数据也不会丢
    """
    old_text = (old_text or "").strip()
    new_text = (new_text or "").strip()
    if not old_text:
        return new_text[:cap]
    if not new_text or new_text == old_text:
        return old_text[:cap]

    merged = old_text.rstrip("。")
    old_compact = re.sub(r"\s", "", old_text)
    for sentence in _SENTENCE_SPLIT.split(new_text):
        sentence = sentence.strip().strip("，,")
        if len(sentence) < 4:
            continue
        compact = re.sub(r"\s", "", sentence)
        # 新句子已包含在旧文中（或其开头片段已出现，视为同一事实的变体）则跳过
        if compact in old_compact:
            continue
        if len(compact) >= 8 and compact[:8] in old_compact:
            continue
        if len(merged) + len(sentence) + 2 > cap:
            break
        merged = f"{merged}。{sentence}"
        old_compact += compact
    return (merged + "。")[:cap]


def blend_traits(old_traits: dict | None, new_traits: dict | None, new_weight: float = 0.4) -> dict[str, float]:
    """大五人格融合：双方都有取 EMA（避免单次导入剧烈改写人格），单方有则直接采用"""
    old = old_traits if isinstance(old_traits, dict) else {}
    new = new_traits if isinstance(new_traits, dict) else {}
    merged: dict[str, float] = {}
    for key in BIG_FIVE_KEYS:
        old_value = old.get(key)
        new_value = new.get(key)
        old_ok = isinstance(old_value, (int, float))
        new_ok = isinstance(new_value, (int, float))
        if old_ok and new_ok:
            merged[key] = round(max(0.0, min(1.0, float(old_value) * (1 - new_weight) + float(new_value) * new_weight)), 2)
        elif new_ok:
            merged[key] = round(max(0.0, min(1.0, float(new_value))), 2)
        elif old_ok:
            merged[key] = round(max(0.0, min(1.0, float(old_value))), 2)
    return merged


# 完整度权重（合计 100）
_COMPLETENESS_WEIGHTS = {
    "role": 8,
    "background": 12,
    "personality_tags": 12,
    "core_traits": 10,
    "motivation": 12,
    "weakness": 12,
    "speaking_style": 10,
    "behavior_patterns": 10,
    "relationships": 7,
    "events": 7,
}

_MODULE_LABELS = {
    "role": "角色定位",
    "background": "背景故事",
    "personality_tags": "人格标签",
    "core_traits": "大五人格",
    "motivation": "核心动机",
    "weakness": "核心弱点",
    "speaking_style": "说话风格",
    "behavior_patterns": "行为模式",
    "relationships": "关系网络",
    "events": "事件时间线",
}


def _text_grade(value: str, full_at: int) -> float:
    """文本字段质量分级：达到 full_at 字数算充实(1.0)，有内容但偏短算半分(0.5)"""
    length = len((value or "").strip())
    if length == 0:
        return 0.0
    if length >= full_at:
        return 1.0
    return 0.5


def _count_grade(count: int, full_at: int) -> float:
    if count <= 0:
        return 0.0
    if count >= full_at:
        return 1.0
    return 0.5


def profile_completeness(
    char: Any,
    behavior_pattern_count: int = 0,
    relationship_count: int = 0,
    event_count: int = 0,
) -> dict[str, Any]:
    """
    计算档案完整度：score 0-100 + 缺失/偏薄模块清单。
    不只看"有没有"，还看"是否充实"：内容偏短的字段只得一半权重。
    """
    grades: dict[str, float] = {
        "role": _text_grade(getattr(char, "role", ""), 4),
        "background": _text_grade(getattr(char, "background", ""), 40),
        "personality_tags": _count_grade(len(getattr(char, "personality_tags", None) or []), 3),
        "core_traits": 1.0 if all(
            isinstance((getattr(char, "core_traits", None) or {}).get(key), (int, float))
            for key in BIG_FIVE_KEYS
        ) else 0.0,
        "motivation": _text_grade(getattr(char, "motivation", ""), 10),
        "weakness": _text_grade(getattr(char, "weakness", ""), 10),
        "speaking_style": _text_grade(getattr(char, "speaking_style", ""), 8),
        "behavior_patterns": _count_grade(behavior_pattern_count, 2),
        "relationships": _count_grade(relationship_count, 1),
        "events": _count_grade(event_count, 2),
    }
    score = round(sum(_COMPLETENESS_WEIGHTS[key] * grade for key, grade in grades.items()))
    missing = [_MODULE_LABELS[key] for key, grade in grades.items() if grade == 0.0]
    thin = [_MODULE_LABELS[key] for key, grade in grades.items() if grade == 0.5]
    return {
        "score": score,
        "missing": missing,
        "thin": thin,
        "filled_count": sum(1 for grade in grades.values() if grade > 0),
        "total_count": len(grades),
    }
