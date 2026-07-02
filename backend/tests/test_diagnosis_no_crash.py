"""回归：停 AI 模拟后深度诊断的 ai_msg 恒为 None，_run_structured_diagnosis 不得因
`analysis_message_id=ai_msg.id` 崩溃（曾静默回退导致诊断永远 502）。打桩诊断 LLM。"""
import asyncio

import app.api.chat as chat
from app.api.chat import _run_diagnosis_for_message
from app.api.deps import SessionLocal
from app.models.sql_models import Character, Conversation, Message, MessagePerspective, StructuredDiagnosis


def test_diagnosis_no_crash_when_ai_msg_none(monkeypatch):
    async def fake_diag(ctx):
        return {"summary": "他在回避当前话题", "diagnosis_type": "subtext",
                "supporting_evidence": [], "conflicting_evidence": [],
                "alternative_explanations": [], "insufficient_evidence": [], "confidence": 0.5}
    async def fake_critic(diag, pack, profiles):
        return {"final_status": "approved", "confidence_adjustment": 0.0, "issues": [], "revised_summary": ""}
    monkeypatch.setattr(chat.orchestrator, "structured_diagnosis", fake_diag)
    monkeypatch.setattr(chat.orchestrator, "critique_diagnosis", fake_critic)
    monkeypatch.setattr(chat, "build_evidence_pack", lambda *a, **k: {})

    db = SessionLocal()
    conv = Conversation(title="诊断无崩", self_name="xxx"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="abc",
                receiver_name="xxx", content="再说吧")
    db.add(m); db.commit(); db.refresh(m)
    db.add(MessagePerspective(conversation_id=conv.id, message_id=m.id, speaker_name="abc",
                              viewer_name="xxx", stance="observer", is_primary=True,
                              subtext="他在回避", emotion_label="表层:敷衍(5)"))
    db.commit()
    cid, mid = conv.id, m.id
    try:
        report = asyncio.run(_run_diagnosis_for_message(db, m))   # ai_msg=None 内部传入
        assert report is not None                                  # 不再静默崩成 None
        assert report.message_id == mid
        assert report.analysis_message_id is None                  # 守卫生效
    finally:
        db.query(StructuredDiagnosis).filter(StructuredDiagnosis.conversation_id == cid).delete(synchronize_session=False)
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
