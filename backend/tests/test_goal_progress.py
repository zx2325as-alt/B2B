"""目标进度追踪：连续分段增量评估 + 缓存 + 改目标重置。打桩 orchestrator，不调真实 LLM。"""
import app.api.chat as chat
from app.api.chat import _refresh_goal_progress
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import Conversation, Message
from fastapi.testclient import TestClient
import asyncio

client = TestClient(app)


def _mk(db, goal="约她出来"):
    conv = Conversation(title="目标测试", self_name="小林", goal=goal)
    db.add(conv); db.commit(); db.refresh(conv)
    return conv


def _msg(db, conv, role, name, content, idx):
    db.add(Message(conversation_id=conv.id, role=role, message_index=idx, character_name=name, content=content))
    db.commit()


def _cleanup(db, cid):
    db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
    db.delete(db.get(Conversation, cid)); db.commit()


def test_refresh_assesses_only_new_and_accumulates(monkeypatch):
    calls = {"seen": []}
    async def fake_assess(me, goal, prev_state, new_dialogue):
        calls["seen"].append(new_dialogue)
        return {"segments": [{"summary": "她答应考虑", "direction": "advance", "delta": 0.2}],
                "current_score": 0.45, "trend": "rising", "blocker": "她还在犹豫时间", "next_lever": "给两个具体时间二选一"}
    monkeypatch.setattr(chat.orchestrator, "assess_goal_progress", fake_assess)

    db = SessionLocal()
    conv = _mk(db)
    _msg(db, conv, "user", "小林", "周末一起吃饭？", 0)
    _msg(db, conv, "assistant", "阿杰", "可以考虑下", 1)
    cid = conv.id
    try:
        prog = asyncio.run(_refresh_goal_progress(cid))
        assert prog["score"] == 0.45
        assert prog["trend"] == "rising"
        assert prog["blocker"]
        assert prog["assessed_until_index"] == 1
        assert len(prog["segments"]) == 1

        # 再追加一轮 → 只评估新对话，段累积
        _msg(db, conv, "user", "小林", "那周六晚怎么样？", 2)
        _msg(db, conv, "assistant", "阿杰", "周六啊…我看看", 3)
        prog2 = asyncio.run(_refresh_goal_progress(cid))
        assert prog2["assessed_until_index"] == 3
        assert len(prog2["segments"]) == 2          # 累积
        assert "周六" in calls["seen"][-1]          # 只把新对话喂进去
        assert "周末一起吃饭" not in calls["seen"][-1]
    finally:
        _cleanup(db, cid); db.close()


def test_no_goal_skips(monkeypatch):
    called = {"n": 0}
    async def spy(*a, **k):
        called["n"] += 1; return {}
    monkeypatch.setattr(chat.orchestrator, "assess_goal_progress", spy)
    db = SessionLocal()
    conv = _mk(db, goal="")
    _msg(db, conv, "user", "小林", "随便聊聊", 0)
    cid = conv.id
    try:
        prog = asyncio.run(_refresh_goal_progress(cid))
        assert prog == {}
        assert called["n"] == 0
    finally:
        _cleanup(db, cid); db.close()


def test_changing_goal_resets_progress():
    db = SessionLocal()
    conv = _mk(db, goal="约她出来")
    conv.goal_progress_json = {"score": 0.5, "assessed_until_index": 3, "segments": [{"summary": "x"}]}
    db.commit()
    cid = conv.id
    try:
        r = client.patch(f"/api/v1/chat/conversations/{cid}", json={"goal": "改成谈成合作"})
        assert r.status_code == 200
        db.expire_all()
        c = db.get(Conversation, cid)
        assert c.goal == "改成谈成合作"
        assert (c.goal_progress_json or {}) == {}   # 目标变了，进度清空重算
    finally:
        _cleanup(db, cid); db.close()


def test_endpoints(monkeypatch):
    async def fake_assess(*a, **k):
        return {"segments": [{"summary": "推进了", "direction": "advance", "delta": 0.1}],
                "current_score": 0.3, "trend": "rising", "blocker": "", "next_lever": "继续"}
    monkeypatch.setattr(chat.orchestrator, "assess_goal_progress", fake_assess)
    db = SessionLocal()
    conv = _mk(db)
    _msg(db, conv, "user", "小林", "一起出来玩呀", 0)
    cid = conv.id
    try:
        # GET 缓存（还没评估）
        g0 = client.get(f"/api/v1/chat/conversations/{cid}/goal-progress").json()
        assert g0["goal"] == "约她出来" and g0["progress"] == {}
        # refresh 触发评估
        g1 = client.post(f"/api/v1/chat/conversations/{cid}/goal-progress/refresh").json()
        assert g1["progress"]["score"] == 0.3
        # GET 现在有缓存
        g2 = client.get(f"/api/v1/chat/conversations/{cid}/goal-progress").json()
        assert g2["progress"]["score"] == 0.3
    finally:
        _cleanup(db, cid); db.close()
