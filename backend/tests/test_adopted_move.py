"""Q5 结果反馈闭环：采用某条建议发出 → _record_adopted_move 记一条 sent 预测（预期后果=预测），
复用预演对账机制，对方下条回复到达时自动判定这招有没有用。"""
from app.api.chat import _record_adopted_move
from app.api.deps import SessionLocal
from app.models.sql_models import Character, Conversation, Message, Prediction


def test_record_adopted_move_creates_sent_prediction():
    db = SessionLocal()
    conv = Conversation(title="反馈", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    cp = Character(name="老李"); db.add(cp); db.commit(); db.refresh(cp)
    # 一条对方历史消息，让默认 counterpart 推断为 老李（这里直接用 receiver_name 指定）
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="我",
                receiver_name="老李", content="这事我来定，你别操心")
    db.add(m); db.commit(); db.refresh(m)
    cid, mid = conv.id, m.id
    try:
        pred = _record_adopted_move(db, conv, m, "我", "他会松一口气、不再纠结", "主动接管")
        assert pred.status == "sent"
        assert pred.sent_message_id == mid
        assert pred.counterpart_name == "老李" and pred.counterpart_id == cp.id
        assert pred.reaction_type == "采纳建议"
        assert "松一口气" in pred.predicted_reply
        # 落库可被对账逻辑捞到（status=sent + sent_message_id 绑定）
        row = db.query(Prediction).filter(Prediction.conversation_id == cid, Prediction.status == "sent").first()
        assert row is not None and row.sent_message_id == mid
    finally:
        db.query(Prediction).filter(Prediction.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.delete(db.get(Character, cp.id)); db.commit(); db.close()
