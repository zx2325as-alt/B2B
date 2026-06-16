"""P5 每次分析后自动 LLM 复核：_auto_critic_message 把 critic 结论就地并入视角，
过度推断下调置信/标推测。打桩 critique_perspectives，避免真实 LLM。"""
import asyncio

import app.api.chat as chat
from app.api.chat import _auto_critic_message
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Message, MessagePerspective


def test_auto_critic_applies_review(monkeypatch):
    async def fake_critic(utterance, perspectives_payload, evidence_block=""):
        return {"overall": "整体偏脑补", "reviewed": [
            {"viewer": "阿杰", "verdict": "downgraded", "confidence": 0.3, "grounded": False,
             "issues": ["把短期情绪当长期人格"], "revised_subtext": "证据不足"}]}
    monkeypatch.setattr(chat.orchestrator, "critique_perspectives", fake_critic)

    db = SessionLocal()
    conv = Conversation(title="复核", self_name="小林"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="阿杰", content="在吗")
    db.add(m); db.commit(); db.refresh(m)
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, speaker_name="阿杰", viewer_name="阿杰",
        stance="speaker", subtext="他在试探",
        analysis_json={"confidence": 0.8, "grounded": True, "evidence": "在吗"}))
    db.commit()
    cid, mid = conv.id, m.id
    try:
        res = asyncio.run(_auto_critic_message(db, m))
        assert res["corrections"], "应有修订"
        aj = db.query(MessagePerspective).filter(MessagePerspective.message_id == mid).first().analysis_json
        assert aj["critic"]["verdict"] == "downgraded"
        assert aj["confidence"] <= 0.45   # grounded=False → 置信封顶
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_auto_critic_no_perspectives_safe():
    db = SessionLocal()
    conv = Conversation(title="空", self_name="小林"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="阿杰", content="在吗")
    db.add(m); db.commit(); db.refresh(m)
    cid = conv.id
    try:
        assert asyncio.run(_auto_critic_message(db, m)) == {"overall": "", "corrections": []}
    finally:
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
