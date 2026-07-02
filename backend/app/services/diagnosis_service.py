"""结构化深度诊断（潜台词/人格信号/关系影响 + 证据 + Critic 复核）。
从 api/chat.py 抽出为独立服务：诊断按需触发（深度诊断按钮），不在核心读链路上。"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from ..harness.orchestrator import orchestrator
from ..harness.retrieval_engine import build_evidence_pack
from ..models.sql_models import AgentRun, Character, Conversation, Message, MessagePerspective, StructuredDiagnosis
from .analysis_store import create_memory_item

logger = logging.getLogger("import")


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


async def run_structured_diagnosis(
    db: Session,
    *,
    conv: Conversation,
    user_msg: Message,
    ai_msg: Message | None,
    speaker_char: Character | None,
    listener_char: Character | None,
    analysis_result: dict,
    evidence_pack: dict,
) -> StructuredDiagnosis | None:
    agent_run = AgentRun(
        workflow_name="structured_diagnosis",
        input_hash=f"message:{user_msg.id}:analysis:{getattr(ai_msg, 'id', None)}",
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
            analysis_message_id=ai_msg.id if ai_msg else None,
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
                create_memory_item(
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


async def run_diagnosis_for_message(db: Session, message: Message):
    """对一条 user 消息跑结构化深度诊断。供诊断端点触发。无视角/对话时返回 None。"""
    if not message or message.role != "user":
        return None
    conv = db.get(Conversation, message.conversation_id)
    if not conv:
        return None
    persps = db.query(MessagePerspective).filter(MessagePerspective.message_id == message.id).all()
    if not persps:
        return None
    speaker = (message.character_name or "").strip()
    receiver = (message.receiver_name or "").strip()
    observers = [p for p in persps if not (p.stance == "speaker" or p.viewer_name == speaker)]
    obs = (next((p for p in observers if p.viewer_name == receiver), None)
           or next((p for p in observers if p.is_primary), None)
           or (observers[0] if observers else persps[0]))
    speaker_char = db.query(Character).filter(Character.name == speaker).first()
    listener_char = db.get(Character, message.receiver_id) if message.receiver_id else None
    evidence_pack = build_evidence_pack(
        db, query_text=message.content, speaker=speaker_char, listener=listener_char, conversation=conv)
    analysis_result = {
        "reply": obs.suggested_reply or "",
        "inner_monologue": obs.inner_monologue or "",
        "emotion_label": obs.emotion_label or "",
        "emotion_score": obs.emotion_score or 0.0,
        "subtext": obs.subtext or "",
        "psychological_tag": obs.psychological_tag or "",
    }
    return await run_structured_diagnosis(
        db, conv=conv, user_msg=message, ai_msg=None,
        speaker_char=speaker_char, listener_char=listener_char,
        analysis_result=analysis_result, evidence_pack=evidence_pack)
