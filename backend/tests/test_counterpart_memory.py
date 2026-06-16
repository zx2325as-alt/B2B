"""Q4 越用越准做实：counterpart-memory 聚合关于对方的（假设+已批准观察+预演教训）+ 预演命中率。"""
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import (
    Character, CharacterObservation, Conversation, MemoryItem, Message, Prediction, TraitHypothesis,
)
from fastapi.testclient import TestClient

client = TestClient(app)


def test_counterpart_memory_aggregates():
    db = SessionLocal()
    conv = Conversation(title="记忆", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    cp = Character(name="老王", motivation="想被认可", weakness="怕被否定", personality_tags=["要强"])
    db.add(cp); db.commit(); db.refresh(cp)
    db.add(Message(conversation_id=conv.id, role="user", message_index=0, character_name="老王", content="哦"))
    db.add(TraitHypothesis(character_id=cp.id, hypothesis="被质疑时会嘴硬", dimension="心理特征", confidence=0.7, status="confirmed"))
    db.add(CharacterObservation(character_id=cp.id, field="motivation", new_value="渴望主导权", status="approved"))
    db.add(MemoryItem(character_id=cp.id, memory_type="diagnosis", content="他被直接邀约反而先警惕", confidence=0.75, status="active"))
    db.add(Prediction(conversation_id=conv.id, counterpart_name="老王", counterpart_id=cp.id, status="resolved", verdict="hit"))
    db.add(Prediction(conversation_id=conv.id, counterpart_name="老王", counterpart_id=cp.id, status="resolved", verdict="miss"))
    db.commit()
    cid, cpid = conv.id, cp.id
    try:
        r = client.get(f"/api/v1/chat/conversations/{cid}/counterpart-memory")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "老王"
        assert d["count"] >= 3
        contents = " ".join(l["content"] for l in d["learnings"])
        assert "嘴硬" in contents and "警惕" in contents
        assert d["prediction"]["resolved"] == 2 and d["prediction"]["hits"] == 1
        assert d["prediction"]["hit_rate"] == 0.5
    finally:
        db.query(Prediction).filter(Prediction.conversation_id == cid).delete(synchronize_session=False)
        db.query(MemoryItem).filter(MemoryItem.character_id == cpid).delete(synchronize_session=False)
        db.query(CharacterObservation).filter(CharacterObservation.character_id == cpid).delete(synchronize_session=False)
        db.query(TraitHypothesis).filter(TraitHypothesis.character_id == cpid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.delete(db.get(Character, cpid)); db.commit(); db.close()


def test_counterpart_memory_unknown_returns_empty():
    db = SessionLocal()
    conv = Conversation(title="空记忆", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    cid = conv.id
    try:
        d = client.get(f"/api/v1/chat/conversations/{cid}/counterpart-memory", params={"name": "查无此人"}).json()
        assert d["character_id"] is None and d["learnings"] == []
    finally:
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
