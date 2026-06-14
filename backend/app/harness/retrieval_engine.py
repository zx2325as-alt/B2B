from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character,
    CharacterEvent,
    Conversation,
    EvidenceSpan,
    MemoryItem,
    Relationship,
    RetrievalTrace,
)
from ..services.relationships import find_pair_relationship
from .embeddings import cosine_similarity, embed_text, embedding_enabled
from .graph_store import graph_store


MAX_TEXT = 360


def _clip(text: str | None, limit: int = MAX_TEXT) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit]


def _tokens(text: str | None) -> set[str]:
    lower = (text or "").lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", lower))
    cjk = re.findall(r"[\u4e00-\u9fff]", lower)
    words.update(cjk)
    words.update("".join(cjk[index:index + 2]) for index in range(max(0, len(cjk) - 1)))
    return {item for item in words if item.strip()}


def _score_text(query: str, *texts: str | None) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    joined = " ".join(text or "" for text in texts)
    candidate_tokens = _tokens(joined)
    if not candidate_tokens:
        return 0.0
    overlap = len(query_tokens & candidate_tokens) / max(1, len(query_tokens))
    exact_bonus = 0.0
    lowered = joined.lower()
    for token in query_tokens:
        if len(token) >= 2 and token in lowered:
            exact_bonus += 0.04
    return min(1.0, overlap + min(0.3, exact_bonus))


def _recency_score(created_at: datetime | None) -> float:
    if not created_at:
        return 0.0
    age_days = max(0, (datetime.utcnow() - created_at).days)
    if age_days <= 1:
        return 0.25
    if age_days <= 7:
        return 0.18
    if age_days <= 30:
        return 0.1
    return 0.03


def _character_profile(char: Character | None) -> dict[str, Any]:
    if not char:
        return {}
    return {
        "id": char.id,
        "name": char.name,
        "role": char.role or "",
        "background": _clip(char.background, 240),
        "personality_tags": char.personality_tags or [],
        "core_traits": char.core_traits or {},
        "motivation": char.motivation or "",
        "weakness": char.weakness or "",
        "speaking_style": char.speaking_style or "",
        "version": char.version,
    }


def _relationship_context(db: Session, speaker: Character | None, listener: Character | None) -> dict[str, Any]:
    """两人之间只存一条无向关系，直接返回这条 pair 关系"""
    if not speaker or not listener:
        return {}
    rel = find_pair_relationship(db, speaker.id, listener.id)
    return {
        "pair": _relationship_item(rel, listener),
    }


def _relationship_item(rel: Relationship | None, target: Character | None) -> dict[str, Any]:
    if not rel:
        return {
            "target_id": target.id if target else None,
            "target_name": target.name if target else "",
            "rel_type": "unknown",
            "strength": 0.0,
            "sentiment": 0.0,
            "description": "",
        }
    return {
        "id": rel.id,
        "target_id": target.id if target else rel.target_id,
        "target_name": target.name if target else "",
        "rel_type": rel.rel_type,
        "strength": rel.strength,
        "sentiment": rel.sentiment,
        "description": _clip(rel.description, 240),
        "history_tail": (rel.history or [])[-3:],
    }


def _recent_events(db: Session, character_ids: list[int]) -> list[dict[str, Any]]:
    if not character_ids:
        return []
    events = db.query(CharacterEvent).filter(
        CharacterEvent.character_id.in_(character_ids)
    ).order_by(CharacterEvent.created_at.desc()).limit(8).all()
    return [
        {
            "id": event.id,
            "character_id": event.character_id,
            "title": event.title,
            "description": _clip(event.description, 260),
            "event_date": event.event_date or "",
            "emotion_label": event.emotion_label or "",
            "importance": event.importance,
        }
        for event in events
    ]


def _memory_candidates(db: Session, query: str, character_ids: list[int]) -> list[dict[str, Any]]:
    if not character_ids:
        return []
    memories = db.query(MemoryItem).filter(
        MemoryItem.character_id.in_(character_ids),
        MemoryItem.status == "active",
    ).order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).limit(120).all()
    # 可选语义检索：embedding 启用时，查询向量与记忆向量的余弦相似度参与打分
    query_vector = embed_text(query) if embedding_enabled() else None
    scored = []
    for memory in memories:
        score = (
            _score_text(query, memory.content, memory.memory_type, memory.source)
            + float(memory.confidence or 0.0) * 0.35
            + _recency_score(memory.updated_at or memory.created_at)
        )
        if query_vector and memory.embedding:
            score += cosine_similarity(query_vector, memory.embedding) * 0.5
        scored.append(
            {
                "id": memory.id,
                "character_id": memory.character_id,
                "memory_type": memory.memory_type,
                "content": _clip(memory.content, 260),
                "confidence": memory.confidence,
                "source": memory.source,
                "evidence_ids": memory.evidence_ids or [],
                "score": round(score, 4),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:12]


def _evidence_candidates(
    db: Session,
    query: str,
    character_ids: list[int],
    conversation_id: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filters = []
    if character_ids:
        filters.append(EvidenceSpan.character_id.in_(character_ids))
    if conversation_id:
        filters.append(EvidenceSpan.conversation_id == conversation_id)
    if not filters:
        return [], []
    query_obj = db.query(EvidenceSpan).filter(*filters).order_by(EvidenceSpan.created_at.desc()).limit(180)
    scored_supporting = []
    scored_conflicting = []
    for evidence in query_obj.all():
        score = (
            _score_text(query, evidence.quote, evidence.interpretation, evidence.supports_type)
            + float(evidence.confidence or 0.0) * 0.4
            + _recency_score(evidence.created_at)
        )
        item = {
            "id": evidence.id,
            "character_id": evidence.character_id,
            "source_type": evidence.source_type,
            "supports_type": evidence.supports_type,
            "polarity": evidence.polarity,
            "quote": _clip(evidence.quote, 320),
            "interpretation": _clip(evidence.interpretation, 320),
            "confidence": evidence.confidence,
            "score": round(score, 4),
        }
        text = f"{evidence.polarity} {evidence.interpretation}"
        if evidence.polarity == "contradicts" or any(word in text for word in ("反证", "矛盾", "不一致")):
            scored_conflicting.append(item)
        else:
            scored_supporting.append(item)
    scored_supporting.sort(key=lambda item: item["score"], reverse=True)
    scored_conflicting.sort(key=lambda item: item["score"], reverse=True)
    return scored_supporting[:10], scored_conflicting[:5]


def build_evidence_pack(
    db: Session,
    *,
    query_text: str,
    speaker: Character | None,
    listener: Character | None,
    conversation: Conversation | None = None,
) -> dict[str, Any]:
    character_ids = [char.id for char in (speaker, listener) if char]
    supporting_evidence, conflicting_evidence = _evidence_candidates(
        db,
        query_text,
        character_ids,
        conversation.id if conversation else None,
    )
    memory_hits = _memory_candidates(db, query_text, character_ids)
    recent_events = _recent_events(db, character_ids)
    relationship_context = _relationship_context(db, speaker, listener)
    graph_context = graph_store.get_graph_context(
        speaker.id if speaker else None,
        listener.id if listener else None,
    )
    keyword_hits = [
        item for item in supporting_evidence[:5]
        if item["score"] >= 0.35
    ]
    time_hits = sorted(
        supporting_evidence[:8],
        key=lambda item: item["id"],
        reverse=True,
    )[:4]
    graph_hits = []
    for key, rel_item in (relationship_context or {}).items():
        if rel_item and rel_item.get("rel_type") != "unknown":
            graph_hits.append({"kind": "relationship", "direction": key, **rel_item})
    for event in recent_events[:4]:
        graph_hits.append({"kind": "event", **event})
    for person_group in (graph_context.get("people", []) if graph_context else []):
        person = person_group.get("person") or {}
        for rel_item in person_group.get("relationships") or []:
            if rel_item.get("target_id"):
                graph_hits.append({"kind": "neo4j_relationship", "person_id": person.get("id"), **rel_item})
        for memory in person_group.get("memories") or []:
            if memory.get("id"):
                graph_hits.append({"kind": "neo4j_memory", "person_id": person.get("id"), **memory})
        for evidence in person_group.get("evidence") or []:
            if evidence.get("id"):
                graph_hits.append({"kind": "neo4j_evidence", "person_id": person.get("id"), **evidence})

    return {
        "query": query_text,
        "person_profile": {
            "speaker": _character_profile(speaker),
            "listener": _character_profile(listener),
        },
        "relationship_context": relationship_context,
        "graph_context": graph_context,
        "recent_events": recent_events,
        "memory_hits": memory_hits,
        "supporting_evidence": supporting_evidence,
        "conflicting_evidence": conflicting_evidence,
        "retrieval_notes": {
                "strategy": "hybrid_sqlite_keyword_memory_graph_time",
            "vector_hits": [],
            "keyword_hits": keyword_hits,
                "graph_hits": graph_hits[:8],
            "time_hits": time_hits,
            "candidate_counts": {
                "memories": len(memory_hits),
                "supporting_evidence": len(supporting_evidence),
                "conflicting_evidence": len(conflicting_evidence),
                "recent_events": len(recent_events),
                "graph_hits": len(graph_hits),
                "neo4j_people": len(graph_context.get("people", [])) if graph_context else 0,
            },
        },
    }


def record_retrieval_trace(
    db: Session,
    *,
    conversation: Conversation | None,
    speaker: Character | None,
    listener: Character | None,
    query_text: str,
    evidence_pack: dict[str, Any],
) -> RetrievalTrace:
    trace = RetrievalTrace(
        conversation_id=conversation.id if conversation else None,
        speaker_id=speaker.id if speaker else None,
        listener_id=listener.id if listener else None,
        query_text=query_text,
        strategy=evidence_pack.get("retrieval_notes", {}),
        evidence_pack=evidence_pack,
    )
    db.add(trace)
    for hit in evidence_pack.get("memory_hits", [])[:8]:
        memory = db.get(MemoryItem, hit.get("id"))
        if memory:
            memory.last_used_at = datetime.utcnow()
    db.flush()
    return trace


def render_evidence_pack(evidence_pack: dict[str, Any]) -> str:
    if not evidence_pack:
        return ""
    lines = ["混合检索证据包："]
    profiles = evidence_pack.get("person_profile", {})
    for label, profile in [("发言者", profiles.get("speaker") or {}), ("接收方", profiles.get("listener") or {})]:
        if profile:
            tags = "、".join(profile.get("personality_tags") or []) or "暂无"
            lines.append(f"- {label}画像：{profile.get('name', '')}｜标签：{tags}｜动机：{profile.get('motivation') or '暂无'}｜弱点：{profile.get('weakness') or '暂无'}")
    rel = evidence_pack.get("relationship_context") or {}
    pair_rel = rel.get("pair") or rel.get("speaker_to_listener") or {}
    if pair_rel:
        lines.append(f"- 关系链：{pair_rel.get('target_name', '')}｜类型={pair_rel.get('rel_type')}｜强度={pair_rel.get('strength')}｜极性={pair_rel.get('sentiment')}｜说明={pair_rel.get('description') or '暂无'}")
    graph_people = (evidence_pack.get("graph_context") or {}).get("people", [])
    if graph_people:
        lines.append("- Neo4j 图谱上下文：")
        for group in graph_people[:3]:
            person = group.get("person") or {}
            rel_count = len([item for item in (group.get("relationships") or []) if item.get("target_id")])
            memory_count = len([item for item in (group.get("memories") or []) if item.get("id")])
            evidence_count = len([item for item in (group.get("evidence") or []) if item.get("id")])
            lines.append(f"  - {person.get('name') or person.get('id')}：关系 {rel_count}，记忆 {memory_count}，证据 {evidence_count}")
    memories = evidence_pack.get("memory_hits", [])[:6]
    if memories:
        lines.append("- 长期记忆命中：")
        for item in memories:
            lines.append(f"  - [{item.get('memory_type')}] {item.get('content')}（置信度 {round(float(item.get('confidence') or 0), 2)}，证据 {item.get('evidence_ids') or []}）")
    evidence = evidence_pack.get("supporting_evidence", [])[:6]
    if evidence:
        lines.append("- 支撑证据：")
        for item in evidence:
            lines.append(f"  - #{item.get('id')} {item.get('quote')} => {item.get('interpretation')}")
    conflicts = evidence_pack.get("conflicting_evidence", [])[:3]
    if conflicts:
        lines.append("- 反证/冲突证据：")
        for item in conflicts:
            lines.append(f"  - #{item.get('id')} {item.get('quote')} => {item.get('interpretation')}")
    notes = evidence_pack.get("retrieval_notes", {})
    lines.append(f"- 检索说明：{notes.get('strategy')}，候选统计：{notes.get('candidate_counts')}")
    return "\n".join(lines)
