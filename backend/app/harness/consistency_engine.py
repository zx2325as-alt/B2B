from typing import Any


def build_consistency_constraints(
    speaker_profile: dict[str, Any],
    listener_profile: dict[str, Any],
    relationship_snapshot: dict[str, Any],
    recent_dialogue: str,
) -> str:
    speaker_traits = "、".join(speaker_profile.get("personality_tags", []) or []) or "未知"
    listener_traits = "、".join(listener_profile.get("personality_tags", []) or []) or "未知"
    rel_type = relationship_snapshot.get("rel_type") or "未知"
    rel_strength = relationship_snapshot.get("strength", "未知")
    rel_sentiment = relationship_snapshot.get("sentiment", "未知")
    rel_desc = relationship_snapshot.get("description") or "暂无"

    return "\n".join(
        [
            "一致性约束器：",
            f"- 发言者人格约束：{speaker_traits}",
            f"- 接收方人格约束：{listener_traits}",
            f"- 当前关系：类型={rel_type}，强度={rel_strength}，情感极性={rel_sentiment}",
            f"- 关系描述：{rel_desc}",
            f"- 最近上下文：{recent_dialogue or '暂无'}",
            "- 若本轮判断与既有人格、行为模式或关系不一致，必须在“一致性说明”中解释为何反常。",
            "- 若信息不足，允许保守推断，但不得无依据强行戏剧化。",
        ]
    )
