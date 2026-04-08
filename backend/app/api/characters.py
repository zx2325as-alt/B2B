import json
from pathlib import Path

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character, CharacterEvent, Relationship, CharacterObservation,
    Conversation, Message, ImportFile, InteractionUnit
)
from ..schemas import (
    CharacterCreate, CharacterUpdate, CharacterOut,
    EventCreate, EventOut,
    RelationshipCreate, RelationshipUpdate, RelationshipOut,
    ObservationReview, ObservationOut, ImportCommitRequest,
)
from ..harness.orchestrator import orchestrator
from ..harness.import_engine import extract_text_from_file, build_import_preview
from .deps import get_db

router = APIRouter(prefix="/characters", tags=["characters"])


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _resolve_mapping(role_mappings: list, original_name: str) -> dict:
    for mapping in role_mappings:
        if mapping.original_name == original_name:
            return {
                "name": mapping.resolved_name.strip() or original_name,
                "action": mapping.action,
            }
    return {"name": original_name, "action": "create"}


async def _ensure_character_from_mapping(db: Session, mapping: dict, parsed_character: dict) -> Character:
    resolved_name = mapping["name"]
    existing = db.query(Character).filter(Character.name == resolved_name).first()
    if existing:
        return existing

    char = Character(
        name=resolved_name,
        role=parsed_character.get("role", "") or "",
        background=parsed_character.get("background", "") or "",
        avatar_color="#00d4ff",
        personality_tags=parsed_character.get("personality_tags", []) or [],
        core_traits={},
        weakness="",
        motivation="",
        speaking_style="",
    )
    db.add(char)
    db.commit()
    db.refresh(char)
    try:
        profile = await orchestrator.generate_character_profile(
            char.name,
            char.role or "",
            char.background or "",
        )
        char.personality_tags = profile.get("personality_tags", []) or char.personality_tags
        char.core_traits = profile.get("core_traits", {}) or {}
        char.weakness = profile.get("weakness", "") or char.weakness
        char.motivation = profile.get("motivation", "") or char.motivation
        char.speaking_style = profile.get("speaking_style", "") or char.speaking_style
        db.commit()
        db.refresh(char)
    except Exception:
        pass
    return char


def _infer_rel_type(sentiment: float, interaction_type: str) -> str:
    if interaction_type in {"conflict", "对抗"}:
        return "rival"
    if interaction_type in {"support", "信任", "合作"}:
        return "ally"
    if sentiment >= 0.35:
        return "friend"
    if sentiment <= -0.35:
        return "rival"
    return "neutral"


# ─── Characters CRUD ──────────────────────────────────────────────────────────

@router.get("/", response_model=list[CharacterOut])
def list_characters(db: Session = Depends(get_db)):
    return db.query(Character).order_by(Character.name).all()


@router.post("/", response_model=CharacterOut)
async def create_character(body: CharacterCreate, db: Session = Depends(get_db)):
    char = Character(**body.model_dump())
    char.core_traits = {}
    db.add(char)
    db.commit()
    db.refresh(char)
    # 自动生成 AI 心理档案
    try:
        profile = await orchestrator.generate_character_profile(
            char.name, char.role, char.background
        )
        char.personality_tags = profile.get("personality_tags", [])
        char.core_traits = profile.get("core_traits", {})
        char.weakness = profile.get("weakness", "")
        char.motivation = profile.get("motivation", "")
        char.speaking_style = profile.get("speaking_style", "")
        db.commit()
        db.refresh(char)
    except Exception:
        pass  # AI 分析失败不影响创建
    return char


@router.get("/{char_id}", response_model=CharacterOut)
def get_character(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    return char


@router.put("/{char_id}", response_model=CharacterOut)
def update_character(char_id: int, body: CharacterUpdate, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(char, k, v)
    char.version += 1
    char.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(char)
    return char


@router.delete("/{char_id}")
def delete_character(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    db.delete(char)
    db.commit()
    return {"ok": True}


@router.post("/imports/preview")
async def preview_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    content_text = await extract_text_from_file(file.filename or "unknown.txt", content)
    existing_characters = [
        {"id": char.id, "name": char.name, "role": char.role or ""}
        for char in db.query(Character).all()
    ]
    preview = await build_import_preview(file.filename or "unknown.txt", content_text, existing_characters)
    import_file = ImportFile(
        filename=file.filename or "unknown.txt",
        file_type=preview.get("detected_type", Path(file.filename or "").suffix.lower().lstrip(".")),
        content_type=file.content_type or "",
        status="previewed",
        summary=(preview.get("plot_summary", {}) or {}).get("main_conflict", ""),
        metadata_json={
            "role_count": len(preview.get("characters", [])),
            "interaction_count": len(preview.get("interaction_units", [])),
            "event_count": len(preview.get("events", [])),
            "relationship_count": len(preview.get("relationships", [])),
        },
    )
    db.add(import_file)
    db.commit()
    db.refresh(import_file)
    preview["import_file_id"] = import_file.id
    return preview


@router.post("/imports/commit")
async def commit_import(body: ImportCommitRequest, db: Session = Depends(get_db)):
    preview = body.preview_payload or {}
    import_file = db.get(ImportFile, body.import_file_id) if body.import_file_id else None
    if not import_file:
        import_file = ImportFile(
            filename=body.filename,
            file_type=body.file_type,
            content_type="",
            status="committed",
            summary=(preview.get("plot_summary", {}) or {}).get("main_conflict", ""),
            metadata_json={},
        )
        db.add(import_file)
        db.commit()
        db.refresh(import_file)

    resolved_chars = {}
    role_mappings = body.role_mappings or []
    parsed_characters = {item.get("name"): item for item in preview.get("characters", [])}
    for original_name, parsed_char in parsed_characters.items():
        mapping = _resolve_mapping(role_mappings, original_name)
        if mapping["action"] == "skip":
            continue
        resolved_chars[original_name] = await _ensure_character_from_mapping(db, mapping, parsed_char)

    conversation = None
    if body.create_readonly_conversation:
        conversation = Conversation(
            title=f"只读导入 · {body.filename}",
            scenario=body.scenario,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    committed_units = 0
    created_events = 0
    created_relationships = 0
    failures = {"characters": [], "events": [], "relationships": [], "analysis": []}

    for index, unit in enumerate(preview.get("interaction_units", []), start=1):
        try:
            speaker_name = unit.get("speaker", "").strip()
            if not speaker_name or speaker_name not in resolved_chars:
                continue
            speaker_char = resolved_chars[speaker_name]
            receiver_name = unit.get("receiver", "").strip()
            resolved_receiver = resolved_chars.get(receiver_name) if receiver_name in resolved_chars else None
            context_payload = {
                "speaker_profile": {
                    "name": speaker_char.name,
                    "role": speaker_char.role or "",
                    "personality_tags": speaker_char.personality_tags or [],
                    "motivation": speaker_char.motivation or "",
                    "weakness": speaker_char.weakness or "",
                    "speaking_style": speaker_char.speaking_style or "",
                },
                "receiver_profile": {
                    "name": resolved_receiver.name if resolved_receiver else receiver_name,
                    "role": resolved_receiver.role if resolved_receiver else "",
                    "personality_tags": resolved_receiver.personality_tags if resolved_receiver else [],
                    "motivation": resolved_receiver.motivation if resolved_receiver else "",
                    "weakness": resolved_receiver.weakness if resolved_receiver else "",
                    "speaking_style": resolved_receiver.speaking_style if resolved_receiver else "",
                },
                "relationship": {
                    "description": "",
                    "strength": 0.2,
                    "sentiment": 0.0,
                },
            }
            analysis = await orchestrator.rebuild_import_analysis(unit, context_payload)
            message_id = None
            analysis_message_id = None
            if conversation:
                msg = Message(
                    conversation_id=conversation.id,
                    role="user",
                    character_id=speaker_char.id,
                    character_name=speaker_char.name,
                    content=unit.get("content", ""),
                )
                db.add(msg)
                db.commit()
                db.refresh(msg)
                message_id = msg.id

                analysis_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    character_name="AI分析",
                    content=analysis.get("behavior_tendency", "") or analysis.get("inner_monologue", ""),
                    inner_monologue=analysis.get("inner_monologue"),
                    emotion_label=analysis.get("emotion_attribution"),
                    emotion_score=0.6,
                    subtext=analysis.get("strategy_explanation"),
                    psychological_tag=analysis.get("analysis_tags"),
                    parent_id=msg.id,
                )
                db.add(analysis_msg)
                db.commit()
                db.refresh(analysis_msg)
                analysis_message_id = analysis_msg.id

            event_id = None
            event = CharacterEvent(
                character_id=speaker_char.id,
                title=f"导入事件 #{index}",
                description=unit.get("content", ""),
                event_date="",
                emotion_label=(unit.get("emotion") or {}).get("value", ""),
                importance=3,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            event_id = event.id
            created_events += 1

            relationship_id = None
            if resolved_receiver:
                intent_conf = _safe_float((unit.get("intent") or {}).get("confidence"), 0.5)
                sentiment = _safe_float((unit.get("emotion") or {}).get("confidence"), 0.5) * 2 - 1
                interaction_type = (unit.get("interaction_type") or {}).get("value", "")
                rel = db.query(Relationship).filter(
                    Relationship.source_id == speaker_char.id,
                    Relationship.target_id == resolved_receiver.id,
                ).first()
                if not rel:
                    rel = Relationship(
                        source_id=speaker_char.id,
                        target_id=resolved_receiver.id,
                        rel_type=_infer_rel_type(sentiment, interaction_type),
                        strength=max(0.2, min(1.0, intent_conf)),
                        sentiment=max(-1.0, min(1.0, sentiment)),
                        description=analysis.get("strategy_explanation", "")[:500],
                        history=[],
                    )
                    db.add(rel)
                    db.commit()
                    db.refresh(rel)
                    created_relationships += 1
                relationship_id = rel.id

            iu = InteractionUnit(
                import_file_id=import_file.id,
                source_line_index=unit.get("source_line_index", index),
                source_text_snippet=unit.get("content", "")[:500],
                speaker=speaker_char.name,
                receiver=resolved_receiver.name if resolved_receiver else receiver_name,
                receiver_confidence=_safe_float(unit.get("receiver_confidence"), 0.0),
                receiver_state=unit.get("receiver_state", "inferred"),
                content=unit.get("content", ""),
                intent=(unit.get("intent") or {}).get("value", ""),
                intent_confidence=_safe_float((unit.get("intent") or {}).get("confidence"), 0.0),
                intent_state=(unit.get("intent") or {}).get("state", "inferred"),
                strategy=(unit.get("strategy") or {}).get("value", ""),
                strategy_confidence=_safe_float((unit.get("strategy") or {}).get("confidence"), 0.0),
                strategy_state=(unit.get("strategy") or {}).get("state", "inferred"),
                emotion=(unit.get("emotion") or {}).get("value", ""),
                emotion_confidence=_safe_float((unit.get("emotion") or {}).get("confidence"), 0.0),
                emotion_state=(unit.get("emotion") or {}).get("state", "inferred"),
                interaction_type=(unit.get("interaction_type") or {}).get("value", ""),
                interaction_confidence=_safe_float((unit.get("interaction_type") or {}).get("confidence"), 0.0),
                interaction_state=(unit.get("interaction_type") or {}).get("state", "inferred"),
                analysis=analysis,
                event_payload=preview.get("events", []),
                relationship_payload=preview.get("relationships", []),
                conversation_message_id=message_id or analysis_message_id,
                character_event_id=event_id,
                relationship_id=relationship_id,
            )
            db.add(iu)
            db.commit()
            committed_units += 1
        except Exception as exc:
            failures["analysis"].append({"index": index, "error": str(exc)})
            db.rollback()

    import_file.status = "committed"
    import_file.summary = (preview.get("plot_summary", {}) or {}).get("main_conflict", import_file.summary)
    import_file.metadata_json = {
        "role_count": len(resolved_chars),
        "interaction_count": committed_units,
        "event_count": created_events,
        "relationship_count": created_relationships,
        "failures": failures,
        "plot_summary": preview.get("plot_summary", {}),
    }
    db.commit()

    return {
        "ok": True,
        "import_file_id": import_file.id,
        "conversation_id": conversation.id if conversation else None,
        "created_characters": [char.name for char in resolved_chars.values()],
        "interaction_units": committed_units,
        "events": created_events,
        "relationships": created_relationships,
        "failures": failures,
        "plot_summary": preview.get("plot_summary", {}),
    }


@router.get("/exports/full")
def export_all_data(db: Session = Depends(get_db)):
    payload = {
        "characters": [CharacterOut.model_validate(char).model_dump(mode="json") for char in db.query(Character).all()],
        "events": [EventOut.model_validate(event).model_dump(mode="json") for event in db.query(CharacterEvent).all()],
        "relationships": [RelationshipOut.model_validate(rel).model_dump(mode="json") for rel in db.query(Relationship).all()],
        "observations": [ObservationOut.model_validate(obs).model_dump(mode="json") for obs in db.query(CharacterObservation).all()],
        "imports": [
            {
                "file": {
                    "id": item.id,
                    "filename": item.filename,
                    "file_type": item.file_type,
                    "status": item.status,
                    "summary": item.summary,
                    "metadata_json": item.metadata_json or {},
                },
                "interaction_units": [
                    {
                        "id": unit.id,
                        "source_line_index": unit.source_line_index,
                        "source_text_snippet": unit.source_text_snippet,
                        "speaker": unit.speaker,
                        "receiver": unit.receiver,
                        "receiver_confidence": unit.receiver_confidence,
                        "receiver_state": unit.receiver_state,
                        "content": unit.content,
                        "intent": {"value": unit.intent, "confidence": unit.intent_confidence, "state": unit.intent_state},
                        "strategy": {"value": unit.strategy, "confidence": unit.strategy_confidence, "state": unit.strategy_state},
                        "emotion": {"value": unit.emotion, "confidence": unit.emotion_confidence, "state": unit.emotion_state},
                        "interaction_type": {"value": unit.interaction_type, "confidence": unit.interaction_confidence, "state": unit.interaction_state},
                        "analysis": unit.analysis or {},
                        "character_event_id": unit.character_event_id,
                        "relationship_id": unit.relationship_id,
                    }
                    for unit in item.interaction_units
                ],
            }
            for item in db.query(ImportFile).order_by(ImportFile.created_at.desc()).all()
        ],
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename=btb-export-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"},
    )


# ─── AI Suggestions ──────────────────────────────────────────────────────────

@router.post("/{char_id}/suggest-update")
async def suggest_update(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404)
    profile = {
        "name": char.name, "role": char.role,
        "personality_tags": char.personality_tags,
        "weakness": char.weakness, "motivation": char.motivation,
    }
    # 取最近对话文本（简化：用 events 代替）
    events = db.query(CharacterEvent).filter_by(character_id=char_id).order_by(CharacterEvent.created_at.desc()).limit(5).all()
    dialogue = "\n".join(e.description for e in events if e.description) or "暂无对话记录"
    suggestions = await orchestrator.suggest_character_update(profile, dialogue)
    obs_list = []
    for s in suggestions:
        obs = CharacterObservation(
            character_id=char_id,
            field=s.get("field", ""),
            old_value=str(s.get("old_value", "")),
            new_value=str(s.get("new_value", "")),
            reason=s.get("reason", ""),
        )
        db.add(obs)
        obs_list.append(obs)
    db.commit()
    for o in obs_list:
        db.refresh(o)
    return obs_list


@router.get("/{char_id}/observations", response_model=list[ObservationOut])
def list_observations(char_id: int, db: Session = Depends(get_db)):
    return db.query(CharacterObservation).filter_by(character_id=char_id).order_by(CharacterObservation.created_at.desc()).all()


@router.post("/{char_id}/observations/{obs_id}/review")
def review_observation(char_id: int, obs_id: int, body: ObservationReview, db: Session = Depends(get_db)):
    obs = db.get(CharacterObservation, obs_id)
    if not obs or obs.character_id != char_id:
        raise HTTPException(404)
    obs.status = body.status
    obs.reviewed_at = datetime.utcnow()
    if body.status == "approved":
        char = db.get(Character, char_id)
        if char and hasattr(char, obs.field):
            setattr(char, obs.field, obs.new_value)
            char.version += 1
    db.commit()
    return {"ok": True, "status": body.status}


# ─── Events ───────────────────────────────────────────────────────────────────

@router.get("/{char_id}/events", response_model=list[EventOut])
def list_events(char_id: int, db: Session = Depends(get_db)):
    return db.query(CharacterEvent).filter_by(character_id=char_id).order_by(CharacterEvent.event_date).all()


@router.post("/{char_id}/events", response_model=EventOut)
def create_event(char_id: int, body: EventCreate, db: Session = Depends(get_db)):
    event = CharacterEvent(**body.model_dump())
    event.character_id = char_id
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{char_id}/events/{event_id}")
def delete_event(char_id: int, event_id: int, db: Session = Depends(get_db)):
    ev = db.get(CharacterEvent, event_id)
    if not ev:
        raise HTTPException(404)
    db.delete(ev)
    db.commit()
    return {"ok": True}


# ─── Relationships ────────────────────────────────────────────────────────────

@router.get("/relationships/all", response_model=list[RelationshipOut])
def list_all_relationships(db: Session = Depends(get_db)):
    return db.query(Relationship).all()


@router.post("/relationships/", response_model=RelationshipOut)
def create_relationship(body: RelationshipCreate, db: Session = Depends(get_db)):
    # 检查是否已存在
    existing = db.query(Relationship).filter_by(
        source_id=body.source_id, target_id=body.target_id
    ).first()
    if existing:
        raise HTTPException(400, "关系已存在")
    rel = Relationship(**body.model_dump(), history=[])
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


@router.put("/relationships/{rel_id}", response_model=RelationshipOut)
def update_relationship(rel_id: int, body: RelationshipUpdate, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    # 保存历史快照
    snapshot = {
        "date": datetime.utcnow().isoformat(),
        "strength": rel.strength,
        "sentiment": rel.sentiment,
    }
    history = rel.history or []
    history.append(snapshot)
    rel.history = history
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(rel, k, v)
    rel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rel)
    return rel


@router.delete("/relationships/{rel_id}")
def delete_relationship(rel_id: int, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    db.delete(rel)
    db.commit()
    return {"ok": True}


@router.get("/relationships/{rel_id}/analyze")
async def analyze_relationship(rel_id: int, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    char_a = f"{rel.source.name}（{rel.source.role}）"
    char_b = f"{rel.target.name}（{rel.target.role}）"
    result = await orchestrator.analyze_relationship(char_a, char_b, rel.history or [])
    return result
