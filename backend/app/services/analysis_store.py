"""持久化写入助手：长期记忆 / 证据片段（被诊断、归档、关系回流共用）。
从 api/chat.py 抽出，避免业务路由与存储细节耦合。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..harness.graph_store import graph_store
from ..models.sql_models import EvidenceSpan, MemoryItem


def create_evidence_span(
    db: Session,
    *,
    character_id: int | None,
    source_type: str,
    quote: str,
    interpretation: str,
    confidence: float,
    supports_type: str = "memory",
    supports_id: int | None = None,
    source_id: int | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
    character_event_id: int | None = None,
    relationship_id: int | None = None,
    observation_id: int | None = None,
    metadata: dict | None = None,
) -> EvidenceSpan:
    evidence = EvidenceSpan(
        character_id=character_id,
        source_type=source_type,
        source_id=source_id,
        conversation_id=conversation_id,
        message_id=message_id,
        character_event_id=character_event_id,
        relationship_id=relationship_id,
        observation_id=observation_id,
        supports_type=supports_type,
        supports_id=supports_id,
        quote=(quote or "")[:2000],
        interpretation=(interpretation or "")[:2000],
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        metadata_json=metadata or {},
    )
    db.add(evidence)
    db.flush()
    graph_store.sync_evidence(evidence)
    return evidence


def create_memory_item(
    db: Session,
    *,
    character_id: int,
    memory_type: str,
    content: str,
    confidence: float,
    source: str,
    evidence_ids: list[int] | None = None,
) -> MemoryItem | None:
    normalized = (content or "").strip()
    if not normalized:
        return None
    existing = db.query(MemoryItem).filter(
        MemoryItem.character_id == character_id,
        MemoryItem.memory_type == memory_type,
        MemoryItem.content == normalized,
        MemoryItem.status == "active",
    ).first()
    if existing:
        existing.evidence_ids = list(dict.fromkeys(list(existing.evidence_ids or []) + list(evidence_ids or [])))
        existing.confidence = max(float(existing.confidence or 0.0), max(0.0, min(1.0, float(confidence or 0.0))))
        existing.updated_at = datetime.utcnow()
        db.flush()
        graph_store.sync_memory(existing)
        return existing
    from ..harness.embeddings import embed_text
    memory = MemoryItem(
        character_id=character_id,
        memory_type=memory_type,
        content=normalized[:2000],
        embedding=embed_text(normalized[:2000]),
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        evidence_ids=list(evidence_ids or []),
        source=source,
        status="active",
    )
    db.add(memory)
    db.flush()
    graph_store.sync_memory(memory)
    return memory
