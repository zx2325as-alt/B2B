from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_EMOTIONS = {
    "calm": 0.5,
    "guarded": 0.4,
    "attachment": 0.3,
    "fear": 0.2,
    "anger": 0.2,
}


@dataclass
class PsychologicalState:
    emotion_vector: dict[str, float] = field(default_factory=lambda: DEFAULT_EMOTIONS.copy())
    current_goal: str = "维持关系稳定并保护自身立场"
    beliefs: dict[str, str] = field(default_factory=dict)
    defense_style: str = "谨慎观察"
    relationship_weights: dict[str, float] = field(default_factory=dict)
    stable_traits: list[str] = field(default_factory=list)
    behavior_patterns: list[str] = field(default_factory=list)
    last_intent: str = ""
    last_strategy: str = ""
    consistency_note: str = ""


class PsychologicalStateEngine:
    def __init__(self):
        self._store: dict[int, dict[str, PsychologicalState]] = {}

    def get_state(self, conversation_id: int, character_name: str) -> PsychologicalState:
        conv_state = self._store.setdefault(conversation_id, {})
        return conv_state.setdefault(character_name, PsychologicalState())

    def bootstrap_state(
        self,
        conversation_id: int,
        character_name: str,
        character_profile: dict[str, Any] | None = None,
        relationship_snapshot: dict[str, Any] | None = None,
        observations: list[str] | None = None,
    ) -> PsychologicalState:
        state = self.get_state(conversation_id, character_name)
        profile = character_profile or {}
        state.stable_traits = [tag for tag in profile.get("personality_tags", []) if tag][:6]
        state.behavior_patterns = [item for item in (observations or []) if item][:6]
        state.current_goal = profile.get("motivation") or state.current_goal
        state.defense_style = profile.get("weakness") or state.defense_style
        if relationship_snapshot:
            for key in ("trust", "dependency", "dominance", "fear", "attraction"):
                if relationship_snapshot.get(key) is not None:
                    state.relationship_weights[key] = float(relationship_snapshot[key])
            belief_key = relationship_snapshot.get("target_name")
            belief_value = relationship_snapshot.get("belief")
            if belief_key and belief_value:
                state.beliefs[belief_key] = belief_value
        return state

    def update_after_analysis(
        self,
        conversation_id: int,
        speaker_name: str,
        listener_name: str,
        analysis_result: dict[str, Any],
    ) -> None:
        listener_state = self.get_state(conversation_id, listener_name)
        speaker_state = self.get_state(conversation_id, speaker_name)

        emotion_label = analysis_result.get("emotion_label", "")
        intended = self._extract_score(emotion_label, "试图激发")
        surface = self._extract_score(emotion_label, "表层")
        deep = self._extract_score(emotion_label, "深层")
        suppressed = self._extract_score(emotion_label, "压抑")

        if surface is not None:
            listener_state.emotion_vector["calm"] = max(0.0, 1.0 - surface / 10)
        if deep is not None:
            listener_state.emotion_vector["guarded"] = min(1.0, deep / 10)
        if suppressed is not None:
            listener_state.emotion_vector["anger"] = min(1.0, suppressed / 10)

        strategy_text = analysis_result.get("subtext", "")
        intent_line, strategy_line = self._split_strategy(strategy_text)
        speaker_state.last_intent = intent_line
        speaker_state.last_strategy = strategy_line
        listener_state.consistency_note = self._extract_consistency(strategy_text)

        tags = [tag.strip() for tag in (analysis_result.get("psychological_tag", "") or "").split("|") if tag.strip()]
        for tag in tags:
            if "关系" in tag or "信任" in tag:
                listener_state.beliefs[speaker_name] = tag
        if intended is not None:
            listener_state.relationship_weights["pressure"] = intended / 10

    def render_state_block(self, character_name: str, state: PsychologicalState) -> str:
        beliefs = "；".join(f"{name}:{value}" for name, value in state.beliefs.items()) or "暂无"
        relationships = "；".join(f"{key}:{round(value, 2)}" for key, value in state.relationship_weights.items()) or "暂无"
        traits = "、".join(state.stable_traits) or "暂无"
        patterns = "、".join(state.behavior_patterns) or "暂无"
        emotions = "；".join(f"{key}:{round(value, 2)}" for key, value in state.emotion_vector.items())
        return "\n".join(
            [
                f"角色心理状态：{character_name}",
                f"- 当前情绪向量：{emotions}",
                f"- 当前目标：{state.current_goal}",
                f"- 对他人信念：{beliefs}",
                f"- 防御机制：{state.defense_style}",
                f"- 关系权重：{relationships}",
                f"- 稳定人格：{traits}",
                f"- 行为模式：{patterns}",
                f"- 上一轮意图：{state.last_intent or '暂无'}",
                f"- 上一轮策略：{state.last_strategy or '暂无'}",
                f"- 一致性说明：{state.consistency_note or '暂无'}",
            ]
        )

    def _extract_score(self, label: str, prefix: str) -> int | None:
        if not label or prefix not in label:
            return None
        try:
            segment = label.split(prefix, 1)[1]
            number = segment.split("(", 1)[1].split(")", 1)[0]
            return int(number)
        except Exception:
            return None

    def _split_strategy(self, strategy_text: str) -> tuple[str, str]:
        lines = [line.strip() for line in strategy_text.splitlines() if line.strip()]
        short = next((line.replace("短期策略：", "").strip() for line in lines if line.startswith("短期策略：")), "")
        long = next((line.replace("长期策略：", "").strip() for line in lines if line.startswith("长期策略：")), "")
        return short, long

    def _extract_consistency(self, strategy_text: str) -> str:
        lines = [line.strip() for line in strategy_text.splitlines() if line.strip()]
        return next((line.replace("一致性说明：", "").strip() for line in lines if line.startswith("一致性说明：")), "")


state_engine = PsychologicalStateEngine()
