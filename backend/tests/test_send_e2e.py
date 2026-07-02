"""#4 端到端主干测试：POST /chat/send → 多视角分析(mock) → _save_perspectives 写 analysis_json.final
→ 该消息的 perspectives 带可读的 final（inner_monologue=final_thought、收敛情绪标签、应对 moves）。
全程 mock LLM / 证据包 / 冷启动 / 摘要，不打真实模型或 Neo4j，确保快且确定。"""
import json

import app.api.chat as chat
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import Character, Conversation, Message, MessagePerspective
from fastapi.testclient import TestClient

client = TestClient(app)


def _fake_perspectives():
    return [
        {"viewer": "abc", "stance": "speaker", "evidence": "在吗", "confidence": 0.7, "grounded": True,
         "final_thought": "我就想开个话头，看她搭不搭理", "alternative": "",
         "emotions": {"intended": {"label": "试探", "score": 5}, "surface": {"label": "平静", "score": 4},
                      "deep": {"label": "好奇", "score": 5}, "suppressed": {"label": "无", "score": 0}},
         "emotion_label": "试图激发:试探(5)｜表层:平静(4)｜深层:好奇(5)｜压抑:无(0)", "emotion_score": 0.5,
         "inner_monologue_text": "先抛一句在吗", "inner_monologue": {"first_reaction": "想聊"},
         "strategy": {"short_term": "开话题", "long_term": "", "consistency_note": ""},
         "subtext": "想开个话题", "psychological_tag": "主:破冰", "tags": {"primary": "破冰", "secondary": "", "relation": ""},
         "moves": []},
        {"viewer": "xxx", "stance": "observer", "evidence": "在吗", "confidence": 0.6, "grounded": True,
         "final_thought": "他来搭话，我自然接住就行", "alternative": "",
         "emotions": {"intended": {"label": "拉近", "score": 4}, "surface": {"label": "随和", "score": 5},
                      "deep": {"label": "好奇", "score": 4}, "suppressed": {"label": "无", "score": 0}},
         "emotion_label": "试图激发:拉近(4)｜表层:随和(5)｜深层:好奇(4)｜压抑:无(0)", "emotion_score": 0.4,
         "inner_monologue_text": "接住", "inner_monologue": {"first_reaction": "接住"},
         "strategy": {"short_term": "接话", "long_term": "", "consistency_note": ""},
         "subtext": "他想聊，我接住", "psychological_tag": "主:回应", "tags": {"primary": "回应", "secondary": "", "relation": ""},
         "moves": [{"label": "自然接话", "reply": "在的，怎么了", "consequence": "推进对话"}]},
    ]


def test_send_endpoint_writes_final(monkeypatch):
    async def fake_multi(**kw):
        return _fake_perspectives()
    async def fake_cold(*a, **k):
        return ""
    async def fake_summary(*a, **k):
        return {}
    monkeypatch.setattr(chat.orchestrator, "analyze_multi_perspective", fake_multi)
    monkeypatch.setattr(chat, "_augment_cold_start", fake_cold)
    monkeypatch.setattr(chat, "_refresh_context_summary", fake_summary)
    monkeypatch.setattr(chat, "build_evidence_pack", lambda *a, **k: {})      # 不打 Neo4j/RAG
    monkeypatch.setattr(chat, "render_evidence_pack", lambda *a, **k: "")
    monkeypatch.setattr(chat, "record_retrieval_trace", lambda *a, **k: None)

    db = SessionLocal()
    conv = Conversation(title="e2e", self_name="xxx")    # 不设 goal → 跳过目标进度后台
    db.add(conv); db.commit(); db.refresh(conv)
    abc = Character(name="abc", motivation="想认识新朋友")   # 有料 → 即便不 mock 冷启动也不 thin
    xxx = Character(name="xxx", motivation="会聊天")
    db.add_all([abc, xxx]); db.commit(); db.refresh(abc); db.refresh(xxx)
    cid = conv.id
    try:
        payload = {"conversation_id": cid, "speaker": "abc", "character_id": abc.id, "content": "在吗",
                   "receiver_name": "xxx",
                   "active_characters": [{"id": abc.id, "name": "abc"}, {"id": xxx.id, "name": "xxx"}]}
        r = client.post("/api/v1/chat/send", json=payload)
        assert r.status_code == 200, r.text
        assert "saved" in r.text                                   # SSE 落库事件

        msg = db.query(Message).filter(Message.conversation_id == cid, Message.role == "user").order_by(Message.id.desc()).first()
        assert msg is not None and msg.content == "在吗"
        persps = db.query(MessagePerspective).filter(MessagePerspective.message_id == msg.id).all()
        by_viewer = {p.viewer_name: p for p in persps}
        assert set(by_viewer) == {"abc", "xxx"}                    # 两视角都落库

        # 核心断言：每个视角的 analysis_json.final 立即就绪、字段可读（无需后台覆盖）
        f_abc = (by_viewer["abc"].analysis_json or {}).get("final") or {}
        assert f_abc["inner_monologue"] == "我就想开个话头，看她搭不搭理"   # = final_thought
        assert f_abc["synthesized"] is True
        assert "破冰" in f_abc["emotion_label"] or "试探" in f_abc["emotion_label"]
        assert f_abc["confidence"] == 0.7 and f_abc["grounded"] is True       # "在吗" 在原文 → 不降级

        f_xxx = (by_viewer["xxx"].analysis_json or {}).get("final") or {}
        assert f_xxx["inner_monologue"] == "他来搭话，我自然接住就行"
        # 我方应对 moves 进入 analysis_json，供前端"行动·我该怎么接"
        assert any(m.get("reply") == "在的，怎么了" for m in (by_viewer["xxx"].analysis_json or {}).get("moves") or [])
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid))
        for c in (db.get(Character, abc.id), db.get(Character, xxx.id)):
            if c:
                db.delete(c)
        db.commit(); db.close()
