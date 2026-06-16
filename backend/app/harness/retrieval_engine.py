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


# 持久知识类型：上传资料 / 诊断沉淀，不随时间过期，给新鲜度地板避免被对话记忆冲掉
_DURABLE_TYPES = {"reference", "diagnosis"}
_RRF_K = 60  # 倒数排名融合常数：越大越平滑，淡化头部排名的绝对差距
_MMR_LAMBDA = 0.7  # MMR 权衡：0.7 偏相关、0.3 罚冗余
_DUP_THRESHOLD = 0.85  # 与已选项相似度超过此值视为近重复，硬性降级（除非别无可选）
_MEMORY_TOP_N = 20  # 不计成本/时间：召回更多长期记忆，让"他上次也这样"够得到更远
_REFERENCE_QUOTA = 4  # 命中资料时至少保留这么多块，保证上传资料能进上下文


def _pair_similarity(item_a: dict[str, Any], item_b: dict[str, Any]) -> float:
    """两条候选的冗余度：有向量用余弦，否则退化为内容词 Jaccard。"""
    emb_a, emb_b = item_a.get("_emb"), item_b.get("_emb")
    if emb_a and emb_b:
        return cosine_similarity(emb_a, emb_b)
    tokens_a, tokens_b = _tokens(item_a.get("content")), _tokens(item_b.get("content"))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))


def _rerank_memory(pool: list[dict[str, Any]], has_vector: bool, top_n: int = _MEMORY_TOP_N) -> list[dict[str, Any]]:
    """
    两阶段召回的第二阶段：RRF 融合 + MMR 去冗余。
    - RRF：分别按关键词分、向量分排名，倒数排名融合（量纲无关，比线性加权稳健）
    - 先验：置信度 + 新鲜度 + 持久知识小幅加权
    - MMR：相关性高且与已选差异大者优先，避免返回同一份资料的多个近重复块
    - 配额：命中资料时保底纳入若干 reference 块
    """
    if not pool:
        return []
    size = len(pool)
    rrf = [0.0] * size
    for rank, idx in enumerate(sorted(range(size), key=lambda i: pool[i]["_kw"], reverse=True)):
        rrf[idx] += 1.0 / (_RRF_K + rank + 1)
    if has_vector:
        for rank, idx in enumerate(sorted(range(size), key=lambda i: pool[i]["_vec"], reverse=True)):
            rrf[idx] += 1.0 / (_RRF_K + rank + 1)
    for idx, item in enumerate(pool):
        prior = float(item["confidence"] or 0.0) * 0.02 + item["_rec"] * 0.02
        if item["memory_type"] in _DURABLE_TYPES:
            prior += 0.005
        item["_rel"] = rrf[idx] + prior
    # 相关性归一到 [0,1]，让 MMR 的相关项与冗余罚项处于同一量纲
    rels = [item["_rel"] for item in pool]
    low, high = min(rels), max(rels)
    span = (high - low) or 1.0
    for item in pool:
        item["_reln"] = (item["_rel"] - low) / span

    remaining = sorted(range(size), key=lambda i: pool[i]["_reln"], reverse=True)
    selected: list[int] = []
    while remaining and len(selected) < top_n:
        if not selected:
            selected.append(remaining.pop(0))
            continue
        scored = []
        for idx in remaining:
            max_sim = max(_pair_similarity(pool[idx], pool[j]) for j in selected)
            mmr = _MMR_LAMBDA * pool[idx]["_reln"] - (1 - _MMR_LAMBDA) * max_sim
            scored.append((idx, mmr, max_sim))
        # 近重复硬过滤：优先选与已选差异足够大的；全是近重复时再退而求其次
        novel = [entry for entry in scored if entry[2] < _DUP_THRESHOLD]
        best_idx = max(novel or scored, key=lambda entry: entry[1])[0]
        selected.append(best_idx)
        remaining.remove(best_idx)

    # 资料配额：若命中的 reference 块没进结果，挤掉分数最低的非资料项补进来
    ref_pool = sorted(
        (i for i in range(size) if pool[i]["memory_type"] == "reference"),
        key=lambda i: pool[i]["_rel"], reverse=True,
    )
    have_ref = sum(1 for i in selected if pool[i]["memory_type"] == "reference")
    for idx in ref_pool:
        if have_ref >= _REFERENCE_QUOTA:
            break
        if idx in selected:
            continue
        non_ref = [i for i in selected if pool[i]["memory_type"] != "reference"]
        if not non_ref:
            break
        victim = min(non_ref, key=lambda i: pool[i]["_rel"])
        selected[selected.index(victim)] = idx
        have_ref += 1
    selected.sort(key=lambda i: pool[i]["_rel"], reverse=True)

    results = []
    for idx in selected:
        item = pool[idx]
        results.append({
            "id": item["id"],
            "character_id": item["character_id"],
            "memory_type": item["memory_type"],
            "content": item["content"],
            "confidence": item["confidence"],
            "source": item["source"],
            "evidence_ids": item["evidence_ids"],
            "score": round(item["_rel"], 4),
        })
    return results


def _memory_candidates(db: Session, query: str, character_ids: list[int]) -> list[dict[str, Any]]:
    if not character_ids:
        return []
    # 启用向量检索时放宽候选池：语义召回要能够到更久远的记忆（跨会话"他上次也这样"），
    # 不能被"最近 120 条"按时间先砍掉；纯字面检索时维持原来的近度优先窗口。
    semantic_on = embedding_enabled()
    candidate_cap = 1000 if semantic_on else 120
    memories = db.query(MemoryItem).filter(
        MemoryItem.character_id.in_(character_ids),
        MemoryItem.status == "active",
    ).order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).limit(candidate_cap).all()
    # 第一阶段召回：对每条候选独立算关键词分与向量分（不再线性混合，留给 rerank 融合）
    query_vector = embed_text(query) if semantic_on else None
    pool = []
    for memory in memories:
        recency = _recency_score(memory.updated_at or memory.created_at)
        # 持久知识不随时间衰减——给新鲜度地板，避免老资料被近期对话记忆压没
        if memory.memory_type in _DURABLE_TYPES:
            recency = max(recency, 0.1)
        pool.append({
            "id": memory.id,
            "character_id": memory.character_id,
            "memory_type": memory.memory_type,
            "content": _clip(memory.content, 260),
            "confidence": memory.confidence,
            "source": memory.source,
            "evidence_ids": memory.evidence_ids or [],
            "_kw": _score_text(query, memory.content, memory.memory_type, memory.source),
            "_vec": cosine_similarity(query_vector, memory.embedding) if (query_vector and memory.embedding) else 0.0,
            "_rec": recency,
            "_emb": memory.embedding,
        })
    return _rerank_memory(pool, query_vector is not None)


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
    query_obj = db.query(EvidenceSpan).filter(*filters).order_by(EvidenceSpan.created_at.desc()).limit(320)
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
    return scored_supporting[:18], scored_conflicting[:10]


def _multihop_facts(speaker: Character | None, listener: Character | None) -> dict[str, Any]:
    """会话两人之间的多跳关系事实（牵线人 + 最短关系链）。图谱不可用/未连通时安全返回空。"""
    if not speaker or not listener:
        return {}
    try:
        if not graph_store.is_available():
            return {}
        intermediaries = graph_store.find_intermediaries(speaker.id, listener.id, limit=6) or []
        path = graph_store.shortest_path(speaker.id, listener.id, max_hops=5) or {}
        # 直接相连（1 跳）就不必展示路径，留给已有的关系链字段
        if path.get("hops", 0) and path["hops"] <= 1:
            path = {}
        if not intermediaries and not path:
            return {}
        return {"intermediaries": intermediaries, "path": path}
    except Exception:
        return {}


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
    # 上传资料单独拎出，便于在 prompt 里明确标注为"外部依据"供模型引用
    reference_hits = [hit for hit in memory_hits if hit.get("memory_type") == "reference"][:8]
    recent_events = _recent_events(db, character_ids)
    relationship_context = _relationship_context(db, speaker, listener)
    graph_context = graph_store.get_graph_context(
        speaker.id if speaker else None,
        listener.id if listener else None,
    )
    # 多跳关系：会话两人之间的牵线人 + 最短关系链（"对方↔我"怎么连上的，谁能引荐）
    multihop = _multihop_facts(speaker, listener)
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
        "multihop": multihop,
        "recent_events": recent_events,
        "memory_hits": memory_hits,
        "reference_hits": reference_hits,
        "supporting_evidence": supporting_evidence,
        "conflicting_evidence": conflicting_evidence,
        "retrieval_notes": {
                "strategy": "rrf_mmr_rerank_keyword_vector_graph",
            "vector_hits": [],
            "keyword_hits": keyword_hits,
                "graph_hits": graph_hits[:16],
            "time_hits": time_hits,
            "candidate_counts": {
                "memories": len(memory_hits),
                "references": len(reference_hits),
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
    # 多跳关系：牵线人 + 最短关系链（让"对方↔我"的间接连接进入每次分析）
    multihop = evidence_pack.get("multihop") or {}
    intermediaries = multihop.get("intermediaries") or []
    if intermediaries:
        lines.append("- 多跳·牵线人（同时认识双方、可引荐/施压的中间人）：")
        for it in intermediaries[:6]:
            person = it.get("person") or {}
            lines.append(f"  - {person.get('name') or person.get('id')}：与发言方[{it.get('my_rel') or '?'}/{it.get('my_sentiment')}]、与对方[{it.get('target_rel') or '?'}/{it.get('target_sentiment')}]")
    path = multihop.get("path") or {}
    if path.get("nodes"):
        chain = " → ".join((n.get("name") or str(n.get("id"))) for n in path["nodes"])
        lines.append(f"- 多跳·关系链（{path.get('hops')} 跳）：{chain}")
    graph_people = (evidence_pack.get("graph_context") or {}).get("people", [])
    if graph_people:
        lines.append("- Neo4j 图谱上下文：")
        for group in graph_people[:6]:
            person = group.get("person") or {}
            rel_count = len([item for item in (group.get("relationships") or []) if item.get("target_id")])
            memory_count = len([item for item in (group.get("memories") or []) if item.get("id")])
            evidence_count = len([item for item in (group.get("evidence") or []) if item.get("id")])
            lines.append(f"  - {person.get('name') or person.get('id')}：关系 {rel_count}，记忆 {memory_count}，证据 {evidence_count}")
    references = evidence_pack.get("reference_hits", [])[:8]
    if references:
        lines.append("- 参考资料命中（用户上传的外部依据，可直接引用作答）：")
        for item in references:
            lines.append(f"  - {item.get('content')}（来源：{item.get('source') or '上传资料'}）")
    memories = [item for item in evidence_pack.get("memory_hits", []) if item.get("memory_type") != "reference"][:12]
    if memories:
        lines.append("- 长期记忆命中：")
        for item in memories:
            lines.append(f"  - [{item.get('memory_type')}] {item.get('content')}（置信度 {round(float(item.get('confidence') or 0), 2)}，证据 {item.get('evidence_ids') or []}）")
    evidence = evidence_pack.get("supporting_evidence", [])[:12]
    if evidence:
        lines.append("- 支撑证据：")
        for item in evidence:
            lines.append(f"  - #{item.get('id')} {item.get('quote')} => {item.get('interpretation')}")
    conflicts = evidence_pack.get("conflicting_evidence", [])[:6]
    if conflicts:
        lines.append("- 反证/冲突证据：")
        for item in conflicts:
            lines.append(f"  - #{item.get('id')} {item.get('quote')} => {item.get('interpretation')}")
    notes = evidence_pack.get("retrieval_notes", {})
    lines.append(f"- 检索说明：{notes.get('strategy')}，候选统计：{notes.get('candidate_counts')}")
    return "\n".join(lines)
