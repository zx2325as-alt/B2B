"""Q2 自动深度诊断门控：_maybe_auto_diagnose 只对「对方」发言跑、且已有诊断不重复。
打桩 _run_diagnosis_for_message，避免真实 LLM。"""
import asyncio

import app.api.chat as chat
from app.api.chat import _maybe_auto_diagnose
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Message, StructuredDiagnosis


def _mk(db, self_name, speaker):
    conv = Conversation(title="诊断门控", self_name=self_name); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name=speaker, content="一句话")
    db.add(m); db.commit(); db.refresh(m)
    return conv, m


def _cleanup(db, cid):
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.conversation_id == cid).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
    db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_skips_my_own_message(monkeypatch):
    called = {"n": 0}
    async def fake_run(db, message):
        called["n"] += 1; return object()
    monkeypatch.setattr(chat, "_run_diagnosis_for_message", fake_run)
    db = SessionLocal(); conv, m = _mk(db, "我", "我"); cid = conv.id
    try:
        assert asyncio.run(_maybe_auto_diagnose(db, m)) is None   # 我自己的话不诊断
        assert called["n"] == 0
    finally:
        _cleanup(db, cid)


def test_runs_for_counterpart_then_dedups(monkeypatch):
    sentinel = object(); called = {"n": 0}
    async def fake_run(db, message):
        called["n"] += 1; return sentinel
    monkeypatch.setattr(chat, "_run_diagnosis_for_message", fake_run)
    db = SessionLocal(); conv, m = _mk(db, "我", "对方"); cid = conv.id
    try:
        assert asyncio.run(_maybe_auto_diagnose(db, m)) is sentinel   # 对方的话 → 诊断
        assert called["n"] == 1
        # 落一条诊断后再调用 → 去重，不重复跑
        db.add(StructuredDiagnosis(conversation_id=cid, message_id=m.id, confidence=0.7,
                                   status="approved", result_json={}, critic_json={}))
        db.commit(); called["n"] = 0
        assert asyncio.run(_maybe_auto_diagnose(db, m)) is None
        assert called["n"] == 0
    finally:
        _cleanup(db, cid)
