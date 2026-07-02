"""停止 AI 模拟后，关系走势/情绪张力/归档/诊断 改从「用户消息的多视角分析」读数据。
验证 _msg_emotion_strategy + trajectory/tension 端点 + diagnose 端点（打桩）。"""
import app.api.chat as chat
from app.api.chat import _msg_emotion_strategy
from app.api.deps import SessionLocal
from app.main import app
from app.models.sql_models import Conversation, Character, Message, MessagePerspective
from fastapi.testclient import TestClient

client = TestClient(app)


def _persp(conv_id, mid, viewer, stance, emotions=None, strategy=None, is_primary=False, emotion_label=""):
    return MessagePerspective(
        conversation_id=conv_id, message_id=mid, speaker_name="", viewer_name=viewer,
        stance=stance, is_primary=is_primary, subtext="某策略动机", emotion_label=emotion_label,
        analysis_json={"emotions": emotions or {}, "strategy": strategy or {}},
    )


def _setup(db):
    conv = Conversation(title="迁移测试", self_name="小林")
    db.add(conv); db.commit(); db.refresh(conv)
    for nm in ("小林", "阿哲"):
        if not db.query(Character).filter(Character.name == nm).first():
            db.add(Character(name=nm))
    db.commit()
    # 小林→阿哲 一条，带视角（阿哲观察者情绪 + 小林发言者策略）
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="小林",
                receiver_name="阿哲", content="周末一起吃饭？")
    db.add(m); db.commit(); db.refresh(m)
    db.add(_persp(conv.id, m.id, "小林", "speaker", strategy={"short_term": "邀约", "long_term": "拉近"}))
    db.add(_persp(conv.id, m.id, "阿哲", "observer", is_primary=True, emotion_label="好奇",
                  emotions={"intended": {"label": "友好", "score": 6}, "surface": {"label": "平静", "score": 5},
                            "deep": {"label": "好奇", "score": 7}, "suppressed": {"label": "犹豫", "score": 4}}))
    db.commit()
    return conv, m


def _cleanup(db, cid):
    db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
    db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
    db.delete(db.get(Conversation, cid)); db.commit()


def test_msg_emotion_strategy_reads_from_perspectives():
    db = SessionLocal()
    conv, m = _setup(db)
    cid = conv.id
    try:
        emo, strat = _msg_emotion_strategy(db, m)
        assert (emo.get("deep") or {}).get("label") == "好奇"      # 接收方观察者情绪
        assert (emo.get("intended") or {}).get("label") == "友好"
        assert strat.get("short_term") == "邀约"                   # 发言者策略
    finally:
        _cleanup(db, cid); db.close()


def test_trajectory_and_tension_from_perspectives():
    db = SessionLocal()
    conv, m = _setup(db)
    cid = conv.id
    try:
        tr = client.get(f"/api/v1/chat/conversations/{cid}/relationship-trajectory",
                        params={"source": "小林", "target": "阿哲"}).json()
        assert len(tr["points"]) == 1   # 从用户消息视角推出走势点（不再依赖 assistant 消息）
        te = client.get(f"/api/v1/chat/conversations/{cid}/emotion-tension",
                        params={"source": "小林", "target": "阿哲"}).json()
        assert len(te["emotions"]) == 1
        assert any(k["label"] == "好奇" for k in te["emotion_keywords"])
    finally:
        _cleanup(db, cid); db.close()


def test_diagnose_uses_user_message_perspectives(monkeypatch):
    # 诊断不再要 assistant 消息；打桩诊断管线，验证用视角构建 analysis_result 并落库
    seen = {}
    async def fake_diag(db, **kw):
        from app.models.sql_models import StructuredDiagnosis
        seen["analysis"] = kw["analysis_result"]   # 验证 analysis_result 来自视角
        rep = StructuredDiagnosis(conversation_id=kw["conv"].id, message_id=kw["user_msg"].id,
                                  confidence=0.7, status="approved",
                                  result_json={"summary": "测试诊断"}, critic_json={})
        db.add(rep); db.commit(); db.refresh(rep)
        return rep
    # 诊断已抽到 services/diagnosis_service：在那儿打桩（_run_diagnosis_for_message 在服务内构建 analysis_result 后调它）
    import app.services.diagnosis_service as diagsvc
    monkeypatch.setattr(diagsvc, "run_structured_diagnosis", fake_diag)
    monkeypatch.setattr(diagsvc, "build_evidence_pack", lambda *a, **k: {})

    db = SessionLocal()
    conv, m = _setup(db)
    cid, mid = conv.id, m.id
    try:
        r = client.post(f"/api/v1/chat/messages/{mid}/diagnose")
        assert r.status_code == 200, r.text
        # analysis_result 取自接收方观察视角（阿哲 deep=好奇）
        assert seen["analysis"]["emotion_label"] == "好奇"
    finally:
        from app.models.sql_models import StructuredDiagnosis
        db.query(StructuredDiagnosis).filter(StructuredDiagnosis.conversation_id == cid).delete(synchronize_session=False)
        _cleanup(db, cid); db.close()


def test_diagnose_400_without_perspectives():
    db = SessionLocal()
    conv = Conversation(title="无视角", self_name="小林")
    db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="小林", content="在吗")
    db.add(m); db.commit(); db.refresh(m)
    cid, mid = conv.id, m.id
    try:
        assert client.post(f"/api/v1/chat/messages/{mid}/diagnose").status_code == 400
    finally:
        _cleanup(db, cid); db.close()
