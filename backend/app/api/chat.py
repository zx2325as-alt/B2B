import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..models.sql_models import Conversation, Message, Character
from ..schemas import ChatMessage, ConversationCreate, MessageOut
from ..harness.orchestrator import orchestrator
from ..harness.context_manager import get_context
from .deps import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


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


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def get_messages(conv_id: int, db: Session = Depends(get_db)):
    return db.query(Message).filter_by(conversation_id=conv_id).order_by(Message.created_at).all()


# ─── Stream Chat ──────────────────────────────────────────────────────────────

@router.post("/send")
async def send_message(body: ChatMessage, db: Session = Depends(get_db)):
    """
    SSE 流式聊天
    先保存用户消息，再流式返回 AI 分析
    """
    conv = db.get(Conversation, body.conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    # 保存用户消息
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

    # 获取角色记忆
    character_memory = ""
    if body.character_id:
        char = db.get(Character, body.character_id)
        if char:
            character_memory = (
                f"角色：{char.name}\n"
                f"角色定位：{char.role}\n"
                f"核心动机：{char.motivation}\n"
                f"弱点：{char.weakness}\n"
                f"说话风格：{char.speaking_style}"
            )

    # 获取场景中的所有角色描述
    characters_desc = "用户"

    async def event_generator():
        full_result = None
        async for chunk in orchestrator.stream_chat(
            conversation_id=body.conversation_id,
            speaker=body.speaker,
            content=body.content,
            scenario=conv.scenario,
            characters_desc=characters_desc,
            character_memory=character_memory,
        ):
            data = json.loads(chunk)
            if data["type"] == "done":
                full_result = data["result"]
            yield f"data: {chunk}\n\n"

        # 流结束后保存 AI 回复到数据库
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
