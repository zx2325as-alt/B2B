"""A/D/E：对方回复自动应对建议（_generate_counterpart_advice 门控 + /advise 端点）
与 回退上一轮（/rollback）。打桩 orchestrator，避免真实 LLM。"""
import app.api.chat as chat
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import SessionLocal
from app.models.sql_models import Character, Conversation, Message, MessagePerspective

client = TestClient(app)


def _mk_conv(db, self_name="小林"):
    conv = Conversation(title="军师测试", self_name=self_name)
    db.add(conv); db.commit(); db.refresh(conv)
    return conv


def _mk_msg(db, conv, role, name, content, idx):
    m = Message(conversation_id=conv.id, role=role, message_index=idx, character_name=name, content=content)
    db.add(m); db.commit(); db.refresh(m)
    return m


# ── A/D：对方回复 → 自动洞察‖行动 ───────────────────────────
def test_advise_generates_perspectives_for_counterpart(monkeypatch):
    async def fake_multi(**kw):
        return [
            {"viewer": "阿杰", "stance": "speaker", "evidence": "在吗", "confidence": 0.7,
             "moves": [], "inner_monologue": {}, "emotions": {}, "strategy": {}, "tags": {}},
            {"viewer": "小林", "stance": "observer", "evidence": "在吗", "confidence": 0.6,
             "moves": [{"label": "正面回应", "reply": "在的，怎么了？", "consequence": "推进对话"}],
             "inner_monologue": {}, "emotions": {}, "strategy": {}, "tags": {}},
        ]
    monkeypatch.setattr(chat.orchestrator, "analyze_multi_perspective", fake_multi)

    async def fake_critic(utterance, perspectives_payload, evidence_block=""):
        return {"overall": "", "reviewed": []}   # 自动复核打桩，避免真实 LLM
    monkeypatch.setattr(chat.orchestrator, "critique_perspectives", fake_critic)

    db = SessionLocal()
    conv = _mk_conv(db, self_name="小林")
    reply = _mk_msg(db, conv, "assistant", "阿杰", "在吗，找我有事？", 1)
    cid, rid = conv.id, reply.id
    try:
        r = client.post(f"/api/v1/chat/messages/{rid}/advise")
        assert r.status_code == 200, r.text
        assert r.json()["perspectives_saved"] >= 1
        # 视角挂在该回复消息自身上 → 前端 selfTwoCol 可读
        n = db.query(MessagePerspective).filter(MessagePerspective.message_id == rid).count()
        assert n >= 1
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_advise_rejects_when_speaker_is_me():
    db = SessionLocal()
    conv = _mk_conv(db, self_name="小林")
    mine = _mk_msg(db, conv, "user", "小林", "我说的话", 0)  # 发言者就是「我」
    cid, mid = conv.id, mine.id
    try:
        r = client.post(f"/api/v1/chat/messages/{mid}/advise")
        assert r.status_code == 400  # 我自己的话不需要"我该怎么接"
    finally:
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_advise_rejects_without_self_name():
    db = SessionLocal()
    conv = _mk_conv(db, self_name="")
    msg = _mk_msg(db, conv, "assistant", "阿杰", "在吗", 1)
    cid, mid = conv.id, msg.id
    try:
        r = client.post(f"/api/v1/chat/messages/{mid}/advise")
        assert r.status_code == 400  # 没指定「我」无法给建议
    finally:
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


# ── E：回退上一轮 ───────────────────────────────────────────
def test_rollback_removes_last_turn():
    db = SessionLocal()
    conv = _mk_conv(db)
    m0_id = _mk_msg(db, conv, "user", "小林", "第一轮我", 0).id
    m1_id = _mk_msg(db, conv, "assistant", "阿杰", "第一轮他", 1).id
    _mk_msg(db, conv, "user", "小林", "第二轮我", 2)
    m3_id = _mk_msg(db, conv, "assistant", "阿杰", "第二轮他", 3).id
    # 给最后一轮挂个视角，确认一并删除
    db.add(MessagePerspective(conversation_id=conv.id, message_id=m3_id, speaker_name="阿杰", viewer_name="小林", stance="observer"))
    db.commit()
    cid = conv.id
    try:
        r = client.post(f"/api/v1/chat/conversations/{cid}/rollback")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["removed"] == 2  # 删 m2 + m3（最近一轮）
        assert body["remaining"] == 2  # 剩 m0 + m1
        remaining_ids = {m.id for m in db.query(Message).filter(Message.conversation_id == cid).all()}
        assert remaining_ids == {m0_id, m1_id}
        # 视角随之删除
        assert db.query(MessagePerspective).filter(MessagePerspective.message_id == m3_id).count() == 0
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_rollback_empty_conversation_400():
    db = SessionLocal()
    conv = _mk_conv(db)
    cid = conv.id
    try:
        r = client.post(f"/api/v1/chat/conversations/{cid}/rollback")
        assert r.status_code == 400  # 没有可回退的消息
    finally:
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
