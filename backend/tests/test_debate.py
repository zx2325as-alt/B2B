"""Q1 多轮对抗分析：_auto_debate_message 对「发言者自述视角」跑对抗，把 debate 并入 analysis_json；
主流解读被推翻(stronger=alternative)时置信只降不升。打桩 debate_perspective，避免真实 LLM。"""
import asyncio

import app.api.chat as chat
from app.api.chat import _auto_debate_message
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Message, MessagePerspective


def test_debate_merges_and_downgrades_on_alternative(monkeypatch):
    async def fake_debate(speaker, utterance, current_read, evidence_block=""):
        return {
            "alternative_read": {"intent": "真的累了", "subtext": "让我省心", "deep_emotion": {"label": "疲惫", "score": 5}},
            "stronger": "alternative",
            "reconciled": {"subtext": "更可能是真放手", "deep_emotion": {"label": "疲惫", "score": 5},
                           "confidence": 0.4, "why": "原话无情绪词"},
        }
    monkeypatch.setattr(chat.orchestrator, "debate_perspective", fake_debate)
    monkeypatch.setattr(chat, "build_evidence_pack", lambda *a, **k: {})
    monkeypatch.setattr(chat, "render_evidence_pack", lambda *a, **k: "")

    db = SessionLocal()
    conv = Conversation(title="对抗", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="小敏", content="随便吧")
    db.add(m); db.commit(); db.refresh(m)
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, speaker_name="小敏", viewer_name="小敏",
        stance="speaker", subtext="赌气想被哄",
        analysis_json={"confidence": 0.8, "subtext": "赌气想被哄",
                       "emotions": {"deep": {"label": "委屈", "score": 7}},
                       "inner_monologue": {"first_reaction": "哼"}}))
    db.commit()
    cid, mid = conv.id, m.id
    try:
        res = asyncio.run(_auto_debate_message(db, m))
        assert res["stronger"] == "alternative"
        aj = db.query(MessagePerspective).filter(MessagePerspective.message_id == mid).first().analysis_json
        assert aj["debate"]["alternative"]["intent"] == "真的累了"
        assert aj["debate"]["reconciled"]["subtext"] == "更可能是真放手"
        assert aj["confidence"] <= 0.4   # 主流解读被推翻 → 置信降到 reconciled
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_debate_no_speaker_perspective_safe():
    db = SessionLocal()
    conv = Conversation(title="空对抗", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="小敏", content="随便吧")
    db.add(m); db.commit(); db.refresh(m)
    cid = conv.id
    try:
        assert asyncio.run(_auto_debate_message(db, m)) == {}   # 没有自述视角安全返回
    finally:
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
