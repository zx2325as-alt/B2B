import json
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Conversation, Message, Character, Relationship, CharacterEvent, CharacterObservation,
    EvidenceSpan, MemoryItem, RetrievalTrace, StructuredDiagnosis, AgentRun,
)
from ..schemas import ChatMessage, ConversationCreate, MessageOut, StructuredDiagnosisOut
from ..harness.orchestrator import orchestrator
from ..harness.context_manager import get_context
from ..harness.state_engine import state_engine
from ..harness.consistency_engine import build_consistency_constraints
from ..harness.retrieval_engine import (
    build_evidence_pack,
    record_retrieval_trace,
    render_evidence_pack,
)
from ..harness.graph_store import graph_store
from .deps import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


SCENARIO_PRESETS = {
    "general": {
        "title": "通用对话",
        "default_speaker": "",
    },
    "bar_chat": {
        "title": "老友酒吧闲聊",
        "default_speaker": "吉娜",
    },
    "business": {
        "title": "商务谈判",
        "default_speaker": "",
    },
    "hr_interview": {
        "title": "HR面试",
        "default_speaker": "",
    },
    "counseling": {
        "title": "心理咨询",
        "default_speaker": "",
    },
}


def _parse_emotion_label(label: str | None) -> dict:
    if not label:
        return {}
    try_match = re.search(r"试图激发[:：]\s*([^\(\]\[｜|]+)\((\d+)\)", label)
    surface_match = re.search(r"表层[:：]\s*([^\(\]\[｜|]+)\((\d+)\)", label)
    deep_match = re.search(r"深层[:：]\s*([^\(\]\[｜|]+)\((\d+)\)", label)
    suppressed_match = re.search(r"压抑[:：]\s*([^\(\]\[｜|]+)\((\d+)\)", label)
    return {
        "intended_label": try_match.group(1).strip() if try_match else "",
        "intended_score": int(try_match.group(2)) if try_match else 0,
        "surface_label": surface_match.group(1).strip() if surface_match else "",
        "surface_score": int(surface_match.group(2)) if surface_match else 0,
        "deep_label": deep_match.group(1).strip() if deep_match else "",
        "deep_score": int(deep_match.group(2)) if deep_match else 0,
        "suppressed_label": suppressed_match.group(1).strip() if suppressed_match else "",
        "suppressed_score": int(suppressed_match.group(2)) if suppressed_match else 0,
        "actual_label": deep_match.group(1).strip() if deep_match else "",
        "actual_score": int(deep_match.group(2)) if deep_match else 0,
    }


def _parse_strategy_text(strategy_text: str | None) -> dict:
    lines = [line.strip() for line in (strategy_text or "").splitlines() if line.strip()]
    return {
        "short_term": next((line.replace("短期策略：", "").strip() for line in lines if line.startswith("短期策略：")), ""),
        "long_term": next((line.replace("长期策略：", "").strip() for line in lines if line.startswith("长期策略：")), ""),
        "consistency": next((line.replace("一致性说明：", "").strip() for line in lines if line.startswith("一致性说明：")), ""),
    }


def _emotion_polarity(label: str) -> int:
    positive = {"喜悦", "依恋", "信任", "安心", "感动", "期待", "亲近"}
    negative = {"愧疚", "恐惧", "愤怒", "厌烦", "警惕", "防御", "回避", "羞耻", "怀疑"}
    if label in positive:
        return 1
    if label in negative:
        return -1
    return 0


def _create_evidence_span(
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


def _create_memory_item(
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
    memory = MemoryItem(
        character_id=character_id,
        memory_type=memory_type,
        content=normalized[:2000],
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        evidence_ids=list(evidence_ids or []),
        source=source,
        status="active",
    )
    db.add(memory)
    db.flush()
    graph_store.sync_memory(memory)
    return memory


def _compact_evidence_pack(evidence_pack: dict) -> dict:
    if not evidence_pack:
        return {}
    return {
        "query": evidence_pack.get("query", ""),
        "person_profile": evidence_pack.get("person_profile", {}),
        "relationship_context": evidence_pack.get("relationship_context", {}),
        "graph_context": evidence_pack.get("graph_context", {}),
        "memory_hits": (evidence_pack.get("memory_hits") or [])[:8],
        "supporting_evidence": (evidence_pack.get("supporting_evidence") or [])[:8],
        "conflicting_evidence": (evidence_pack.get("conflicting_evidence") or [])[:5],
        "retrieval_notes": evidence_pack.get("retrieval_notes", {}),
    }


def _extract_evidence_ids(items: list[dict] | None) -> list[int]:
    ids = []
    for item in items or []:
        value = item.get("evidence_id") or item.get("id")
        try:
            if value is not None:
                ids.append(int(value))
        except Exception:
            continue
    return list(dict.fromkeys(ids))


def _diagnosis_status(diagnosis: dict, critic: dict) -> str:
    final_status = (critic or {}).get("final_status") or ""
    if final_status in {"approved", "downgraded", "insufficient", "rejected"}:
        return final_status
    if diagnosis.get("insufficient_evidence"):
        return "insufficient"
    recommendation = diagnosis.get("save_recommendation")
    if recommendation == "save":
        return "approved"
    if recommendation == "discard":
        return "rejected"
    return "downgraded"


def _diagnosis_confidence(diagnosis: dict, critic: dict) -> float:
    base = float(diagnosis.get("confidence") or 0.0)
    adjustment = float((critic or {}).get("confidence_adjustment") or 0.0)
    return max(0.0, min(1.0, base + adjustment))


def _profile_context(char: Character | None) -> dict:
    if not char:
        return {}
    return {
        "id": char.id,
        "name": char.name,
        "role": char.role or "",
        "personality_tags": char.personality_tags or [],
        "core_traits": char.core_traits or {},
        "motivation": char.motivation or "",
        "weakness": char.weakness or "",
        "speaking_style": char.speaking_style or "",
    }


async def _run_structured_diagnosis(
    db: Session,
    *,
    conv: Conversation,
    user_msg: Message,
    ai_msg: Message,
    speaker_char: Character | None,
    listener_char: Character | None,
    analysis_result: dict,
    evidence_pack: dict,
) -> StructuredDiagnosis | None:
    agent_run = AgentRun(
        workflow_name="structured_diagnosis",
        input_hash=f"message:{user_msg.id}:analysis:{ai_msg.id}",
        status="running",
        model_used="ai-harness",
        trace_json={
            "conversation_id": conv.id,
            "message_id": user_msg.id,
            "steps": ["structured_diagnosis", "diagnosis_critic"],
        },
    )
    db.add(agent_run)
    db.flush()
    compact_pack = _compact_evidence_pack(evidence_pack)
    diagnosis_context = {
        "conversation": {"id": conv.id, "scenario": conv.scenario},
        "speaker": _profile_context(speaker_char),
        "listener": _profile_context(listener_char),
        "message": {
            "id": user_msg.id,
            "speaker": user_msg.character_name or "",
            "receiver": user_msg.receiver_name or "",
            "content": user_msg.content,
        },
        "analysis": analysis_result,
        "evidence_pack": compact_pack,
    }
    try:
        diagnosis = await orchestrator.structured_diagnosis(diagnosis_context)
        critic = await orchestrator.critique_diagnosis(
            diagnosis,
            compact_pack,
            {
                "speaker": _profile_context(speaker_char),
                "listener": _profile_context(listener_char),
            },
        )
        evidence_ids = _extract_evidence_ids(diagnosis.get("supporting_evidence"))
        conflicting_ids = _extract_evidence_ids(diagnosis.get("conflicting_evidence"))
        status = _diagnosis_status(diagnosis, critic)
        confidence = _diagnosis_confidence(diagnosis, critic)
        report = StructuredDiagnosis(
            conversation_id=conv.id,
            message_id=user_msg.id,
            analysis_message_id=ai_msg.id,
            speaker_id=speaker_char.id if speaker_char else None,
            listener_id=listener_char.id if listener_char else None,
            diagnosis_type=diagnosis.get("diagnosis_type") or "subtext",
            status=status,
            confidence=confidence,
            result_json=diagnosis,
            critic_json=critic,
            evidence_ids=evidence_ids,
            conflicting_evidence_ids=conflicting_ids,
            agent_run_id=agent_run.id,
        )
        db.add(report)
        db.flush()
        memory_candidate = diagnosis.get("memory_candidate") or {}
        save_recommendation = (critic or {}).get("save_recommendation") or diagnosis.get("save_recommendation")
        if listener_char and status == "approved" and save_recommendation == "save":
            content = (memory_candidate.get("content") or critic.get("revised_summary") or diagnosis.get("summary") or "").strip()
            if content:
                _create_memory_item(
                    db,
                    character_id=listener_char.id,
                    memory_type=memory_candidate.get("memory_type") or "diagnosis",
                    content=content,
                    confidence=confidence,
                    source="结构化诊断",
                    evidence_ids=evidence_ids,
                )
        agent_run.status = "completed"
        agent_run.trace_json = {
            **(agent_run.trace_json or {}),
            "status": status,
            "confidence": confidence,
            "diagnosis_id": report.id,
            "critic": critic,
        }
        agent_run.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(report)
        return report
    except Exception as exc:
        agent_run.status = "failed"
        agent_run.trace_json = {**(agent_run.trace_json or {}), "error": str(exc)}
        agent_run.updated_at = datetime.utcnow()
        db.commit()
        return None


def _find_or_create_character(db: Session, name: str) -> Character:
    char = db.query(Character).filter(Character.name == name).first()
    if char:
        return char
    char = Character(
        name=name,
        role="",
        background="",
        personality_tags=[],
        core_traits={},
        weakness="",
        motivation="",
        speaking_style="",
    )
    db.add(char)
    db.commit()
    db.refresh(char)
    graph_store.sync_character(char)
    return char


def _get_recent_dialogue(db: Session, conv_id: int, limit: int = 10) -> str:
    conv = db.get(Conversation, conv_id)
    if not conv:
        return ""
    messages = _visible_messages_query(db, conv).filter(
        Message.role == "user",
    ).order_by(Message.message_index.desc(), Message.created_at.desc(), Message.id.desc()).limit(limit).all()
    lines = []
    for message in reversed(messages):
        lines.append(f"[{message.character_name or '未知角色'}] {message.content}")
    return "\n".join(lines)


def _build_profile_dict(char: Character | None) -> dict:
    if not char:
        return {
            "name": "",
            "role": "",
            "background": "",
            "personality_tags": [],
            "core_traits": {},
            "weakness": "",
            "motivation": "",
            "speaking_style": "",
        }
    return {
        "name": char.name,
        "role": char.role or "",
        "background": char.background or "",
        "personality_tags": char.personality_tags or [],
        "core_traits": char.core_traits or {},
        "weakness": char.weakness or "",
        "motivation": char.motivation or "",
        "speaking_style": char.speaking_style or "",
    }


def _list_behavior_patterns(db: Session, char_id: int | None) -> list[str]:
    if not char_id:
        return []
    observations = db.query(CharacterObservation).filter(
        CharacterObservation.character_id == char_id
    ).order_by(CharacterObservation.created_at.desc()).limit(5).all()
    return [ob.reason for ob in observations if ob.reason]


def _get_relationship_snapshot(db: Session, speaker_char: Character | None, listener_char: Character | None) -> dict:
    if not speaker_char or not listener_char:
        return {}
    relationship = db.query(Relationship).filter(
        Relationship.source_id == speaker_char.id,
        Relationship.target_id == listener_char.id,
    ).first()
    if relationship:
        trust = max(0.0, min(1.0, relationship.strength))
        sentiment = relationship.sentiment or 0.0
        snapshot = {
            "rel_type": relationship.rel_type,
            "strength": relationship.strength,
            "sentiment": relationship.sentiment,
            "description": relationship.description or "",
            "target_name": listener_char.name,
            "belief": relationship.description or "",
            "trust": trust,
            "dependency": max(0.0, min(1.0, 0.5 + sentiment / 2)),
            "dominance": max(0.0, min(1.0, 1 - trust / 2)),
            "fear": max(0.0, min(1.0, 0.5 - sentiment / 2)),
            "attraction": max(0.0, min(1.0, 0.5 + sentiment / 2)),
        }
        return snapshot
    return {
        "rel_type": "unknown",
        "strength": 0.4,
        "sentiment": 0.0,
        "description": "",
        "target_name": listener_char.name,
        "belief": "",
        "trust": 0.4,
        "dependency": 0.3,
        "dominance": 0.5,
        "fear": 0.2,
        "attraction": 0.3,
    }


def _select_primary_listener(
    db: Session,
    speaker: str,
    active_characters: list,
    conv_id: int,
) -> tuple[list, object | None]:
    listeners = [c for c in (active_characters or []) if c.name != speaker]
    if not listeners:
        return [], None

    speaker_char = db.query(Character).filter(Character.name == speaker).first()
    if not speaker_char:
        return listeners, listeners[0]

    conv = db.get(Conversation, conv_id)
    if conv:
        recent_messages = _visible_messages_query(db, conv).filter(
            Message.role == "user",
        ).order_by(Message.message_index.desc(), Message.created_at.desc(), Message.id.desc()).limit(5).all()
    else:
        recent_messages = []
    recent_content = "\n".join(m.content for m in recent_messages)

    ranked = []
    for listener in listeners:
        score = 0.0
        if listener.name and listener.name in recent_content:
            score += 1.5
        if getattr(listener, "id", None):
            relationship = db.query(Relationship).filter(
                Relationship.source_id == speaker_char.id,
                Relationship.target_id == listener.id,
            ).first()
            if relationship:
                score += relationship.strength
        ranked.append((score, listener))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return listeners, ranked[0][1]


def _build_listener_memory(
    db: Session,
    conv_id: int,
    speaker: str,
    listeners: list,
    primary_listener,
) -> tuple[str, str, str, str, str, dict]:
    if not listeners:
        return "暂无明确接收方信息，请基于当前对话有限信息推测。", "未知聆听者", "", "", "", {}

    speaker_char = db.query(Character).filter(Character.name == speaker).first()
    speaker_profile = _build_profile_dict(speaker_char)
    listener_names = [listener.name for listener in listeners]
    recent_dialogue = _get_recent_dialogue(db, conv_id, limit=5)
    memory_parts = []
    primary_char = None
    relationship_snapshot = {}
    listener_state_block = ""
    speaker_state_block = ""
    consistency_block = ""

    if primary_listener and getattr(primary_listener, "id", None):
        primary_char = db.get(Character, primary_listener.id)
        if primary_char:
            listener_profile = _build_profile_dict(primary_char)
            memory_parts.append(
                "\n".join(
                    [
                        f"主要接收方：{primary_char.name}",
                        f"角色定位：{primary_char.role or '未知'}",
                        f"背景：{primary_char.background or '未知'}",
                        f"性格标签：{'、'.join(primary_char.personality_tags or []) or '未知'}",
                        f"核心动机：{primary_char.motivation or '未知'}",
                        f"弱点：{primary_char.weakness or '未知'}",
                        f"说话风格：{primary_char.speaking_style or '未知'}",
                    ]
                )
            )
            events = db.query(CharacterEvent).filter(
                CharacterEvent.character_id == primary_char.id
            ).order_by(CharacterEvent.created_at.desc()).limit(3).all()
            if events:
                memory_parts.append(
                    "关键经历：\n" + "\n".join(
                        f"- {event.title}：{event.description or ''}" for event in events
                    )
                )
            relationship_snapshot = _get_relationship_snapshot(db, speaker_char, primary_char)
            memory_parts.append(
                "\n".join(
                    [
                        f"与发言者关系类型：{relationship_snapshot.get('rel_type', 'neutral')}",
                        f"关系强度：{relationship_snapshot.get('strength', 0.4)}",
                        f"情感极性：{relationship_snapshot.get('sentiment', 0.0)}",
                        f"关系描述：{relationship_snapshot.get('description', '暂无') or '暂无'}",
                    ]
                )
            )
            listener_state = state_engine.bootstrap_state(
                conv_id,
                primary_char.name,
                listener_profile,
                relationship_snapshot,
                _list_behavior_patterns(db, primary_char.id),
            )
            listener_state_block = state_engine.render_state_block(primary_char.name, listener_state)
            if speaker_char:
                speaker_state = state_engine.bootstrap_state(
                    conv_id,
                    speaker_char.name,
                    speaker_profile,
                    relationship_snapshot,
                    _list_behavior_patterns(db, speaker_char.id),
                )
                speaker_state_block = state_engine.render_state_block(speaker_char.name, speaker_state)
            consistency_block = build_consistency_constraints(
                speaker_profile,
                listener_profile,
                relationship_snapshot,
                recent_dialogue,
            )

    if len(listener_names) > 1:
        memory_parts.append(f"其他接收方：{'、'.join(name for name in listener_names if name != primary_listener.name)}")
    if recent_dialogue:
        memory_parts.append(f"最近5轮上下文：\n{recent_dialogue}")

    return (
        "\n\n".join(memory_parts),
        primary_listener.name if primary_listener else listener_names[0],
        speaker_state_block,
        listener_state_block,
        consistency_block,
        relationship_snapshot | {"primary_listener_name": primary_listener.name if primary_listener else listener_names[0]},
    )


def _visible_message_filter(conv: Conversation):
    base_filter = Message.conversation_id == conv.id
    active_branch_id = getattr(conv, "active_branch_id", None)
    branch_point_id = getattr(conv, "active_branch_point_id", None)
    if active_branch_id:
        mainline_filter = Message.branch_id.is_(None)
        if branch_point_id:
            mainline_filter = and_(mainline_filter, Message.id <= branch_point_id)
        return and_(
            base_filter,
            or_(mainline_filter, Message.branch_id == active_branch_id),
        )
    return and_(base_filter, Message.branch_id.is_(None))


def _visible_messages_query(db: Session, conv: Conversation):
    return db.query(Message).filter(_visible_message_filter(conv))


def _hydrate_context_from_db(
    db: Session,
    conv: Conversation,
    before_message_id: int | None = None,
    include_message_id: int | None = None,
) -> None:
    ctx = get_context(conv.id)
    ctx.clear()
    query = _visible_messages_query(db, conv)
    if include_message_id:
        query = query.filter(Message.id <= include_message_id)
    elif before_message_id:
        query = query.filter(Message.id < before_message_id)
    rows = query.order_by(Message.message_index, Message.created_at, Message.id).all()
    for row in rows[-40:]:
        display_name = row.character_name or row.role
        if row.role == "assistant" and row.receiver_name:
            display_name = f"{row.receiver_name}的回复"
        ctx.add(row.role, row.content, {"character_name": display_name})


# ─── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    convs = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(20).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "scenario": c.scenario,
            "updated_at": c.updated_at,
            "is_readonly": bool(getattr(c, "is_readonly", False)),
            "source_import_file_id": getattr(c, "source_import_file_id", None),
            "active_branch_id": getattr(c, "active_branch_id", None),
            "active_branch_point_id": getattr(c, "active_branch_point_id", None),
        }
        for c in convs
    ]


@router.post("/conversations")
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    conv = Conversation(title=body.title, scenario=body.scenario)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {
        "id": conv.id,
        "title": conv.title,
        "scenario": conv.scenario,
        "is_readonly": False,
        "active_branch_id": None,
        "active_branch_point_id": None,
    }


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    # 级联删除相关的 messages (假设已在模型中配置级联，否则需要手动删除)
    db.query(Message).filter_by(conversation_id=conv_id).delete()
    db.delete(conv)
    db.commit()
    return {"ok": True}


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def get_messages(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    rows = _visible_messages_query(db, conv).order_by(Message.message_index, Message.created_at, Message.id).all()
    for index, row in enumerate(rows, start=1):
        if not row.message_index:
            row.message_index = index
    db.commit()
    return rows


@router.post("/conversations/{conv_id}/evidence-pack")
def preview_evidence_pack(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    query_text = (payload.get("query_text") or payload.get("content") or "").strip()
    if not query_text:
        raise HTTPException(400, "query_text 不能为空")
    speaker_name = (payload.get("speaker") or "").strip()
    listener_name = (payload.get("listener") or payload.get("receiver") or "").strip()
    speaker = db.query(Character).filter(Character.name == speaker_name).first() if speaker_name else None
    listener = db.query(Character).filter(Character.name == listener_name).first() if listener_name else None
    pack = build_evidence_pack(
        db,
        query_text=query_text,
        speaker=speaker,
        listener=listener,
        conversation=conv,
    )
    trace = record_retrieval_trace(
        db,
        conversation=conv,
        speaker=speaker,
        listener=listener,
        query_text=query_text,
        evidence_pack=pack,
    )
    db.commit()
    pack["trace_id"] = trace.id
    return pack


@router.get("/conversations/{conv_id}/retrieval-traces")
def list_retrieval_traces(conv_id: int, limit: int = 20, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    traces = db.query(RetrievalTrace).filter(
        RetrievalTrace.conversation_id == conv_id,
    ).order_by(RetrievalTrace.created_at.desc()).limit(min(max(limit, 1), 100)).all()
    return [
        {
            "id": trace.id,
            "conversation_id": trace.conversation_id,
            "speaker_id": trace.speaker_id,
            "listener_id": trace.listener_id,
            "query_text": trace.query_text,
            "strategy": trace.strategy or {},
            "evidence_pack": trace.evidence_pack or {},
            "created_at": trace.created_at.isoformat() if trace.created_at else "",
        }
        for trace in traces
    ]


@router.get("/conversations/{conv_id}/diagnoses", response_model=list[StructuredDiagnosisOut])
def list_conversation_diagnoses(conv_id: int, limit: int = 50, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return db.query(StructuredDiagnosis).filter(
        StructuredDiagnosis.conversation_id == conv_id,
    ).order_by(StructuredDiagnosis.created_at.desc()).limit(min(max(limit, 1), 200)).all()


@router.get("/messages/{message_id}/diagnoses", response_model=list[StructuredDiagnosisOut])
def list_message_diagnoses(message_id: int, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(404, "消息不存在")
    return db.query(StructuredDiagnosis).filter(
        StructuredDiagnosis.message_id == message_id,
    ).order_by(StructuredDiagnosis.created_at.desc()).all()


@router.post("/messages/{message_id}/diagnose", response_model=StructuredDiagnosisOut)
async def diagnose_message(message_id: int, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if not message or message.role != "user":
        raise HTTPException(404, "消息不存在")
    conv = db.get(Conversation, message.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    ai_msg = db.query(Message).filter(Message.parent_id == message.id).order_by(Message.created_at.desc()).first()
    if not ai_msg:
        raise HTTPException(404, "该消息尚无分析结果")
    speaker_char = db.query(Character).filter(Character.name == (message.character_name or "")).first()
    listener_char = db.get(Character, message.receiver_id) if message.receiver_id else None
    evidence_pack = build_evidence_pack(
        db,
        query_text=message.content,
        speaker=speaker_char,
        listener=listener_char,
        conversation=conv,
    )
    analysis_result = {
        "reply": ai_msg.content or "",
        "inner_monologue": ai_msg.inner_monologue or "",
        "emotion_label": ai_msg.emotion_label or "",
        "emotion_score": ai_msg.emotion_score or 0.0,
        "subtext": ai_msg.subtext or "",
        "psychological_tag": ai_msg.psychological_tag or "",
    }
    report = await _run_structured_diagnosis(
        db,
        conv=conv,
        user_msg=message,
        ai_msg=ai_msg,
        speaker_char=speaker_char,
        listener_char=listener_char,
        analysis_result=analysis_result,
        evidence_pack=evidence_pack,
    )
    if not report:
        raise HTTPException(502, "结构化诊断失败")
    return report


# ─── Stream Chat ──────────────────────────────────────────────────────────────

@router.post("/send")
async def send_message(body: ChatMessage, db: Session = Depends(get_db)):
    conv = db.get(Conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    if getattr(conv, "is_readonly", False):
        raise HTTPException(403, "只读导入会话不可继续发送消息")
    if not body.speaker:
        raise HTTPException(400, "请先选择发言角色")

    listeners, primary_listener = _select_primary_listener(
        db,
        body.speaker,
        body.active_characters or [],
        body.conversation_id,
    )
    listener_memory, characters_desc, speaker_state_block, listener_state_block, consistency_block, relationship_snapshot = _build_listener_memory(
        db,
        body.conversation_id,
        body.speaker,
        listeners,
        primary_listener,
    )
    speaker_char = db.query(Character).filter(Character.name == body.speaker).first()
    listener_char = db.get(Character, primary_listener.id) if primary_listener and getattr(primary_listener, "id", None) else None
    evidence_pack = build_evidence_pack(
        db,
        query_text=body.content,
        speaker=speaker_char,
        listener=listener_char,
        conversation=conv,
    )
    record_retrieval_trace(
        db,
        conversation=conv,
        speaker=speaker_char,
        listener=listener_char,
        query_text=body.content,
        evidence_pack=evidence_pack,
    )
    evidence_block = render_evidence_pack(evidence_pack)
    if evidence_block:
        listener_memory = "\n\n".join(block for block in [listener_memory, evidence_block] if block)
    db.commit()
    receiver_id = getattr(primary_listener, "id", None) if primary_listener else None
    receiver_name = getattr(primary_listener, "name", "") if primary_listener else ""
    next_message_index = _visible_messages_query(db, conv).count() + 1
    user_msg = Message(
        conversation_id=body.conversation_id,
        role="user",
        message_index=next_message_index,
        branch_id=getattr(conv, "active_branch_id", None),
        character_name=body.speaker,
        character_id=body.character_id,
        receiver_id=receiver_id,
        receiver_name=receiver_name,
        content=body.content,
        source_type="chat",
        readonly=False,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)
    _hydrate_context_from_db(db, conv, before_message_id=user_msg.id)

    async def event_generator():
        full_result = None
        async for chunk in orchestrator.stream_chat(
            conversation_id=body.conversation_id,
            speaker=body.speaker,
            content=body.content,
            scenario=conv.scenario,
            characters_desc=characters_desc,
            character_memory=listener_memory,
            speaker_state_block=speaker_state_block,
            listener_state_block=listener_state_block,
            consistency_block=consistency_block,
            listener_name=relationship_snapshot.get("primary_listener_name", ""),
        ):
            data = json.loads(chunk)
            if data["type"] == "done":
                full_result = data["result"]
            yield f"data: {chunk}\n\n"

        if full_result:
            strategy_payload = _parse_strategy_text(full_result.get("subtext"))
            emotion_payload = _parse_emotion_label(full_result.get("emotion_label"))
            user_msg.intent = strategy_payload.get("short_term") or strategy_payload.get("long_term")
            user_msg.strategy = strategy_payload.get("long_term") or strategy_payload.get("short_term")
            user_msg.emotion = emotion_payload.get("actual_label") or emotion_payload.get("surface_label")
            ai_msg = Message(
                conversation_id=body.conversation_id,
                role="assistant",
                message_index=next_message_index + 1,
                branch_id=getattr(conv, "active_branch_id", None),
                character_name="AI分析",
                receiver_id=receiver_id,
                receiver_name=receiver_name,
                content=full_result.get("reply", ""),
                inner_monologue=full_result.get("inner_monologue"),
                emotion_label=full_result.get("emotion_label"),
                emotion_score=full_result.get("emotion_score"),
                subtext=full_result.get("subtext"),
                psychological_tag=full_result.get("psychological_tag"),
                intent=user_msg.intent,
                strategy=user_msg.strategy,
                emotion=user_msg.emotion,
                source_type="analysis",
                readonly=False,
                parent_id=user_msg.id,
            )
            db.add(ai_msg)
            conv.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(ai_msg)
            report = await _run_structured_diagnosis(
                db,
                conv=conv,
                user_msg=user_msg,
                ai_msg=ai_msg,
                speaker_char=speaker_char,
                listener_char=listener_char,
                analysis_result=full_result,
                evidence_pack=evidence_pack,
            )
            if report:
                yield f"data: {json.dumps({'type': 'diagnosis', 'result': StructuredDiagnosisOut.model_validate(report).model_dump(mode='json')}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/messages/{message_id}/reanalyze", response_model=MessageOut)
async def reanalyze_message(message_id: int, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if not message or message.role != "user":
        raise HTTPException(404, "消息不存在")

    conv = db.get(Conversation, message.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    participant_rows = db.query(Message.character_name).filter(
        _visible_message_filter(conv),
        Message.role == "user",
        Message.character_name.isnot(None),
    ).distinct().all()
    active_characters = []
    for row in participant_rows:
        char_name = row[0]
        char = db.query(Character).filter(Character.name == char_name).first()
        active_characters.append(type("ActiveCharacter", (), {"id": char.id if char else None, "name": char_name}))

    listeners, primary_listener = _select_primary_listener(
        db,
        message.character_name or "",
        active_characters,
        conv.id,
    )
    listener_memory, characters_desc, speaker_state_block, listener_state_block, consistency_block, relationship_snapshot = _build_listener_memory(
        db,
        conv.id,
        message.character_name or "",
        listeners,
        primary_listener,
    )
    speaker_char = db.query(Character).filter(Character.name == (message.character_name or "")).first()
    listener_char = db.get(Character, primary_listener.id) if primary_listener and getattr(primary_listener, "id", None) else None
    evidence_pack = build_evidence_pack(
        db,
        query_text=message.content,
        speaker=speaker_char,
        listener=listener_char,
        conversation=conv,
    )
    record_retrieval_trace(
        db,
        conversation=conv,
        speaker=speaker_char,
        listener=listener_char,
        query_text=message.content,
        evidence_pack=evidence_pack,
    )
    evidence_block = render_evidence_pack(evidence_pack)
    if evidence_block:
        listener_memory = "\n\n".join(block for block in [listener_memory, evidence_block] if block)
    db.commit()

    result = None
    _hydrate_context_from_db(db, conv, before_message_id=message.id)
    async for chunk in orchestrator.stream_chat(
        conversation_id=conv.id,
        speaker=message.character_name or "",
        content=message.content,
        scenario=conv.scenario,
        characters_desc=characters_desc,
        character_memory=listener_memory,
        speaker_state_block=speaker_state_block,
        listener_state_block=listener_state_block,
        consistency_block=consistency_block,
        listener_name=relationship_snapshot.get("primary_listener_name", ""),
    ):
        data = json.loads(chunk)
        if data["type"] == "done":
            result = data["result"]

    if not result:
        raise HTTPException(500, "补全分析失败")

    ai_msg = db.query(Message).filter(Message.parent_id == message.id).first()
    if ai_msg:
        strategy_payload = _parse_strategy_text(result.get("subtext"))
        emotion_payload = _parse_emotion_label(result.get("emotion_label"))
        message.intent = strategy_payload.get("short_term") or strategy_payload.get("long_term")
        message.strategy = strategy_payload.get("long_term") or strategy_payload.get("short_term")
        message.emotion = emotion_payload.get("actual_label") or emotion_payload.get("surface_label")
        ai_msg.content = result.get("reply", "")
        ai_msg.inner_monologue = result.get("inner_monologue")
        ai_msg.emotion_label = result.get("emotion_label")
        ai_msg.emotion_score = result.get("emotion_score")
        ai_msg.subtext = result.get("subtext")
        ai_msg.psychological_tag = result.get("psychological_tag")
        ai_msg.intent = message.intent
        ai_msg.strategy = message.strategy
        ai_msg.emotion = message.emotion
    else:
        strategy_payload = _parse_strategy_text(result.get("subtext"))
        emotion_payload = _parse_emotion_label(result.get("emotion_label"))
        message.intent = strategy_payload.get("short_term") or strategy_payload.get("long_term")
        message.strategy = strategy_payload.get("long_term") or strategy_payload.get("short_term")
        message.emotion = emotion_payload.get("actual_label") or emotion_payload.get("surface_label")
        ai_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            message_index=(message.message_index or message.id or 0) + 1,
            branch_id=message.branch_id,
            character_name="AI分析",
            receiver_id=message.receiver_id,
            receiver_name=message.receiver_name,
            content=result.get("reply", ""),
            inner_monologue=result.get("inner_monologue"),
            emotion_label=result.get("emotion_label"),
            emotion_score=result.get("emotion_score"),
            subtext=result.get("subtext"),
            psychological_tag=result.get("psychological_tag"),
            intent=message.intent,
            strategy=message.strategy,
            emotion=message.emotion,
            source_type="analysis",
            parent_id=message.id,
        )
        db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)
    await _run_structured_diagnosis(
        db,
        conv=conv,
        user_msg=message,
        ai_msg=ai_msg,
        speaker_char=speaker_char,
        listener_char=listener_char,
        analysis_result=result,
        evidence_pack=evidence_pack,
    )
    return ai_msg


# ─── Branch ──────────────────────────────────────────────────────────────────

@router.post("/conversations/{conv_id}/branch/{message_id}")
def create_branch(conv_id: int, message_id: int, db: Session = Depends(get_db)):
    """从指定消息创建分支"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    if getattr(conv, "is_readonly", False):
        raise HTTPException(403, "只读导入会话不可创建分支")
    msg = db.get(Message, message_id)
    if not msg or msg.conversation_id != conv_id:
        raise HTTPException(404)
    visible = _visible_messages_query(db, conv).filter(Message.id == message_id).first()
    if not visible:
        raise HTTPException(404, "消息不在当前分支中")
    branch_id = f"branch-{message_id}-{int(datetime.utcnow().timestamp())}"
    conv.active_branch_id = branch_id
    conv.active_branch_point_id = message_id
    conv.updated_at = datetime.utcnow()
    db.commit()
    _hydrate_context_from_db(db, conv, include_message_id=message_id)
    return {
        "ok": True,
        "branch_id": branch_id,
        "branch_point": message_id,
        "context_reset": True,
    }


# ─── Emotion Curve ───────────────────────────────────────────────────────────

@router.get("/conversations/{conv_id}/emotion-curve/{character_name}")
async def get_emotion_curve(conv_id: int, character_name: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    messages = _visible_messages_query(db, conv).filter(
        Message.character_name == character_name,
    ).order_by(Message.message_index, Message.created_at, Message.id).limit(10).all()

    if not messages:
        return {"emotions": [], "trend": "stable", "turning_point": None}

    msg_texts = [m.content for m in messages]
    result = await orchestrator.analyze_emotion_curve(character_name, msg_texts)
    return result


@router.get("/conversations/{conv_id}/emotion-tension")
def get_emotion_tension(conv_id: int, source: str, target: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    analysis_messages = _visible_messages_query(db, conv).filter(
        Message.role == "assistant",
        Message.parent_id.isnot(None),
    ).order_by(Message.message_index, Message.created_at, Message.id).all()

    emotions = []
    deep_emotions = []
    strategy_trajectory = []
    dominant = []
    emotion_keywords = {}
    for analysis in analysis_messages:
        parent = db.get(Message, analysis.parent_id)
        if not parent or parent.character_name != source:
            continue
        if target and parent.receiver_name and parent.receiver_name != target:
            continue
        parsed = _parse_emotion_label(analysis.emotion_label)
        if not parsed:
            continue
        emotions.append(
            {
                "message_id": parent.id,
                "label": parsed.get("intended_label", ""),
                "score": round(parsed.get("intended_score", 0) / 10, 2),
                "target": target,
            }
        )
        if parsed.get("deep_label"):
            deep_emotions.append(
                {
                    "message_id": parent.id,
                    "label": parsed.get("deep_label", ""),
                    "score": round(parsed.get("deep_score", 0) / 10, 2),
                    "target": target,
                }
            )
            dominant.append(parsed["deep_label"])
            emotion_keywords[parsed["deep_label"]] = emotion_keywords.get(parsed["deep_label"], 0) + parsed.get("deep_score", 0)
        if parsed.get("intended_label"):
            emotion_keywords[parsed["intended_label"]] = emotion_keywords.get(parsed["intended_label"], 0) + parsed.get("intended_score", 0)
        strategy_lines = [line.strip() for line in (analysis.subtext or "").splitlines() if line.strip()]
        short_line = next((line.replace("短期策略：", "").strip() for line in strategy_lines if line.startswith("短期策略：")), "")
        long_line = next((line.replace("长期策略：", "").strip() for line in strategy_lines if line.startswith("长期策略：")), "")
        if short_line or long_line:
            strategy_trajectory.append(
                {
                    "message_id": parent.id,
                    "short_term": short_line,
                    "long_term": long_line,
                }
            )

    trend = "stable"
    if len(emotions) >= 2:
        first_score = emotions[0]["score"]
        last_score = emotions[-1]["score"]
        if last_score - first_score > 0.2:
            trend = "rising"
        elif first_score - last_score > 0.2:
            trend = "falling"
        elif max(e["score"] for e in emotions) - min(e["score"] for e in emotions) > 0.35:
            trend = "volatile"

    heatmap = []
    for item in emotions:
        deep_item = next((deep for deep in deep_emotions if deep["message_id"] == item["message_id"]), None)
        heatmap.append(
            {
                "message_id": item["message_id"],
                "target": target,
                "intended": item["score"],
                "actual": deep_item["score"] if deep_item else 0,
            }
        )

    return {
        "emotions": emotions,
        "deep_emotions": deep_emotions,
        "strategy_trajectory": strategy_trajectory,
        "emotion_heatmap": heatmap,
        "emotion_keywords": [
            {"label": label, "weight": weight}
            for label, weight in sorted(emotion_keywords.items(), key=lambda item: item[1], reverse=True)
        ][:12],
        "trend": trend,
        "turning_point": dominant[-1] if dominant else None,
    }


@router.post("/conversations/{conv_id}/archive")
def archive_conversation(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    role_names = payload.get("role_names") or []
    messages = _visible_messages_query(db, conv).order_by(Message.message_index, Message.created_at, Message.id).all()
    if not messages:
        return {"ok": True, "archived_roles": [], "observations_created": 0}

    archived_roles = []
    observations_created = 0
    role_map = {}
    for role_name in role_names:
        char = _find_or_create_character(db, role_name)
        role_map[role_name] = char
        archived_roles.append(role_name)

    for role_name, char in role_map.items():
        related_messages = [m for m in messages if m.character_name == role_name]
        if not related_messages:
            continue
        snippets = []
        for related in related_messages[-6:]:
            snippets.append(f"[{related.character_name}] {related.content}")
            analysis = db.query(Message).filter(Message.parent_id == related.id).first()
            if analysis:
                snippets.append(f"  - 分析内心独白：{analysis.inner_monologue or ''}")
                snippets.append(f"  - 分析情绪归因：{analysis.emotion_label or ''}")
                snippets.append(f"  - 分析策略动机：{analysis.subtext or ''}")
                snippets.append(f"  - 标签：{analysis.psychological_tag or ''}")
        summary = "\n".join(snippets)
        event = CharacterEvent(
            character_id=char.id,
            title=f"{SCENARIO_PRESETS.get(conv.scenario, {}).get('title', conv.scenario)}对话归档",
            description=summary[:2000],
            event_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            emotion_label=related_messages[-1].emotion_label if related_messages[-1].emotion_label else "",
            importance=4,
        )
        db.add(event)
        db.flush()
        graph_store.sync_event(event, char)
        evidence = _create_evidence_span(
            db,
            character_id=char.id,
            source_type="chat_archive",
            source_id=conv.id,
            conversation_id=conv.id,
            character_event_id=event.id,
            supports_type="event",
            supports_id=event.id,
            quote=summary[:1200],
            interpretation=f"会话归档事件：{event.title}",
            confidence=0.82,
            metadata={"role_name": role_name, "scenario": conv.scenario},
        )
        _create_memory_item(
            db,
            character_id=char.id,
            memory_type="fact",
            content=event.title,
            confidence=0.82,
            source="会话归档",
            evidence_ids=[evidence.id],
        )

    user_messages = [m for m in messages if m.role == "user" and m.parent_id is None]
    for user_message in user_messages:
        source_char = role_map.get(user_message.character_name or "")
        if not source_char:
            continue
        analysis = db.query(Message).filter(Message.parent_id == user_message.id).first()
        if not analysis:
            continue
        listeners = [name for name in role_names if name != user_message.character_name]
        if user_message.receiver_name and user_message.receiver_name in role_map:
            listeners = [user_message.receiver_name, *[name for name in listeners if name != user_message.receiver_name]]
        if not listeners:
            continue
        target_char = role_map.get(listeners[0])
        if not target_char:
            continue
        parsed = _parse_emotion_label(analysis.emotion_label)
        actual_polarity = _emotion_polarity(parsed.get("actual_label", ""))
        intended_polarity = _emotion_polarity(parsed.get("intended_label", ""))
        delta = 0.06 if actual_polarity == intended_polarity and actual_polarity != 0 else -0.04
        sentiment_target = max(-1.0, min(1.0, parsed.get("actual_score", 0) / 10 * actual_polarity))
        relationship = db.query(Relationship).filter(
            Relationship.source_id == source_char.id,
            Relationship.target_id == target_char.id,
        ).first()
        if not relationship:
            relationship = Relationship(
                source_id=source_char.id,
                target_id=target_char.id,
                rel_type="dynamic",
                strength=0.5,
                sentiment=0.0,
                description="由沉浸式对话归档自动生成",
                history=[],
            )
            db.add(relationship)
            db.flush()
            graph_store.sync_relationship(relationship, source_char, target_char)
        history = relationship.history or []
        history.append(
            {
                "date": datetime.utcnow().isoformat(),
                "strength": relationship.strength,
                "sentiment": relationship.sentiment,
            }
        )
        relationship.history = history
        relationship.strength = max(0.0, min(1.0, relationship.strength * 0.8 + (relationship.strength + delta) * 0.2))
        relationship.sentiment = max(-1.0, min(1.0, relationship.sentiment * 0.7 + sentiment_target * 0.3))
        relationship.updated_at = datetime.utcnow()
        db.flush()
        graph_store.sync_relationship(relationship, source_char, target_char)
        relationship_evidence = _create_evidence_span(
            db,
            character_id=source_char.id,
            source_type="chat_archive",
            source_id=conv.id,
            conversation_id=conv.id,
            message_id=user_message.id,
            relationship_id=relationship.id,
            supports_type="relationship",
            supports_id=relationship.id,
            quote=user_message.content,
            interpretation=analysis.subtext or analysis.emotion_label or "归档对话中的关系变化证据",
            confidence=0.76,
            metadata={
                "target_character_id": target_char.id,
                "delta": delta,
                "sentiment_target": sentiment_target,
            },
        )
        _create_memory_item(
            db,
            character_id=source_char.id,
            memory_type="relationship",
            content=f"对 {target_char.name} 的关系变化：强度 {round(relationship.strength, 2)}，情绪极性 {round(relationship.sentiment, 2)}",
            confidence=0.76,
            source="会话归档",
            evidence_ids=[relationship_evidence.id],
        )

        strategy_lines = [line.strip() for line in (analysis.subtext or "").splitlines() if line.strip()]
        long_term = next((line.replace("长期策略：", "").strip() for line in strategy_lines if line.startswith("长期策略：")), "")
        if long_term:
            existing_pattern = db.query(CharacterObservation).filter(
                CharacterObservation.character_id == source_char.id,
                CharacterObservation.field == "behavior_pattern",
                CharacterObservation.reason.contains(long_term),
            ).first()
            if not existing_pattern:
                obs = CharacterObservation(
                    character_id=source_char.id,
                    field="behavior_pattern",
                    old_value="",
                    new_value=long_term,
                    reason=f"归档提取到稳定行为模式：{long_term}",
                )
                db.add(obs)
                db.flush()
                behavior_evidence = _create_evidence_span(
                    db,
                    character_id=source_char.id,
                    source_type="chat_archive",
                    source_id=conv.id,
                    conversation_id=conv.id,
                    message_id=user_message.id,
                    observation_id=obs.id,
                    supports_type="behavior_pattern",
                    supports_id=obs.id,
                    quote=user_message.content,
                    interpretation=long_term,
                    confidence=0.74,
                    metadata={"receiver_name": target_char.name},
                )
                _create_memory_item(
                    db,
                    character_id=source_char.id,
                    memory_type="pragmatics",
                    content=long_term,
                    confidence=0.74,
                    source="会话归档",
                    evidence_ids=[behavior_evidence.id],
                )
                observations_created += 1

        if analysis.subtext and "矛盾" in analysis.subtext:
            observation = CharacterObservation(
                character_id=source_char.id,
                field="personality_tags",
                old_value=json.dumps(source_char.personality_tags or [], ensure_ascii=False),
                new_value=json.dumps(source_char.personality_tags or [], ensure_ascii=False),
                reason=f"归档时检测到潜在角色冲突：{analysis.subtext}",
            )
            db.add(observation)
            db.flush()
            conflict_evidence = _create_evidence_span(
                db,
                character_id=source_char.id,
                source_type="chat_archive",
                source_id=conv.id,
                conversation_id=conv.id,
                message_id=user_message.id,
                observation_id=observation.id,
                supports_type="personality_tags",
                supports_id=observation.id,
                quote=user_message.content,
                interpretation=analysis.subtext,
                confidence=0.68,
                metadata={"reason": "归档检测到潜在角色冲突"},
            )
            _create_memory_item(
                db,
                character_id=source_char.id,
                memory_type="diagnosis",
                content=analysis.subtext,
                confidence=0.68,
                source="会话归档",
                evidence_ids=[conflict_evidence.id],
            )
            observations_created += 1

    db.commit()
    return {
        "ok": True,
        "archived_roles": archived_roles,
        "observations_created": observations_created,
    }
