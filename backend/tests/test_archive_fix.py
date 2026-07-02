"""#1 稳定性回归：停 AI 模拟后归档不再因 `analysis`(None) 崩溃。
归档应从「观察视角」取潜台词/情绪/策略，正常产出关系回流与观察，不抛 AttributeError。"""
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import Character, Conversation, Message, MessagePerspective, CharacterObservation
from fastapi.testclient import TestClient

client = TestClient(app)


def test_archive_does_not_crash_and_uses_perspective():
    db = SessionLocal()
    conv = Conversation(title="归档回归", self_name="小敏")
    db.add(conv); db.commit(); db.refresh(conv)
    for nm in ("小敏", "阿哲"):
        if not db.query(Character).filter(Character.name == nm).first():
            db.add(Character(name=nm))
    db.commit()
    # 小敏→阿哲 一条 user 消息，挂观察视角(阿哲)，subtext 含"矛盾"以触发冲突分支(原 analysis.subtext 崩溃点)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="小敏",
                receiver_name="阿哲", content="你到底来不来，别老是矛盾")
    db.add(m); db.commit(); db.refresh(m)
    # 发言者自述视角（小敏）：策略 long_term 取自这里
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, speaker_name="小敏", viewer_name="小敏",
        stance="speaker", subtext="嘴上催、其实怕被拒",
        analysis_json={"strategy": {"short_term": "催", "long_term": "想确认对方在意自己", "consistency_note": ""},
                       "tags": {"primary": "施压"}}))
    # 观察视角（阿哲）：潜台词/情绪取自这里；subtext 含"矛盾"触发冲突分支
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, speaker_name="小敏", viewer_name="阿哲",
        stance="observer", is_primary=True, subtext="她话里有矛盾：嘴上催、其实怕被拒",
        emotion_label="试图激发:施压(6)｜表层:急(6)｜深层:不安(6)｜压抑:怕(5)",
        analysis_json={"emotions": {"deep": {"label": "不安", "score": 6}, "intended": {"label": "施压", "score": 6}},
                       "tags": {"primary": "回应"}}))
    db.commit()
    cid, cpid = conv.id, db.query(Character).filter(Character.name == "小敏").first().id
    try:
        r = client.post(f"/api/v1/chat/conversations/{cid}/archive", json={"role_names": ["小敏", "阿哲"]})
        assert r.status_code == 200, r.text          # 不再崩
        data = r.json()
        assert "小敏" in data["archived_roles"]
        # 行为模式(long_term) + 冲突(矛盾) 两条观察应被创建，且来源是观察视角而非已废弃的 analysis
        obs = db.query(CharacterObservation).filter(CharacterObservation.character_id == cpid).all()
        reasons = " ".join((o.reason or "") for o in obs)
        assert "想确认对方在意自己" in reasons        # long_term 来自视角 strategy
        assert "矛盾" in reasons                       # 冲突分支用 arch_subtext，没崩
    finally:
        from app.models.sql_models import EvidenceSpan, MemoryItem, Relationship, AgentRun
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(EvidenceSpan).filter(EvidenceSpan.conversation_id == cid).delete(synchronize_session=False)
        db.query(CharacterObservation).filter(CharacterObservation.character_id == cpid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit()
        for nm in ("小敏", "阿哲"):
            c = db.query(Character).filter(Character.name == nm).first()
            if c:
                db.query(MemoryItem).filter(MemoryItem.character_id == c.id).delete(synchronize_session=False)
                db.query(Relationship).filter((Relationship.source_id == c.id) | (Relationship.target_id == c.id)).delete(synchronize_session=False)
                db.delete(c)
        db.commit(); db.close()
