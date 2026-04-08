from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character, CharacterEvent, Relationship, CharacterObservation
)
from ..schemas import (
    CharacterCreate, CharacterUpdate, CharacterOut,
    EventCreate, EventOut,
    RelationshipCreate, RelationshipUpdate, RelationshipOut,
    ObservationReview, ObservationOut,
)
from ..harness.orchestrator import orchestrator
from .deps import get_db

router = APIRouter(prefix="/characters", tags=["characters"])


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
