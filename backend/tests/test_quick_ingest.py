"""P2 整段粘贴秒录入：确定性切分 + 预览/提交端点。
提交用 analyze_last=0 跳过后台 LLM 分析，只验证消息批量落库正确（index 递增、receiver 归位、自动建角色、设 self_name）。"""
from app.api.chat import _split_dialogue_segments
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import Character, Conversation, Message
from fastapi.testclient import TestClient

client = TestClient(app)


def test_split_handles_both_colons_and_continuation():
    segs = _split_dialogue_segments("阿杰: 在吗\n小敏：怎么了\n阿杰: 周末那个事\n还算数吗\n小敏: 随便吧")
    assert len(segs) == 4
    assert segs[0] == {"speaker": "阿杰", "content": "在吗"}
    assert segs[2]["content"] == "周末那个事\n还算数吗"   # 无标签续行并入上一条


def test_preview_deterministic():
    db = SessionLocal()
    conv = Conversation(title="录入预览", self_name="小敏")
    db.add(conv); db.commit(); db.refresh(conv)
    cid = conv.id
    try:
        r = client.post(f"/api/v1/chat/conversations/{cid}/quick-ingest/preview",
                        json={"text": "阿杰: 在吗\n小敏: 怎么了\n阿杰: 周末有空吗"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["method"] == "deterministic"
        assert len(data["segments"]) == 3
        assert set(data["speakers"]) == {"阿杰", "小敏"}
        assert data["self_name"] == "小敏"
    finally:
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_commit_creates_messages_and_characters():
    db = SessionLocal()
    conv = Conversation(title="录入提交")
    db.add(conv); db.commit(); db.refresh(conv)
    cid = conv.id
    try:
        payload = {
            "self_name": "小敏",
            "analyze_last": 0,   # 跳过后台分析，避免测试打 LLM
            "segments": [
                {"speaker": "阿杰", "content": "在吗"},
                {"speaker": "小敏", "content": "怎么了"},
                {"speaker": "阿杰", "content": "周末有空吗"},
            ],
        }
        r = client.post(f"/api/v1/chat/conversations/{cid}/quick-ingest/commit", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["created"] == 3
        assert data["self_name"] == "小敏"
        assert data["counterpart"] == "阿杰"
        assert data["analyzing"] == []   # analyze_last=0

        db.expire_all()
        conv2 = db.get(Conversation, cid)
        assert conv2.self_name == "小敏"   # 提交时设定「我」
        msgs = db.query(Message).filter(Message.conversation_id == cid).order_by(Message.message_index).all()
        assert [m.message_index for m in msgs] == [1, 2, 3]   # max+1 递增
        assert msgs[0].character_name == "阿杰" and msgs[0].receiver_name == "小敏"
        assert msgs[1].character_name == "小敏" and msgs[1].receiver_name == "阿杰"  # 我说话→收信人是对方
        # 缺失角色被自动补建
        assert db.query(Character).filter(Character.name == "阿杰").first() is not None
        assert db.query(Character).filter(Character.name == "小敏").first() is not None
    finally:
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        for nm in ("阿杰", "小敏"):
            c = db.query(Character).filter(Character.name == nm).first()
            if c:
                db.delete(c)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
