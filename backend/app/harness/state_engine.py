"""
持续心理状态引擎（DB 持久化版）
- 状态存储在 conversation_states 表，进程重启 / --reload 不丢失
- bootstrap 只在该会话×角色首次出现时从档案初始化，之后只做增量补全，
  不再覆盖上一轮 update_after_analysis 的演化结果
- update_after_analysis 直接消费 chat_analysis 的结构化 JSON，不再正则解析标签串
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from sqlalchemy.orm import Session

from ..models.sql_models import ConversationState

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
    bootstrapped: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PsychologicalState":
        data = data or {}
        state = cls()
        for key in (
            "current_goal", "defense_style", "last_intent",
            "last_strategy", "consistency_note",
        ):
            if isinstance(data.get(key), str) and data[key]:
                setattr(state, key, data[key])
        if isinstance(data.get("emotion_vector"), dict):
            state.emotion_vector = {**DEFAULT_EMOTIONS, **{
                k: float(v) for k, v in data["emotion_vector"].items()
                if isinstance(v, (int, float))
            }}
        if isinstance(data.get("beliefs"), dict):
            state.beliefs = {str(k): str(v) for k, v in data["beliefs"].items()}
        if isinstance(data.get("relationship_weights"), dict):
            state.relationship_weights = {
                str(k): float(v) for k, v in data["relationship_weights"].items()
                if isinstance(v, (int, float))
            }
        if isinstance(data.get("stable_traits"), list):
            state.stable_traits = [str(item) for item in data["stable_traits"] if item][:8]
        if isinstance(data.get("behavior_patterns"), list):
            state.behavior_patterns = [str(item) for item in data["behavior_patterns"] if item][:8]
        state.bootstrapped = bool(data.get("bootstrapped"))
        return state


class PsychologicalStateEngine:
    """读写均走 DB；同一请求内通过传入同一个 Session 保证一致性"""

    def _get_row(self, db: Session, conversation_id: int, character_name: str) -> ConversationState | None:
        return db.query(ConversationState).filter(
            ConversationState.conversation_id == conversation_id,
            ConversationState.character_name == character_name,
        ).first()

    def get_state(self, db: Session, conversation_id: int, character_name: str) -> PsychologicalState:
        row = self._get_row(db, conversation_id, character_name)
        return PsychologicalState.from_dict(row.state_json if row else None)

    def save_state(self, db: Session, conversation_id: int, character_name: str, state: PsychologicalState) -> None:
        row = self._get_row(db, conversation_id, character_name)
        payload = asdict(state)
        if row:
            row.state_json = payload
        else:
            row = ConversationState(
                conversation_id=conversation_id,
                character_name=character_name,
                state_json=payload,
            )
            db.add(row)
        db.flush()

    def bootstrap_state(
        self,
        db: Session,
        conversation_id: int,
        character_name: str,
        character_profile: dict[str, Any] | None = None,
        relationship_snapshot: dict[str, Any] | None = None,
        observations: list[str] | None = None,
    ) -> PsychologicalState:
        state = self.get_state(db, conversation_id, character_name)
        profile = character_profile or {}

        if not state.bootstrapped:
            # 首次：从档案完整初始化
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
            state.bootstrapped = True
        else:
            # 后续：只补空缺，不覆盖演化结果
            if not state.stable_traits:
                state.stable_traits = [tag for tag in profile.get("personality_tags", []) if tag][:6]
            if not state.behavior_patterns and observations:
                state.behavior_patterns = [item for item in observations if item][:6]

        self.save_state(db, conversation_id, character_name, state)
        return state

    def update_after_analysis(
        self,
        db: Session,
        conversation_id: int,
        speaker_name: str,
        listener_name: str,
        analysis_result: dict[str, Any],
    ) -> None:
        """消费结构化分析结果，演化双方状态（EMA 平滑，避免单轮剧烈跳变）"""
        listener_state = self.get_state(db, conversation_id, listener_name)
        speaker_state = self.get_state(db, conversation_id, speaker_name)

        emotions = analysis_result.get("emotions") or {}

        def _score(key: str) -> float | None:
            item = emotions.get(key) or {}
            value = item.get("score")
            if isinstance(value, (int, float)):
                return float(value)
            return None

        def _blend(old: float, target: float, weight: float = 0.5) -> float:
            return max(0.0, min(1.0, old * (1 - weight) + target * weight))

        surface = _score("surface")
        deep = _score("deep")
        suppressed = _score("suppressed")
        intended = _score("intended")

        if surface is not None:
            listener_state.emotion_vector["calm"] = _blend(
                listener_state.emotion_vector.get("calm", 0.5), 1.0 - surface / 10)
        if deep is not None:
            listener_state.emotion_vector["guarded"] = _blend(
                listener_state.emotion_vector.get("guarded", 0.4), deep / 10)
        if suppressed is not None:
            listener_state.emotion_vector["anger"] = _blend(
                listener_state.emotion_vector.get("anger", 0.2), suppressed / 10)
        if intended is not None:
            listener_state.relationship_weights["pressure"] = _blend(
                listener_state.relationship_weights.get("pressure", 0.0), intended / 10)

        strategy = analysis_result.get("strategy") or {}
        speaker_state.last_intent = str(strategy.get("short_term") or speaker_state.last_intent)
        speaker_state.last_strategy = str(strategy.get("long_term") or speaker_state.last_strategy)
        listener_state.consistency_note = str(strategy.get("consistency_note") or listener_state.consistency_note)

        tags = analysis_result.get("tags") or {}
        relation_tag = str(tags.get("relation") or "").strip()
        if relation_tag:
            listener_state.beliefs[speaker_name] = relation_tag

        self.save_state(db, conversation_id, listener_name, listener_state)
        self.save_state(db, conversation_id, speaker_name, speaker_state)

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


state_engine = PsychologicalStateEngine()
