"""R2 三层收敛：_finalize_message 把 原始→critic纠偏→debate调和 收敛成一个 final 结论。
final.subtext = 调和 > 复核修订 > 原始；alternative 仅在对抗认为势均力敌/更强时挂出。"""
from app.api.chat import _finalize_message
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Message, MessagePerspective


def test_finalize_prefers_reconciled_then_revised_then_original():
    db = SessionLocal()
    conv = Conversation(title="收敛", self_name="我"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="对方", content="随便")
    db.add(m); db.commit(); db.refresh(m)
    # 视角1（对方自述）：有 debate.reconciled → final 用 reconciled，且 stronger=both 挂出 alternative
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, viewer_name="对方", stance="speaker", subtext="原始脑补",
        analysis_json={"confidence": 0.4, "subtext": "原始脑补",
                       "critic": {"verdict": "downgraded", "revised_subtext": "复核收敛版"},
                       "debate": {"stronger": "both", "alternative": {"subtext": "另一种"},
                                  "reconciled": {"subtext": "调和版"}}}))
    # 视角2（我观察）：只有 critic、无 debate → final 用 revised，无 alternative
    db.add(MessagePerspective(
        conversation_id=conv.id, message_id=m.id, viewer_name="我", stance="observer", subtext="我原始",
        analysis_json={"confidence": 0.5, "subtext": "我原始",
                       "critic": {"verdict": "softened", "revised_subtext": "我复核版"}}))
    db.commit()
    cid, mid = conv.id, m.id
    try:
        n = _finalize_message(db, m)
        assert n == 2
        rows = {p.viewer_name: p.analysis_json["final"]
                for p in db.query(MessagePerspective).filter(MessagePerspective.message_id == mid).all()}
        assert rows["对方"]["subtext"] == "调和版"        # reconciled 优先
        assert rows["对方"]["alternative"] == "另一种"      # stronger=both → 挂出另一种
        assert rows["对方"]["verdict"] == "downgraded"
        assert rows["我"]["subtext"] == "我复核版"          # 无 debate → 用 critic 修订版
        assert rows["我"]["alternative"] == ""             # 无 debate → 不挂 alternative
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
