"""预演闭环：预测落库 → 对账(review_prediction) → 回流学习 + 命中率统计。
打桩 orchestrator，不调真实 LLM。"""
import app.api.chat as chat
from app.api.chat import _resolve_prediction
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Character, Prediction, MemoryItem, TraitHypothesis
import asyncio


def _mk(db):
    conv = Conversation(title="预演测试", self_name="小林", goal="约出来")
    db.add(conv); db.commit(); db.refresh(conv)
    cp = Character(name="阿杰预演", role="对方")
    db.add(cp); db.commit(); db.refresh(cp)
    return conv, cp


def _cleanup(db, conv_id, cp_id):
    db.query(Prediction).filter(Prediction.conversation_id == conv_id).delete(synchronize_session=False)
    db.query(MemoryItem).filter(MemoryItem.character_id == cp_id).delete(synchronize_session=False)
    db.query(TraitHypothesis).filter(TraitHypothesis.character_id == cp_id).delete(synchronize_session=False)
    db.delete(db.get(Character, cp_id))
    db.delete(db.get(Conversation, conv_id))
    db.commit()


def test_resolve_scores_and_learns(monkeypatch):
    async def fake_review(*a, **k):
        return {"verdict": "miss", "reaction_match": False,
                "note": "预测他会暖化，实际却警惕", "lesson": "他被直接邀约时反而先警惕"}
    monkeypatch.setattr(chat.orchestrator, "review_prediction", fake_review)
    # 回流学习里会跑假设轮 + 算 embedding，都打桩掉避免真实调用
    async def fake_hypo(*a, **k):
        return {}
    monkeypatch.setattr(chat, "run_hypothesis_round", fake_hypo)
    monkeypatch.setattr("app.harness.embeddings.embed_text", lambda *a, **k: None)

    db = SessionLocal()
    conv, cp = _mk(db)
    pred = Prediction(conversation_id=conv.id, me_name="小林", counterpart_name=cp.name,
                      counterpart_id=cp.id, candidate="周末一起吃饭", predicted_reply="好啊",
                      reaction_type="暖化", success_likelihood=0.7, status="open")
    db.add(pred); db.commit(); db.refresh(pred)
    pid, cid, cpid = pred.id, conv.id, cp.id
    try:
        asyncio.run(_resolve_prediction(pid, sent_message_id=999, actual_reply="你谁啊？这么突然"))
        db.expire_all()
        p = db.get(Prediction, pid)
        assert p.status == "resolved"
        assert p.verdict == "miss"
        assert p.reaction_match is False
        assert "警惕" in p.lesson
        assert p.actual_reply.startswith("你谁啊")
        # 教训沉淀为可检索记忆（现实验证过 → 回流建模）
        mem = db.query(MemoryItem).filter(MemoryItem.character_id == cpid, MemoryItem.source == "预演对账").first()
        assert mem is not None and "警惕" in mem.content
    finally:
        _cleanup(db, cid, cpid); db.close()


def test_predict_persists_and_stats(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    async def fake_predict(*a, **k):
        return {"predicted_reply": "好啊", "reaction_type": "暖化", "success_likelihood": 0.7,
                "inner_read": "他挺乐意", "emotion": "愉快", "risk": "", "better_tip": ""}
    monkeypatch.setattr(chat.orchestrator, "predict_counterfactual", fake_predict)

    client = TestClient(app)
    db = SessionLocal()
    conv, cp = _mk(db)
    cid, cpid = conv.id, cp.id
    try:
        # 预演 → 落库 → 返回 prediction_id
        r = client.post(f"/api/v1/chat/conversations/{cid}/predict",
                        json={"candidate": "周末一起吃饭", "me": "小林", "counterpart": cp.name})
        assert r.status_code == 200, r.text
        assert r.json()["prediction_id"]
        assert db.query(Prediction).filter(Prediction.conversation_id == cid).count() == 1

        # 统计端点
        s = client.get(f"/api/v1/chat/conversations/{cid}/prediction-stats", params={"counterpart": cp.name}).json()
        assert s["total"] == 1 and s["open"] == 1 and s["resolved"] == 0
        assert s["hit_rate"] is None  # 还没对账
    finally:
        _cleanup(db, cid, cpid); db.close()
