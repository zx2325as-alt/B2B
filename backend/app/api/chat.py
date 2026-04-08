import json
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..models.sql_models import Conversation, Message, Character, Relationship, CharacterEvent, CharacterObservation
from ..schemas import ChatMessage, ConversationCreate, MessageOut
from ..harness.orchestrator import orchestrator
from ..harness.context_manager import get_context
from ..harness.state_engine import state_engine
from ..harness.consistency_engine import build_consistency_constraints
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


def _emotion_polarity(label: str) -> int:
    positive = {"喜悦", "依恋", "信任", "安心", "感动", "期待", "亲近"}
    negative = {"愧疚", "恐惧", "愤怒", "厌烦", "警惕", "防御", "回避", "羞耻", "怀疑"}
    if label in positive:
        return 1
    if label in negative:
        return -1
    return 0


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
    return char


def _get_recent_dialogue(db: Session, conv_id: int, limit: int = 10) -> str:
    messages = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.role == "user",
    ).order_by(Message.created_at.desc()).limit(limit).all()
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

    recent_messages = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.role == "user",
    ).order_by(Message.created_at.desc()).limit(5).all()
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


# ─── Conversations ────────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    convs = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(20).all()
    return [{"id": c.id, "title": c.title, "scenario": c.scenario, "updated_at": c.updated_at} for c in convs]


@router.post("/conversations")
def create_conversation(body: ConversationCreate, db: Session = Depends(get_db)):
    conv = Conversation(title=body.title, scenario=body.scenario)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"id": conv.id, "title": conv.title, "scenario": conv.scenario}


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
    return db.query(Message).filter_by(conversation_id=conv_id).order_by(Message.created_at).all()


# ─── Stream Chat ──────────────────────────────────────────────────────────────

@router.post("/send")
async def send_message(body: ChatMessage, db: Session = Depends(get_db)):
    conv = db.get(Conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    if not body.speaker:
        raise HTTPException(400, "请先选择发言角色")

    user_msg = Message(
        conversation_id=body.conversation_id,
        role="user",
        character_name=body.speaker,
        character_id=body.character_id,
        content=body.content,
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

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
            ai_msg = Message(
                conversation_id=body.conversation_id,
                role="assistant",
                character_name="AI分析",
                content=full_result.get("reply", ""),
                inner_monologue=full_result.get("inner_monologue"),
                emotion_label=full_result.get("emotion_label"),
                emotion_score=full_result.get("emotion_score"),
                subtext=full_result.get("subtext"),
                psychological_tag=full_result.get("psychological_tag"),
                parent_id=user_msg.id,
            )
            db.add(ai_msg)
            db.commit()

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
        Message.conversation_id == conv.id,
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

    result = None
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
        ai_msg.content = result.get("reply", "")
        ai_msg.inner_monologue = result.get("inner_monologue")
        ai_msg.emotion_label = result.get("emotion_label")
        ai_msg.emotion_score = result.get("emotion_score")
        ai_msg.subtext = result.get("subtext")
        ai_msg.psychological_tag = result.get("psychological_tag")
    else:
        ai_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            character_name="AI分析",
            content=result.get("reply", ""),
            inner_monologue=result.get("inner_monologue"),
            emotion_label=result.get("emotion_label"),
            emotion_score=result.get("emotion_score"),
            subtext=result.get("subtext"),
            psychological_tag=result.get("psychological_tag"),
            parent_id=message.id,
        )
        db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)
    return ai_msg


# ─── Branch ──────────────────────────────────────────────────────────────────

@router.post("/conversations/{conv_id}/branch/{message_id}")
def create_branch(conv_id: int, message_id: int, db: Session = Depends(get_db)):
    """从指定消息创建分支"""
    msg = db.get(Message, message_id)
    if not msg or msg.conversation_id != conv_id:
        raise HTTPException(404)
    # 清除该消息之后的上下文
    ctx = get_context(conv_id)
    # 获取到该消息为止的历史
    messages = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.id <= message_id,
    ).order_by(Message.created_at).all()
    ctx.clear()
    for m in messages:
        ctx.add(m.role, m.content, {"character_name": m.character_name})
    return {"ok": True, "branch_point": message_id, "context_reset": True}


# ─── Emotion Curve ───────────────────────────────────────────────────────────

@router.get("/conversations/{conv_id}/emotion-curve/{character_name}")
async def get_emotion_curve(conv_id: int, character_name: str, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.character_name == character_name,
    ).order_by(Message.created_at).limit(10).all()

    if not messages:
        return {"emotions": [], "trend": "stable", "turning_point": None}

    msg_texts = [m.content for m in messages]
    result = await orchestrator.analyze_emotion_curve(character_name, msg_texts)
    return result


@router.get("/conversations/{conv_id}/emotion-tension")
def get_emotion_tension(conv_id: int, source: str, target: str, db: Session = Depends(get_db)):
    analysis_messages = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.role == "assistant",
        Message.parent_id.isnot(None),
    ).order_by(Message.created_at).all()

    emotions = []
    deep_emotions = []
    strategy_trajectory = []
    dominant = []
    for analysis in analysis_messages:
        parent = db.get(Message, analysis.parent_id)
        if not parent or parent.character_name != source:
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

    return {
        "emotions": emotions,
        "deep_emotions": deep_emotions,
        "strategy_trajectory": strategy_trajectory,
        "trend": trend,
        "turning_point": dominant[-1] if dominant else None,
    }


@router.post("/conversations/{conv_id}/archive")
def archive_conversation(conv_id: int, payload: dict, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    role_names = payload.get("role_names") or []
    messages = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at).all()
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

    user_messages = [m for m in messages if m.role == "user" and m.parent_id is None]
    for user_message in user_messages:
        source_char = role_map.get(user_message.character_name or "")
        if not source_char:
            continue
        analysis = db.query(Message).filter(Message.parent_id == user_message.id).first()
        if not analysis:
            continue
        listeners = [name for name in role_names if name != user_message.character_name]
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

        strategy_lines = [line.strip() for line in (analysis.subtext or "").splitlines() if line.strip()]
        long_term = next((line.replace("长期策略：", "").strip() for line in strategy_lines if line.startswith("长期策略：")), "")
        if long_term:
            existing_pattern = db.query(CharacterObservation).filter(
                CharacterObservation.character_id == source_char.id,
                CharacterObservation.field == "behavior_pattern",
                CharacterObservation.reason.contains(long_term),
            ).first()
            if not existing_pattern:
                db.add(
                    CharacterObservation(
                        character_id=source_char.id,
                        field="behavior_pattern",
                        old_value="",
                        new_value=long_term,
                        reason=f"归档提取到稳定行为模式：{long_term}",
                    )
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
            observations_created += 1

    db.commit()
    return {
        "ok": True,
        "archived_roles": archived_roles,
        "observations_created": observations_created,
    }
