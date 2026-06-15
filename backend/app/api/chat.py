import asyncio
import json
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Conversation, ConversationState, Message, MessagePerspective, Character, Relationship, CharacterEvent, CharacterObservation,
    EvidenceSpan, InteractionUnit, MemoryItem, RetrievalTrace, StructuredDiagnosis, AgentRun,
)
from ..schemas import ChatMessage, ConversationCreate, ConversationUpdate, MessageOut, MessagePerspectiveOut, StructuredDiagnosisOut
from ..harness.orchestrator import orchestrator
from ..harness.context_manager import get_context, clear_context
from ..harness.state_engine import state_engine
from ..harness.consistency_engine import build_consistency_constraints
from ..harness.analysis_schema import extract_emotion_struct, extract_strategy_struct
from ..harness.config_loader import get_config
from ..harness.retrieval_engine import (
    build_evidence_pack,
    record_retrieval_trace,
    render_evidence_pack,
)
from ..harness.graph_store import graph_store
from ..services.relationships import find_pair_relationship
from ..services.identity import find_character_by_name
from ..services.profiles import render_extended_profile
from ..services.hypotheses import run_hypothesis_round
from .deps import get_db, SessionLocal

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


def _emotion_struct_for(message: Message) -> dict:
    """统一读取消息的情绪结构：优先 analysis_json，历史数据回退正则"""
    return extract_emotion_struct(getattr(message, "analysis_json", None), message.emotion_label)


def _strategy_struct_for(message: Message) -> dict:
    """统一读取消息的策略结构：优先 analysis_json，历史数据回退文本解析"""
    return extract_strategy_struct(getattr(message, "analysis_json", None), message.subtext)


def _apply_analysis_to_messages(user_msg: Message, ai_msg: Message, result: dict) -> None:
    """把 normalize 后的结构化分析结果写入消息行（含 legacy 展示列）"""
    emotions = result.get("emotions") or {}
    strategy = result.get("strategy") or {}
    deep_label = ((emotions.get("deep") or {}).get("label") or "").strip()
    surface_label = ((emotions.get("surface") or {}).get("label") or "").strip()
    user_msg.intent = strategy.get("short_term") or strategy.get("long_term")
    user_msg.strategy = strategy.get("long_term") or strategy.get("short_term")
    user_msg.emotion = deep_label or surface_label

    ai_msg.content = result.get("reply", "") or ai_msg.content
    ai_msg.inner_monologue = result.get("inner_monologue_text") or json.dumps(result.get("inner_monologue") or {}, ensure_ascii=False)
    ai_msg.emotion_label = result.get("emotion_label")
    ai_msg.emotion_score = result.get("emotion_score")
    ai_msg.subtext = result.get("subtext")
    ai_msg.psychological_tag = result.get("psychological_tag")
    ai_msg.analysis_json = {
        "emotions": result.get("emotions"),
        "strategy": result.get("strategy"),
        "tags": result.get("tags"),
        "inner_monologue": result.get("inner_monologue"),
    }
    ai_msg.intent = user_msg.intent
    ai_msg.strategy = user_msg.strategy
    ai_msg.emotion = user_msg.emotion


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
    # 本名 → 别名 两级命中，避免同一人物因称呼不同被归档成新角色
    char = find_character_by_name(db, name)
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
    relationship = find_pair_relationship(db, speaker_char.id, listener_char.id)
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


def _render_character_block(char: Character | None, name: str, header: str, speaker_char: Character | None, speaker_name: str, db: Session) -> str:
    parts = [f"【{name}】{header}"]
    if char:
        parts.append(f"  定位：{char.role or '未知'}｜动机：{char.motivation or '未知'}｜弱点：{char.weakness or '未知'}｜说话风格：{char.speaking_style or '未知'}")
        parts.append(f"  性格：{'、'.join(char.personality_tags or []) or '未知'}")
        ext = render_extended_profile(char.profile_json, limit_per_dim=2)
        if ext:
            parts.append("  立体档案：" + ext.replace("\n", "；"))
        if speaker_char and char.id != speaker_char.id:
            rel = find_pair_relationship(db, char.id, speaker_char.id)
            if rel:
                parts.append(f"  与{speaker_name}的关系：{rel.rel_type}（强度{round(rel.strength,2)}，情感{round(rel.sentiment,2)}）{(rel.description or '')[:80]}")
    else:
        parts.append("  （档案信息有限，请基于对话推断其立场）")
    return "\n".join(parts)


def _build_viewers_context(db: Session, speaker: str, listeners: list, primary_name: str, self_name: str = "") -> tuple[str, list[dict]]:
    """
    构建多视角上下文：发言者本人（用于自述分析）+ 在场每个旁观角色（用于解读分析）。
    self_name 给定时，把「我」本人这一旁观视角重点标出，让模型给出"我该怎么接"的多策略。
    返回 (viewers_block 文本, [{name, id} ...] 仅旁观者，用于 primary 判断)。
    """
    speaker_char = db.query(Character).filter(Character.name == speaker).first()
    blocks: list[str] = [
        _render_character_block(speaker_char, speaker, "（发言者本人——请分析他说这句话的真实目的）", speaker_char, speaker, db)
    ]
    viewers: list[dict] = []
    for listener in listeners or []:
        name = getattr(listener, "name", "")
        if not name or name == speaker:
            continue
        char = db.get(Character, listener.id) if getattr(listener, "id", None) else db.query(Character).filter(Character.name == name).first()
        viewers.append({"name": name, "id": char.id if char else None})
        if self_name and name == self_name:
            header = "（这是「我」本人——请重点给出我该如何回应对方这句话的 2-3 个不同策略 moves）"
        elif name == primary_name:
            header = "（主要接收方——会回应）"
        else:
            header = "（旁观者）"
        blocks.append(_render_character_block(char, name, header, speaker_char, speaker, db))
    return "\n\n".join(blocks), viewers


_GROUNDING_DROP = set(" \t\r\n，。！？、；：…·（）()—-~～!?,.:;\"'“”‘’")


def _deterministic_grounding(evidence: str, utterance: str, declared_grounded, confidence):
    """确定性接地核查（信任底线第一层，免费且永远在线）：
    证据片段必须真出现在发言原文里，否则判为「推测」、置信封顶 0.45。返回 (grounded, confidence)。"""
    strip = lambda s: "".join(c for c in (s or "") if c not in _GROUNDING_DROP)
    utter_norm = strip(utterance)
    ev_norm = strip(evidence)
    grounded = bool(ev_norm) and len(ev_norm) >= 2 and ev_norm in utter_norm
    if declared_grounded is False:
        grounded = False
    if not grounded and confidence is not None:
        confidence = min(confidence, 0.45)
    return grounded, confidence


def _perspective_claim_text(analysis_json: dict) -> str:
    """把某视角的内心独白拼成一句，供 critic 复核其判断是否过度推断。"""
    inner = (analysis_json or {}).get("inner_monologue") or {}
    if isinstance(inner, dict):
        parts = [str(inner.get(k) or "").strip() for k in ("first_reaction", "defense", "tendency")]
        return " / ".join(p for p in parts if p)
    return str(inner or "").strip()


def _apply_critic_review(analysis_json: dict, review_item: dict) -> dict:
    """把一条 LLM 复核结果并入某视角的 analysis_json（信任底线第二层）：
    不抹掉原判断，叠加 critic 注记；置信只能调低、引用不实/过度推断则标 grounded=false。返回新 dict。"""
    aj = dict(analysis_json or {})
    issues = [str(i).strip() for i in (review_item.get("issues") or []) if str(i).strip()]
    verdict = (review_item.get("verdict") or "").strip().lower() or ("downgraded" if issues else "approved")
    cur = aj.get("confidence")
    rev = review_item.get("confidence")
    rev = float(rev) if isinstance(rev, (int, float)) else None
    # critic 只能更保守：取原值与复核值的较低者
    if rev is not None:
        aj["confidence"] = round(min(cur, rev) if isinstance(cur, (int, float)) else rev, 2)
    if review_item.get("grounded") is False:
        aj["grounded"] = False
        if isinstance(aj.get("confidence"), (int, float)):
            aj["confidence"] = min(aj["confidence"], 0.45)
    aj["critic"] = {
        "verdict": verdict,
        "issues": issues[:5],
        "revised_subtext": (review_item.get("revised_subtext") or "").strip()[:300],
        "revised_inner_monologue": (review_item.get("revised_inner_monologue") or "").strip()[:400],
    }
    return aj


def _save_perspectives(db: Session, conv_id: int, user_msg: Message, speaker: str, perspectives: list, primary_name: str, primary_reply: str = "") -> int:
    """保存一条发言的多视角分析（先清旧视角，再写新视角）。
    每个旁观视角带"建议回答"；主要接收方的建议回答用流式生成的自然回复。"""
    db.query(MessagePerspective).filter(MessagePerspective.message_id == user_msg.id).delete(synchronize_session=False)
    saved = 0
    for persp in perspectives or []:
        viewer = (persp.get("viewer") or "").strip()
        if not viewer:
            continue
        stance = "speaker" if (persp.get("stance") == "speaker" or viewer == speaker) else "observer"
        is_primary = (stance == "observer" and viewer == primary_name)
        viewer_char = db.query(Character).filter(Character.name == viewer).first()
        emotions = persp.get("emotions") or {}
        # 多策略应对：清洗成 [{label, reply, consequence}]
        moves = []
        for move in (persp.get("moves") or []):
            if not isinstance(move, dict):
                continue
            reply_text = (move.get("reply") or "").strip()
            if not reply_text:
                continue
            moves.append({
                "label": (move.get("label") or "").strip()[:40],
                "reply": reply_text[:500],
                "consequence": (move.get("consequence") or "").strip()[:300],
            })
        # 旁观者的建议回答：主要接收方用流式自然回复；否则用该视角自带 reply，再退到首个策略话术
        suggested = ""
        if stance == "observer":
            suggested = (
                primary_reply if is_primary and primary_reply
                else (persp.get("reply") or (moves[0]["reply"] if moves else ""))
            ).strip()
        # ── 自评-修订第一层：确定性接地核查（信任底线，免费且永远在线）──
        # 证据必须真出现在发言原文里，否则判为「推测」、置信封顶 0.45，不靠模型自觉
        # （更深一层「LLM 复核员」由 /messages/{id}/critique-analysis 端点按需触发）
        evidence = (persp.get("evidence") or "").strip()
        raw_conf = persp.get("confidence")
        confidence = float(raw_conf) if isinstance(raw_conf, (int, float)) else None
        grounded, confidence = _deterministic_grounding(evidence, user_msg.content, persp.get("grounded"), confidence)
        db.add(MessagePerspective(
            conversation_id=conv_id,
            message_id=user_msg.id,
            speaker_name=speaker,
            viewer_character_id=viewer_char.id if viewer_char else None,
            viewer_name=viewer,
            stance=stance,
            is_primary=is_primary,
            suggested_reply=suggested[:500],
            inner_monologue=persp.get("inner_monologue_text") or "",
            emotion_label=persp.get("emotion_label") or "",
            emotion_score=persp.get("emotion_score"),
            subtext=persp.get("subtext") or "",
            psychological_tag=persp.get("psychological_tag") or "",
            analysis_json={
                "emotions": emotions,
                "strategy": persp.get("strategy"),
                "tags": persp.get("tags"),
                "inner_monologue": persp.get("inner_monologue"),
                "moves": moves,
                "evidence": evidence[:300],
                "confidence": confidence,
                "grounded": grounded,
            },
        ))
        saved += 1
    return saved


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
            relationship = find_pair_relationship(db, speaker_char.id, listener.id)
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
            # 立体人物模型注入：价值观/恐惧/人际模式/语言指纹/矛盾性——让 AI 扮演的不是几行人设而是完整的人
            extended_block = render_extended_profile(primary_char.profile_json)
            if extended_block:
                memory_parts.append(f"接收方立体档案：\n{extended_block}")
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
                db,
                conv_id,
                primary_char.name,
                listener_profile,
                relationship_snapshot,
                _list_behavior_patterns(db, primary_char.id),
            )
            listener_state_block = state_engine.render_state_block(primary_char.name, listener_state)
            if speaker_char:
                speaker_state = state_engine.bootstrap_state(
                    db,
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
    ctx.set_summary(getattr(conv, "context_summary", "") or "")
    summary_until = int(getattr(conv, "summary_until_index", 0) or 0)
    query = _visible_messages_query(db, conv)
    if include_message_id:
        query = query.filter(Message.id <= include_message_id)
    elif before_message_id:
        query = query.filter(Message.id < before_message_id)
    if summary_until:
        # 已被滚动摘要覆盖的旧消息不再重复注入原文
        query = query.filter(Message.message_index > summary_until)
    rows = query.order_by(Message.message_index, Message.created_at, Message.id).all()
    for row in rows[-60:]:
        display_name = row.character_name or row.role
        if row.role == "assistant" and (not row.character_name or row.character_name == "AI分析") and row.receiver_name:
            display_name = f"{row.receiver_name}的回复"
        ctx.add(row.role, row.content, {"character_name": display_name})


async def _run_session_hypothesis_rounds(conv_id: int) -> None:
    """会话证据驱动的特质假设演化（fire-and-forget 后台任务）：
    取最近的用户发言，按角色分组跑假设轮——对话越多，系统对人物的理解越深。"""
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        if not conv:
            return
        messages = _visible_messages_query(db, conv).filter(
            Message.role == "user",
        ).order_by(Message.message_index.desc(), Message.id.desc()).limit(24).all()
        by_char: dict[int, list[str]] = {}
        for message in reversed(messages):
            if message.character_id:
                by_char.setdefault(message.character_id, []).append(
                    f"对{message.receiver_name or '？'}说：「{(message.content or '')[:120]}」"
                )
        for char_id, texts in by_char.items():
            if len(texts) < 3:
                continue
            char = db.get(Character, char_id)
            if char:
                await run_hypothesis_round(db, char, texts)
    except Exception:
        db.rollback()
    finally:
        db.close()


async def _refresh_context_summary(conv_id: int) -> None:
    """滚动摘要：把超出窗口的旧消息压缩为剧情纪要（fire-and-forget 后台任务）"""
    db = SessionLocal()
    try:
        conv = db.get(Conversation, conv_id)
        if not conv:
            return
        cfg = get_config().get("context", {}) or {}
        trigger = int(cfg.get("summary_trigger_messages", 40))
        keep_recent = int(cfg.get("summary_keep_recent", 20))
        summary_until = int(getattr(conv, "summary_until_index", 0) or 0)
        rows = _visible_messages_query(db, conv).filter(
            Message.message_index > summary_until,
        ).order_by(Message.message_index, Message.created_at, Message.id).all()
        if len(rows) <= trigger:
            return
        to_summarize = rows[:-keep_recent] if keep_recent else rows
        if not to_summarize:
            return
        lines = []
        for row in to_summarize:
            name = row.character_name or row.role
            lines.append(f"[{name}] {row.content}")
        dialogue = "\n".join(lines)[:9000]
        summary = await orchestrator.summarize_context(conv.context_summary or "", dialogue)
        if not (summary or "").strip():
            return
        conv.context_summary = summary.strip()[:4000]
        conv.summary_until_index = int(to_summarize[-1].message_index or summary_until)
        db.commit()
        clear_context(conv_id)
    except Exception:
        db.rollback()
    finally:
        db.close()


# ─── Conversations ────────────────────────────────────────────────────────────

def _compose_scene(conv: Conversation) -> str:
    """把场景预设标题 + 用户手写背景说明合成为注入分析的场景文本。
    单纯一个预设标签没有意义，背景说明才是真正约束分析的上下文。"""
    label = SCENARIO_PRESETS.get(conv.scenario, {}).get("title", "") or conv.scenario or "通用对话"
    brief = (getattr(conv, "scene_brief", "") or "").strip()
    if brief:
        return f"{label}。背景设定：{brief}"
    return label


def _conversation_payload(c: Conversation) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "scenario": c.scenario,
        "scene_brief": getattr(c, "scene_brief", "") or "",
        "self_name": getattr(c, "self_name", "") or "",
        "goal": getattr(c, "goal", "") or "",
        "updated_at": c.updated_at,
        "is_readonly": bool(getattr(c, "is_readonly", False)),
        "source_import_file_id": getattr(c, "source_import_file_id", None),
        "active_branch_id": getattr(c, "active_branch_id", None),
        "active_branch_point_id": getattr(c, "active_branch_point_id", None),
        "participants": list(getattr(c, "participants", None) or []),
    }


@router.get("/conversations")
def list_conversations(limit: int = 50, db: Session = Depends(get_db)):
    convs = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [_conversation_payload(c) for c in convs]


@router.post("/conversations")
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    conv = Conversation(title=body.title, scenario=body.scenario, scene_brief=(body.scene_brief or "").strip()[:2000])
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conversation_payload(conv)


@router.patch("/conversations/{conv_id}")
def update_conversation(conv_id: int, body: ConversationUpdate, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    if body.title is not None:
        conv.title = body.title.strip()[:200] or conv.title
    if body.scenario is not None and body.scenario.strip():
        conv.scenario = body.scenario.strip()[:100]
    if body.scene_brief is not None:
        conv.scene_brief = body.scene_brief.strip()[:2000]
    if body.self_name is not None:
        conv.self_name = body.self_name.strip()[:100]
    if body.goal is not None:
        conv.goal = body.goal.strip()[:500]
    if body.participants is not None:
        conv.participants = [
            {"id": item.id, "name": item.name.strip()}
            for item in body.participants
            if item.name and item.name.strip()
        ]
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return _conversation_payload(conv)


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    # 显式清理所有关联数据，避免孤儿行
    db.query(EvidenceSpan).filter(EvidenceSpan.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(RetrievalTrace).filter(RetrievalTrace.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(MessagePerspective).filter(MessagePerspective.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(ConversationState).filter(ConversationState.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(Message).filter_by(conversation_id=conv_id).delete(synchronize_session=False)
    db.delete(conv)
    db.commit()
    clear_context(conv_id)
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


@router.get("/conversations/{conv_id}/perspectives")
def get_conversation_perspectives(conv_id: int, db: Session = Depends(get_db)):
    """返回该会话全部多视角分析，按发言消息 id 分组：{message_id: [perspective...]}"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    # 排序：发言者自述优先，其次主要接收方，再其余旁观者
    rows = db.query(MessagePerspective).filter(
        MessagePerspective.conversation_id == conv_id,
    ).order_by(
        (MessagePerspective.stance == "speaker").desc(),
        MessagePerspective.is_primary.desc(),
        MessagePerspective.id,
    ).all()
    grouped: dict[int, list] = {}
    for row in rows:
        grouped.setdefault(row.message_id, []).append(
            MessagePerspectiveOut.model_validate(row).model_dump(mode="json")
        )
    return grouped


# 情绪向量英文键 → 中文展示标签
_EMOTION_VEC_LABELS = {
    "calm": "平静", "guarded": "戒备", "attachment": "亲近", "fear": "恐惧", "anger": "压抑/愤怒",
}


@router.get("/conversations/{conv_id}/states")
def get_conversation_states(conv_id: int, db: Session = Depends(get_db)):
    """返回该会话中各在场角色的当前心理状态卡（来自持续状态机，对话越多越准）。
    情绪面板上半部分用它呈现「各方此刻状态」。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    rows = db.query(ConversationState).filter(
        ConversationState.conversation_id == conv_id,
    ).order_by(ConversationState.updated_at.desc()).all()

    cards = []
    for row in rows:
        st = state_engine.get_state(db, conv_id, row.character_name)
        vec = st.emotion_vector or {}
        # 头条情绪：除“平静”外强度最高的那一项；都很低则归为平静
        salient = {k: v for k, v in vec.items() if k != "calm"}
        if salient:
            top_key = max(salient, key=lambda k: salient[k])
            top_val = float(salient[top_key])
        else:
            top_key, top_val = "calm", float(vec.get("calm", 0.5))
        if top_val < 0.34:
            top_key, top_val = "calm", float(vec.get("calm", 0.5))
        cards.append({
            "name": row.character_name,
            "headline_emotion": _EMOTION_VEC_LABELS.get(top_key, top_key),
            "headline_score": round(top_val, 2),
            "emotion_vector": [
                {"label": _EMOTION_VEC_LABELS.get(k, k), "score": round(float(v), 2)}
                for k, v in sorted(vec.items(), key=lambda kv: kv[1], reverse=True)
            ],
            "current_goal": st.current_goal or "",
            "defense_style": st.defense_style or "",
            "last_intent": st.last_intent or "",
            "last_strategy": st.last_strategy or "",
            "beliefs": [{"target": k, "belief": v} for k, v in (st.beliefs or {}).items()],
            "stable_traits": st.stable_traits or [],
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        })
    return {"conversation_id": conv_id, "states": cards}


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
    # 用户手动指定接收方时优先生效
    if body.receiver_name:
        explicit = next((item for item in listeners if item.name == body.receiver_name), None)
        if explicit:
            primary_listener = explicit
    listener_memory, characters_desc, speaker_state_block, listener_state_block, consistency_block, relationship_snapshot = _build_listener_memory(
        db,
        body.conversation_id,
        body.speaker,
        listeners,
        primary_listener,
    )
    speaker_char = db.query(Character).filter(Character.name == body.speaker).first()
    listener_char = db.get(Character, primary_listener.id) if primary_listener and getattr(primary_listener, "id", None) else None
    primary_name = getattr(primary_listener, "name", "") if primary_listener else ""
    viewers_block, _viewers = _build_viewers_context(db, body.speaker, listeners, primary_name, getattr(conv, "self_name", "") or "")
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
            scenario=_compose_scene(conv),
            characters_desc=characters_desc,
            character_memory=listener_memory,
            speaker_state_block=speaker_state_block,
            listener_state_block=listener_state_block,
            consistency_block=consistency_block,
            viewers_block=viewers_block,
            goal=getattr(conv, "goal", "") or "",
        ):
            data = json.loads(chunk)
            if data["type"] == "done":
                full_result = data["result"]
            yield f"data: {chunk}\n\n"

        if full_result:
            # AI 即接收方角色：assistant 消息以接收方身份入库
            ai_msg = Message(
                conversation_id=body.conversation_id,
                role="assistant",
                message_index=next_message_index + 1,
                branch_id=getattr(conv, "active_branch_id", None),
                character_id=receiver_id,
                character_name=receiver_name or "AI分析",
                receiver_id=body.character_id,
                receiver_name=body.speaker,
                content=full_result.get("reply", ""),
                source_type="analysis",
                readonly=False,
                parent_id=user_msg.id,
            )
            _apply_analysis_to_messages(user_msg, ai_msg, full_result)
            db.add(ai_msg)
            # 多视角分析落库（在场每个旁观角色对这句话的独立分析 + 建议回答）
            _save_perspectives(db, conv.id, user_msg, body.speaker, full_result.get("perspectives") or [], primary_name, full_result.get("reply") or "")
            # 演化双方心理状态（持久化，下一轮注入）
            listener_display = relationship_snapshot.get("primary_listener_name", "")
            if listener_display:
                state_engine.update_after_analysis(
                    db, conv.id, body.speaker, listener_display, full_result,
                )
            conv.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(ai_msg)
            yield f"data: {json.dumps({'type': 'saved', 'user_message_id': user_msg.id, 'ai_message_id': ai_msg.id}, ensure_ascii=False)}\n\n"
            # 滚动摘要按需后台刷新（深度诊断已改为消息上的按钮触发，不再拖慢主链路）
            asyncio.create_task(_refresh_context_summary(conv.id))
            # 每累积 20 条消息自动演化一轮特质假设——对话即建模
            if next_message_index > 0 and (next_message_index + 1) % 20 == 0:
                asyncio.create_task(_run_session_hypothesis_rounds(conv.id))

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _reanalyze_user_message(db: Session, message: Message) -> Message:
    """对一条 user 消息重建完整分析层（补全分析 / 编辑后重分析共用）"""
    conv = db.get(Conversation, message.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    participant_rows = db.query(Message.character_name).filter(
        _visible_message_filter(conv),
        Message.role == "user",
        Message.character_name.isnot(None),
    ).distinct().all()
    active_characters = []
    seen_names = set()
    for row in participant_rows:
        char_name = row[0]
        char = db.query(Character).filter(Character.name == char_name).first()
        active_characters.append(type("ActiveCharacter", (), {"id": char.id if char else None, "name": char_name}))
        seen_names.add(char_name)
    # 「我」即便此前还没发过言，也必须作为旁观者在场，否则对方发言拿不到「我该怎么接」
    self_nm = (getattr(conv, "self_name", "") or "").strip()
    if self_nm and self_nm not in seen_names and self_nm != (message.character_name or ""):
        self_char = db.query(Character).filter(Character.name == self_nm).first()
        active_characters.append(type("ActiveCharacter", (), {"id": self_char.id if self_char else None, "name": self_nm}))

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
    primary_name = getattr(primary_listener, "name", "") if primary_listener else ""
    viewers_block, _viewers = _build_viewers_context(db, message.character_name or "", listeners, primary_name, getattr(conv, "self_name", "") or "")
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
        scenario=_compose_scene(conv),
        characters_desc=characters_desc,
        character_memory=listener_memory,
        speaker_state_block=speaker_state_block,
        listener_state_block=listener_state_block,
        consistency_block=consistency_block,
        viewers_block=viewers_block,
        goal=getattr(conv, "goal", "") or "",
    ):
        data = json.loads(chunk)
        if data["type"] == "done":
            result = data["result"]

    if not result:
        raise HTTPException(500, "补全分析失败")
    # 重建多视角分析
    _save_perspectives(db, conv.id, message, message.character_name or "", result.get("perspectives") or [], primary_name, result.get("reply") or "")

    ai_msg = db.query(Message).filter(Message.parent_id == message.id).first()
    if not ai_msg:
        ai_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            message_index=(message.message_index or message.id or 0) + 1,
            branch_id=message.branch_id,
            character_id=message.receiver_id,
            character_name=message.receiver_name or "AI分析",
            receiver_id=message.character_id,
            receiver_name=message.character_name,
            content=result.get("reply", ""),
            source_type="analysis",
            parent_id=message.id,
        )
        db.add(ai_msg)
    _apply_analysis_to_messages(message, ai_msg, result)
    db.commit()
    db.refresh(ai_msg)
    return ai_msg


@router.post("/messages/{message_id}/reanalyze", response_model=MessageOut)
async def reanalyze_message(message_id: int, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if not message or message.role != "user":
        raise HTTPException(404, "消息不存在")
    return await _reanalyze_user_message(db, message)


@router.post("/messages/{message_id}/critique-analysis")
async def critique_message_analysis(message_id: int, db: Session = Depends(get_db)):
    """对一条发言已存的多视角分析跑一轮 LLM 复核(critic-revise)：逐视角审查过度推断/脑补/引用不实，
    下调置信、标推测、给保守修订，并透明回传抓到的问题。这是确定性接地核查之上的更深一层。"""
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(404, "消息不存在")
    rows = db.query(MessagePerspective).filter(MessagePerspective.message_id == message_id).all()
    if not rows:
        raise HTTPException(400, "这条消息还没有可复核的分析")
    conv = db.get(Conversation, message.conversation_id)

    # 复核证据：与分析同源（对方原话 + 语义召回证据），critic 只能用这些，不许臆造
    evidence_block = ""
    try:
        speaker_char = db.query(Character).filter(Character.name == (message.character_name or "")).first()
        pack = build_evidence_pack(db, query_text=message.content, speaker=speaker_char, listener=None, conversation=conv)
        evidence_block = render_evidence_pack(pack)
    except Exception:
        evidence_block = ""

    payload = [
        {
            "viewer": row.viewer_name,
            "stance": row.stance,
            "evidence": ((row.analysis_json or {}).get("evidence") or "")[:300],
            "confidence": (row.analysis_json or {}).get("confidence"),
            "subtext": row.subtext or "",
            "claim": _perspective_claim_text(row.analysis_json or {}),
        }
        for row in rows
    ]
    try:
        review = await orchestrator.critique_perspectives(message.content, payload, evidence_block)
    except Exception as exc:
        raise HTTPException(502, f"复核调用失败：{exc}")
    by_viewer = {
        (item.get("viewer") or "").strip(): item
        for item in (review.get("reviewed") or [])
        if isinstance(item, dict) and (item.get("viewer") or "").strip()
    }

    corrections = []
    for row in rows:
        item = by_viewer.get((row.viewer_name or "").strip())
        if not item:
            continue
        before = (row.analysis_json or {}).get("confidence")
        row.analysis_json = _apply_critic_review(row.analysis_json, item)  # 重新赋值新 dict，触发脏标记
        critic = row.analysis_json["critic"]
        corrections.append({
            "viewer": row.viewer_name,
            "stance": row.stance,
            "verdict": critic["verdict"],
            "issues": critic["issues"],
            "confidence_before": round(before, 2) if isinstance(before, (int, float)) else None,
            "confidence_after": row.analysis_json.get("confidence"),
        })
    db.commit()
    downgraded = sum(1 for c in corrections if c["verdict"] in ("downgraded", "softened"))
    return {
        "message_id": message_id,
        "overall": (review.get("overall") or "").strip(),
        "reviewed_count": len(corrections),
        "flagged_count": downgraded,
        "corrections": corrections,
    }


@router.post("/conversations/{conv_id}/generate-advice")
async def generate_conversation_advice(conv_id: int, limit: int = 8, db: Session = Depends(get_db)):
    """为「对方」的每句发言批量生成「洞察(他) ‖ 行动(我)」多视角分析（导入的真实聊天用）。
    需先指定 self_name；分批处理、可重复调用直到 remaining=0。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    self_name = (getattr(conv, "self_name", "") or "").strip()
    if not self_name:
        raise HTTPException(400, "请先指定「我」是谁，才能生成应对建议")

    done_ids = {
        row[0] for row in db.query(MessagePerspective.message_id)
        .filter(MessagePerspective.conversation_id == conv_id).distinct().all()
    }
    pending = [
        m for m in _visible_messages_query(db, conv)
        .filter(Message.role == "user")
        .order_by(Message.message_index, Message.created_at, Message.id).all()
        if (m.character_name or "").strip() and m.character_name != self_name and m.id not in done_ids
    ]
    batch = pending[:max(1, min(limit, 30))]
    generated = 0
    for message in batch:
        try:
            await _reanalyze_user_message(db, message)
            generated += 1
        except Exception:
            db.rollback()
    remaining = max(0, len(pending) - generated)
    return {"ok": True, "generated": generated, "remaining": remaining, "self_name": self_name}


@router.put("/messages/{message_id}", response_model=MessageOut)
async def edit_message(message_id: int, payload: dict, db: Session = Depends(get_db)):
    """编辑对话内容并重新分析（含导入的只读消息——编辑修正不算继续发言）"""
    message = db.get(Message, message_id)
    if not message or message.role != "user":
        raise HTTPException(404, "消息不存在")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "内容不能为空")
    message.content = content
    db.commit()
    # 同步更新导入交互单元的原文，保持证据一致
    db.query(InteractionUnit).filter(
        InteractionUnit.conversation_message_id == message.id,
    ).update({"content": content, "source_text_snippet": content[:500]}, synchronize_session=False)
    db.commit()
    return await _reanalyze_user_message(db, message)


# ─── Branch ──────────────────────────────────────────────────────────────────

def _branch_point_from_id(branch_id: str | None) -> int | None:
    matched = re.match(r"branch-(\d+)-", branch_id or "")
    return int(matched.group(1)) if matched else None


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


@router.get("/conversations/{conv_id}/branches")
def list_branches(conv_id: int, db: Session = Depends(get_db)):
    """列出会话的全部分支（含主线）"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    rows = db.query(
        Message.branch_id,
        func.count(Message.id),
        func.min(Message.created_at),
    ).filter(
        Message.conversation_id == conv_id,
        Message.branch_id.isnot(None),
    ).group_by(Message.branch_id).all()
    branches = [
        {
            "branch_id": branch_id,
            "branch_point_id": _branch_point_from_id(branch_id),
            "message_count": count,
            "created_at": created_at.isoformat() if created_at else "",
        }
        for branch_id, count, created_at in rows
    ]
    branches.sort(key=lambda item: item["created_at"])
    return {
        "active_branch_id": getattr(conv, "active_branch_id", None),
        "branches": branches,
    }


@router.post("/conversations/{conv_id}/switch-branch")
def switch_branch(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    """切换分支；branch_id 为空时回到主线"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    branch_id = (payload.get("branch_id") or "").strip() or None
    if branch_id is None:
        conv.active_branch_id = None
        conv.active_branch_point_id = None
    else:
        exists = db.query(Message).filter(
            Message.conversation_id == conv_id,
            Message.branch_id == branch_id,
        ).first()
        if not exists:
            raise HTTPException(404, "分支不存在")
        conv.active_branch_id = branch_id
        conv.active_branch_point_id = _branch_point_from_id(branch_id)
    conv.updated_at = datetime.utcnow()
    db.commit()
    _hydrate_context_from_db(db, conv)
    return {
        "ok": True,
        "active_branch_id": conv.active_branch_id,
        "active_branch_point_id": conv.active_branch_point_id,
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


# 关系维度推导用的情绪/策略词典（确定性映射，透明可查）
_REL_WARM = {"信任","亲近","安心","依恋","喜悦","放松","温暖","感激","亲密","信赖","欣慰","期待","开心","愉快","亲昵","关心","眷恋"}
_REL_GUARD = {"警惕","怀疑","防御","不安","焦虑","恐惧","愤怒","失望","冷漠","戒备","敌意","委屈","尴尬","不满","紧张","烦躁","抗拒","厌烦","疏离"}
_REL_PUSH = ("施压","主导","质问","逼问","逼迫","命令","挑衅","试探","反将","掌控","压制","要求","催促","质疑","追问","摊牌")
_REL_YIELD = ("退让","讨好","迎合","妥协","回避","拖延","顺从","示弱","安抚","解释","赔笑","转移")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@router.get("/conversations/{conv_id}/relationship-trajectory")
def get_relationship_trajectory(conv_id: int, source: str, target: str, db: Session = Depends(get_db)):
    """关系多维走势（信任/亲密/主动权/张力随对话推进）+ 转折点。
    不调用 LLM——从已存的逐句结构化分析里确定性推导，透明可复核。
    主动权(dominance) 取 source 相对 target 的主动权（0.5=对等）。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    analysis_messages = _visible_messages_query(db, conv).filter(
        Message.role == "assistant",
        Message.parent_id.isnot(None),
    ).order_by(Message.message_index, Message.created_at, Message.id).all()

    pair = {source, target}
    trust, intimacy, tension, dominance = 0.5, 0.45, 0.3, 0.5
    points, turning = [], []
    prev = None
    for analysis in analysis_messages:
        parent = db.get(Message, analysis.parent_id)
        if not parent:
            continue
        speaker = (parent.character_name or "").strip()
        receiver = (parent.receiver_name or "").strip()
        # 只取这一对人之间的来回
        if speaker not in pair or (receiver and receiver not in pair):
            continue
        emo = _emotion_struct_for(analysis)
        strat = _strategy_struct_for(analysis)
        labels = {(emo.get(k) or {}).get("label", "") for k in ("surface", "deep", "suppressed")}
        labels.discard("")
        if not labels and not (emo.get("intended") or {}).get("label"):
            continue
        warm = sum(1 for w in labels if any(t in w for t in _REL_WARM))
        guard = sum(1 for w in labels if any(t in w for t in _REL_GUARD))
        net_warm = warm - guard
        strat_text = (strat.get("short_term", "") + strat.get("long_term", "") + (emo.get("intended") or {}).get("label", ""))
        push = any(k in strat_text for k in _REL_PUSH)
        yield_ = any(k in strat_text for k in _REL_YIELD)
        intended_score = float((emo.get("intended") or {}).get("score", 0)) / 10.0

        # 维度演化（逐步累积 + 边界裁剪 + EMA 平滑）
        trust = _clamp01(trust + net_warm * 0.10 - (0.06 if guard else 0))
        intimacy = _clamp01(intimacy + (warm * 0.09) - (guard * 0.05))
        tension = _clamp01(tension * 0.6 + intended_score * 0.4 + (0.05 if guard else 0))
        dom_delta = 0.0
        if push: dom_delta += 0.12 if speaker == source else -0.12
        if yield_: dom_delta += -0.10 if speaker == source else 0.10
        dominance = _clamp01(dominance + dom_delta)

        point = {
            "message_id": parent.id, "index": len(points) + 1, "speaker": speaker,
            "snippet": (parent.content or "")[:40],
            "trust": round(trust, 2), "intimacy": round(intimacy, 2),
            "dominance": round(dominance, 2), "tension": round(tension, 2),
        }
        # 转折点：任一维度相邻变化 > 0.18
        if prev:
            for dim, cn in (("trust", "信任"), ("intimacy", "亲密"), ("dominance", "主动权"), ("tension", "张力")):
                delta = point[dim] - prev[dim]
                if abs(delta) >= 0.18:
                    turning.append({
                        "message_id": parent.id, "dim": cn,
                        "direction": "上升" if delta > 0 else "下降",
                        "snippet": point["snippet"],
                    })
        points.append(point)
        prev = point

    current = points[-1] if points else {"trust": 0.5, "intimacy": 0.45, "dominance": 0.5, "tension": 0.3}
    return {
        "source": source, "target": target,
        "points": points,
        "turning_points": turning[-8:],
        "current": {k: current[k] for k in ("trust", "intimacy", "dominance", "tension")},
        "dims": [
            {"key": "trust", "label": "信任"},
            {"key": "intimacy", "label": "亲密"},
            {"key": "dominance", "label": f"主动权·{source}"},
            {"key": "tension", "label": "张力"},
        ],
    }


def _resolve_pair_for_advice(conv: Conversation, db: Session, payload: dict) -> tuple[str, str]:
    """确定「我」与「对方」：me 优先取 payload，再取会话 self_name；对方优先 payload，否则取对话里非我的发言者。"""
    self_name = (payload.get("me") or getattr(conv, "self_name", "") or "").strip()
    counterpart = (payload.get("counterpart") or "").strip()
    if not counterpart:
        names = [r[0] for r in db.query(Message.character_name).filter(
            _visible_message_filter(conv), Message.role == "user", Message.character_name.isnot(None),
        ).distinct().all()]
        others = [n for n in names if n and n != self_name]
        counterpart = others[0] if others else ""
    return self_name, counterpart


def _recent_dialogue_text(db: Session, conv: Conversation, limit: int = 14) -> str:
    rows = _visible_messages_query(db, conv).filter(Message.role == "user").order_by(
        Message.message_index.desc(), Message.created_at.desc(), Message.id.desc()).limit(limit).all()
    rows = list(reversed(rows))
    return "\n".join(f"{(r.character_name or '?')}：{(r.content or '')[:120]}" for r in rows)


@router.post("/conversations/{conv_id}/theory-of-mind")
async def conversation_theory_of_mind(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    """信息差/心智模型：对方知道什么、不知道什么、在隐瞒什么、对我抱有哪些假设。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    me, counterpart = _resolve_pair_for_advice(conv, db, payload)
    if not counterpart:
        raise HTTPException(400, "无法确定「对方」是谁，请先指定「我」并确保对话里有对方发言")
    cp_char = db.query(Character).filter(Character.name == counterpart).first()
    me_char = db.query(Character).filter(Character.name == me).first() if me else None
    block = _render_character_block(cp_char, counterpart, "", me_char, me, db)
    dialogue = _recent_dialogue_text(db, conv)
    result = await orchestrator.analyze_theory_of_mind(me, counterpart, block, dialogue)
    return {"me": me, "counterpart": counterpart, **(result or {})}


@router.post("/conversations/{conv_id}/predict")
async def conversation_predict(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    """反事实预演：如果「我」对「对方」说出 candidate，预测他的反应/情绪/达成意图的可能性。"""
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    candidate = (payload.get("candidate") or "").strip()
    if not candidate:
        raise HTTPException(400, "请先填写你想说的话")
    me, counterpart = _resolve_pair_for_advice(conv, db, payload)
    if not counterpart:
        raise HTTPException(400, "无法确定「对方」是谁，请先指定「我」并确保对话里有对方发言")
    cp_char = db.query(Character).filter(Character.name == counterpart).first()
    me_char = db.query(Character).filter(Character.name == me).first() if me else None
    block = _render_character_block(cp_char, counterpart, "", me_char, me, db)
    try:
        pack = build_evidence_pack(db, query_text=candidate, speaker=me_char, listener=cp_char, conversation=conv)
        memory_block = render_evidence_pack(pack)
    except Exception:
        memory_block = ""
    context = _recent_dialogue_text(db, conv)
    goal = (payload.get("goal") or getattr(conv, "goal", "") or "").strip()
    result = await orchestrator.predict_counterfactual(me, counterpart, candidate, block, memory_block, context, goal)
    return {"me": me, "counterpart": counterpart, "candidate": candidate, **(result or {})}


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
        parsed = _emotion_struct_for(analysis)
        intended = parsed.get("intended") or {}
        deep = parsed.get("deep") or {}
        if not intended.get("label") and not deep.get("label"):
            continue
        emotions.append(
            {
                "message_id": parent.id,
                "label": intended.get("label", ""),
                "score": round(intended.get("score", 0) / 10, 2),
                "target": target,
            }
        )
        if deep.get("label"):
            deep_emotions.append(
                {
                    "message_id": parent.id,
                    "label": deep.get("label", ""),
                    "score": round(deep.get("score", 0) / 10, 2),
                    "target": target,
                }
            )
            dominant.append(deep["label"])
            emotion_keywords[deep["label"]] = emotion_keywords.get(deep["label"], 0) + deep.get("score", 0)
        if intended.get("label"):
            emotion_keywords[intended["label"]] = emotion_keywords.get(intended["label"], 0) + intended.get("score", 0)
        strategy = _strategy_struct_for(analysis)
        if strategy.get("short_term") or strategy.get("long_term"):
            strategy_trajectory.append(
                {
                    "message_id": parent.id,
                    "short_term": strategy.get("short_term", ""),
                    "long_term": strategy.get("long_term", ""),
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
async def archive_conversation(conv_id: int, payload: dict, db: Session = Depends(get_db)):
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
        parsed = _emotion_struct_for(analysis)
        deep_item = parsed.get("deep") or {}
        intended_item = parsed.get("intended") or {}
        actual_polarity = _emotion_polarity(deep_item.get("label", ""))
        intended_polarity = _emotion_polarity(intended_item.get("label", ""))
        delta = 0.06 if actual_polarity == intended_polarity and actual_polarity != 0 else -0.04
        sentiment_target = max(-1.0, min(1.0, deep_item.get("score", 0) / 10 * actual_polarity))
        relationship = find_pair_relationship(db, source_char.id, target_char.id)
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
        # delta 直接作用于强度（旧公式 0.2*delta 衰减过强，强度几乎不动）
        relationship.strength = max(0.0, min(1.0, relationship.strength + delta))
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

        long_term = _strategy_struct_for(analysis).get("long_term", "")
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
                    metadata_json={
                        "source": "会话归档",
                        "evidence": f"归档提取到稳定行为模式：{long_term}",
                        "confidence": 0.74,
                        "change_type": "新增",
                        "module": "行为模式",
                        "category": "互动策略",
                        "trigger": "",
                        "example": user_message.content[:120],
                    },
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
                metadata_json={
                    "source": "会话归档",
                    "evidence": f"归档时检测到潜在角色冲突：{(analysis.subtext or '')[:200]}",
                    "confidence": 0.68,
                    "change_type": "新增",
                    "module": "人格模型",
                    "category": "",
                    "trigger": "",
                    "example": user_message.content[:120],
                },
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

    # 多视角归档：每条发言的每个旁观视角 → 回流到旁观者对发言者的认知（记忆 + 关系微调）
    perspectives_archived = _archive_perspectives(db, messages, role_map)

    db.commit()
    # 归档后异步演化特质假设：会话证据流入人物模型，闭环不再依赖手动操作
    asyncio.create_task(_run_session_hypothesis_rounds(conv_id))
    return {
        "ok": True,
        "archived_roles": archived_roles,
        "observations_created": observations_created,
        "perspectives_archived": perspectives_archived,
    }


def _archive_perspectives(db: Session, messages: list, role_map: dict) -> int:
    """
    多视角归档回流：每个旁观者对发言者这句话的理解，沉淀为旁观者的认知。
    - 记忆：viewer 记下"我对 speaker 的判断"（关系标签 + 深层情绪）
    - 关系：按 viewer 对 speaker 的深层情绪极性，微调 viewer→speaker 关系的情感
    多人对话中每个角色都从旁观中"学到"对他人的理解。
    """
    archived = 0
    for message in messages:
        if message.role != "user":
            continue
        perspectives = db.query(MessagePerspective).filter(
            MessagePerspective.message_id == message.id,
        ).all()
        for persp in perspectives:
            viewer_char = role_map.get(persp.viewer_name) or (
                db.get(Character, persp.viewer_character_id) if persp.viewer_character_id else None
            )
            speaker_char = role_map.get(persp.speaker_name) or (
                db.query(Character).filter(Character.name == persp.speaker_name).first()
            )
            if not viewer_char or not speaker_char or viewer_char.id == speaker_char.id:
                continue
            emotions = (persp.analysis_json or {}).get("emotions") or {}
            tags = (persp.analysis_json or {}).get("tags") or {}
            deep = emotions.get("deep") or {}
            deep_label = (deep.get("label") or "").strip()
            relation_tag = (tags.get("relation") or "").strip()
            # 记忆：viewer 对 speaker 的认知
            content = f"对{speaker_char.name}的判断：{relation_tag or deep_label or persp.subtext or ''}".strip("：")
            if relation_tag or deep_label:
                evidence = _create_evidence_span(
                    db, character_id=viewer_char.id, source_type="chat_archive",
                    conversation_id=message.conversation_id, message_id=message.id,
                    supports_type="perspective", quote=message.content,
                    interpretation=persp.inner_monologue or content, confidence=0.7,
                    metadata={"speaker": speaker_char.name, "viewer": viewer_char.name},
                )
                _create_memory_item(
                    db, character_id=viewer_char.id, memory_type="relationship",
                    content=content, confidence=0.7, source="多视角归档",
                    evidence_ids=[evidence.id],
                )
            # 关系微调：viewer→speaker，按深层情绪极性
            polarity = _emotion_polarity(deep_label)
            if polarity != 0:
                rel = find_pair_relationship(db, viewer_char.id, speaker_char.id)
                if not rel:
                    rel = Relationship(
                        source_id=viewer_char.id, target_id=speaker_char.id,
                        rel_type="dynamic", strength=0.5, sentiment=0.0,
                        description="由多视角对话归档生成", history=[],
                    )
                    db.add(rel)
                    db.flush()
                score = (deep.get("score") or 0) / 10
                rel.sentiment = max(-1.0, min(1.0, (rel.sentiment or 0.0) * 0.8 + polarity * score * 0.2))
                rel.updated_at = datetime.utcnow()
            archived += 1
    return archived
