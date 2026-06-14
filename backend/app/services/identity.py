"""
角色同一性服务
- find_character_by_name：按"本名 → 别名"顺序命中，解决"张三/张总/老张"分裂成多个角色的问题
- add_alias：记录别名（导入映射改名时自动调用）
- merge_characters：把一个角色完整并入另一个角色（数据重指 + 档案互补 + 关系归并），
  用于补救已经发生的角色分裂
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character,
    CharacterEvent,
    CharacterObservation,
    ConversationState,
    EvidenceSpan,
    MemoryItem,
    Message,
    PersonalitySnapshot,
    Relationship,
    RetrievalTrace,
    StructuredDiagnosis,
    TraitHypothesis,
)
from .profiles import merge_extended_profile, merge_tags
from .relationships import merge_duplicate_relationships

logger = logging.getLogger(__name__)

MAX_ALIASES = 12


def find_character_by_name(db: Session, name: str) -> Character | None:
    """按名字解析角色：精确本名优先，其次别名命中（个人库角色量级，全量扫描可接受）"""
    name = (name or "").strip()
    if not name:
        return None
    char = db.query(Character).filter(Character.name == name).first()
    if char:
        return char
    for candidate in db.query(Character).all():
        if name in (candidate.aliases or []):
            return candidate
    return None


def add_alias(char: Character, alias: str) -> bool:
    """给角色追加别名；与本名相同或已存在时跳过。返回是否实际新增。"""
    alias = (alias or "").strip()
    if not alias or alias == char.name:
        return False
    aliases = list(char.aliases or [])
    if alias in aliases:
        return False
    aliases.append(alias)
    char.aliases = aliases[:MAX_ALIASES]
    return True


# 合并时档案互补的文本字段
_FILL_FIELDS = ("role", "background", "motivation", "weakness", "speaking_style")


def merge_characters(db: Session, target: Character, source: Character) -> dict:
    """
    把 source 完整并入 target 并删除 source：
    - 全部关联数据（事件/观察/证据/记忆/快照/消息/诊断/检索/会话状态）重指到 target
    - 关系重指后去重（自指删除、与 target 已有关系按无向规则合并）
    - 档案互补：target 空缺字段取 source；标签并集；大五只补缺失维度
    - source 本名与别名全部记为 target 的别名
    """
    if target.id == source.id:
        raise ValueError("不能将角色与自身合并")

    stats = {"events": 0, "observations": 0, "evidence": 0, "memories": 0, "snapshots": 0, "relationships": 0}

    # ── 关联数据重指 ──
    stats["events"] = db.query(CharacterEvent).filter(CharacterEvent.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)
    stats["observations"] = db.query(CharacterObservation).filter(CharacterObservation.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)
    stats["evidence"] = db.query(EvidenceSpan).filter(EvidenceSpan.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)
    stats["memories"] = db.query(MemoryItem).filter(MemoryItem.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)
    stats["snapshots"] = db.query(PersonalitySnapshot).filter(PersonalitySnapshot.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)
    db.query(Message).filter(Message.character_id == source.id).update(
        {"character_id": target.id, "character_name": target.name}, synchronize_session=False)
    db.query(Message).filter(Message.receiver_id == source.id).update(
        {"receiver_id": target.id, "receiver_name": target.name}, synchronize_session=False)
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.speaker_id == source.id).update(
        {"speaker_id": target.id}, synchronize_session=False)
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.listener_id == source.id).update(
        {"listener_id": target.id}, synchronize_session=False)
    db.query(RetrievalTrace).filter(RetrievalTrace.speaker_id == source.id).update(
        {"speaker_id": target.id}, synchronize_session=False)
    db.query(RetrievalTrace).filter(RetrievalTrace.listener_id == source.id).update(
        {"listener_id": target.id}, synchronize_session=False)
    db.query(ConversationState).filter(ConversationState.character_name == source.name).update(
        {"character_name": target.name}, synchronize_session=False)
    db.query(TraitHypothesis).filter(TraitHypothesis.character_id == source.id).update(
        {"character_id": target.id}, synchronize_session=False)

    # ── 关系重指 + 去重 ──
    db.query(Relationship).filter(Relationship.source_id == source.id).update(
        {"source_id": target.id}, synchronize_session=False)
    db.query(Relationship).filter(Relationship.target_id == source.id).update(
        {"target_id": target.id}, synchronize_session=False)
    db.flush()
    # 自指关系（原 source↔target 之间的关系重指后变成 target↔target）删除
    self_rels = db.query(Relationship).filter(
        Relationship.source_id == target.id,
        Relationship.target_id == target.id,
    ).all()
    for rel in self_rels:
        db.query(EvidenceSpan).filter(EvidenceSpan.relationship_id == rel.id).update(
            {"relationship_id": None}, synchronize_session=False)
        db.delete(rel)
    db.flush()
    stats["relationships"] = merge_duplicate_relationships(db)

    # ── 档案互补 ──
    for field in _FILL_FIELDS:
        if not (getattr(target, field, "") or "").strip() and (getattr(source, field, "") or "").strip():
            setattr(target, field, getattr(source, field))
    if target.age is None and source.age is not None:
        target.age = source.age
    target.personality_tags = merge_tags(target.personality_tags, source.personality_tags)
    merged_traits = dict(target.core_traits or {})
    for key, value in (source.core_traits or {}).items():
        if isinstance(value, (int, float)) and not isinstance(merged_traits.get(key), (int, float)):
            merged_traits[key] = value
    target.core_traits = merged_traits
    # 扩展人物模型同样并集合并
    merged_extended, _ = merge_extended_profile(target.profile_json, source.profile_json)
    target.profile_json = merged_extended

    # ── 身份归并：source 的本名与别名全部成为 target 的别名 ──
    add_alias(target, source.name)
    for alias in source.aliases or []:
        add_alias(target, alias)

    target.version += 1
    target.updated_at = datetime.utcnow()
    db.delete(source)
    db.flush()
    logger.warning("角色合并完成：%s(id=%s) 已并入 %s(id=%s) %s", source.name, source.id, target.name, target.id, stats)
    return stats
