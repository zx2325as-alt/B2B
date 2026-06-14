"""
关系服务：两个人物之间只存一条关系（无向）
- find_pair_relationship：不论方向，返回这对人物的唯一关系行
- merge_duplicate_relationships：启动迁移——把历史遗留的 A→B / B→A 双行合并为一行，
  并把证据/交互单元上的引用重指到保留行
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.sql_models import EvidenceSpan, InteractionUnit, Relationship

logger = logging.getLogger(__name__)

_GENERIC_REL_TYPES = {None, "", "neutral", "dynamic", "unknown"}


def find_pair_relationship(db: Session, char_a_id: int | None, char_b_id: int | None) -> Relationship | None:
    """返回两个人物之间的唯一关系行（方向无关）"""
    if not char_a_id or not char_b_id or char_a_id == char_b_id:
        return None
    return db.query(Relationship).filter(
        or_(
            and_(Relationship.source_id == char_a_id, Relationship.target_id == char_b_id),
            and_(Relationship.source_id == char_b_id, Relationship.target_id == char_a_id),
        )
    ).order_by(Relationship.id).first()


def _merge_into(db: Session, keep: Relationship, dup: Relationship) -> None:
    keep.strength = round(max(0.0, min(1.0, ((keep.strength or 0.0) + (dup.strength or 0.0)) / 2)), 3)
    keep.sentiment = round(max(-1.0, min(1.0, ((keep.sentiment or 0.0) + (dup.sentiment or 0.0)) / 2)), 3)
    if len(dup.description or "") > len(keep.description or ""):
        keep.description = dup.description
    if (keep.rel_type or "") in _GENERIC_REL_TYPES and (dup.rel_type or "") not in _GENERIC_REL_TYPES:
        keep.rel_type = dup.rel_type
    history = list(keep.history or []) + list(dup.history or [])
    history.sort(key=lambda item: str(item.get("date", "")))
    keep.history = history[-50:]
    keep.updated_at = datetime.utcnow()
    # 重指引用后再删除重复行，避免悬空外键
    db.query(EvidenceSpan).filter(EvidenceSpan.relationship_id == dup.id).update(
        {"relationship_id": keep.id}, synchronize_session=False)
    db.query(InteractionUnit).filter(InteractionUnit.relationship_id == dup.id).update(
        {"relationship_id": keep.id}, synchronize_session=False)
    db.delete(dup)


def merge_duplicate_relationships(db: Session) -> int:
    """一次性迁移：同一对人物的多条关系（含反向行）合并为一条，返回合并掉的行数"""
    rows = db.query(Relationship).order_by(Relationship.id).all()
    keep_by_pair: dict[tuple[int, int], Relationship] = {}
    merged = 0
    for rel in rows:
        key = (min(rel.source_id, rel.target_id), max(rel.source_id, rel.target_id))
        if key in keep_by_pair:
            _merge_into(db, keep_by_pair[key], rel)
            merged += 1
        else:
            keep_by_pair[key] = rel
    if merged:
        db.commit()
        logger.warning("关系去重迁移：合并了 %s 条重复关系", merged)
    return merged
