"""重构后：核心读是「一次推理直接出终版」。_save_perspectives 应把单次输出的
final_thought / alternative / 收敛后的情绪标签 直接写成 analysis_json.final（无需后台覆盖）。"""
from app.api.chat import _save_perspectives
from app.api.deps import SessionLocal
from app.models.sql_models import Conversation, Message, MessagePerspective


def test_save_writes_final_directly_from_single_pass():
    db = SessionLocal()
    conv = Conversation(title="一次推理", self_name="xxx"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="abc",
                receiver_name="xxx", content="再说吧")
    db.add(m); db.commit(); db.refresh(m)
    # 模拟 analyze_multi_perspective 归一化后的单视角输出（自带 final_thought + alternative）
    persp = {
        "viewer": "abc", "stance": "speaker",
        "evidence": "再说吧", "confidence": 0.7, "grounded": True,
        "final_thought": "他在拖，不想正面拒绝，但没把话说死",
        "alternative": "也可能是真忙、没空细想",
        "tags": {"primary": "软性拒绝", "secondary": "低成本回应", "relation": "弱连接"},
        "emotions": {"deep": {"label": "敷衍", "score": 5}},
        "emotion_label": "试图激发:随意(4)｜表层:敷衍(5)｜深层:无感(4)｜压抑:回避(3)",
        "emotion_score": 0.4,
        "inner_monologue_text": "哼，懒得展开",
        "inner_monologue": {"first_reaction": "哼"},
        "strategy": {"short_term": "拖", "long_term": "观望", "consistency_note": ""},
        "subtext": "用'再说吧'拖延，不给承诺",
        "psychological_tag": "主:软性拒绝",
    }
    cid, mid = conv.id, m.id
    try:
        n = _save_perspectives(db, cid, m, "abc", [persp], "xxx")
        db.commit()
        assert n == 1
        row = db.query(MessagePerspective).filter(MessagePerspective.message_id == mid).first()
        f = (row.analysis_json or {}).get("final") or {}
        assert f["inner_monologue"] == "他在拖，不想正面拒绝，但没把话说死"   # = final_thought
        assert f["alternative"] == "也可能是真忙、没空细想"
        assert f["stronger"] == "both"                                      # 有 alternative
        assert f["tags"] == ["主:软性拒绝", "次:低成本回应", "关系:弱连接"]
        assert "敷衍" in f["emotion_label"]
        assert f["synthesized"] is True
        assert f["confidence"] == 0.7 and f["grounded"] is True             # 引用在原文 → 不降级
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()


def test_save_caps_confidence_when_evidence_not_in_utterance():
    db = SessionLocal()
    conv = Conversation(title="接地", self_name="xxx"); db.add(conv); db.commit(); db.refresh(conv)
    m = Message(conversation_id=conv.id, role="user", message_index=0, character_name="abc", content="嗯")
    db.add(m); db.commit(); db.refresh(m)
    persp = {"viewer": "abc", "stance": "speaker", "evidence": "我想约你吃饭",  # 原文里没有
             "confidence": 0.9, "grounded": True, "final_thought": "他想约饭",
             "tags": {"primary": "邀约"}, "emotions": {}, "emotion_label": "", "subtext": ""}
    cid, mid = conv.id, m.id
    try:
        _save_perspectives(db, cid, m, "abc", [persp], "xxx"); db.commit()
        f = (db.query(MessagePerspective).filter(MessagePerspective.message_id == mid).first().analysis_json or {}).get("final") or {}
        assert f["grounded"] is False and f["confidence"] <= 0.45            # 引用不实 → 降为推测
    finally:
        db.query(MessagePerspective).filter(MessagePerspective.conversation_id == cid).delete(synchronize_session=False)
        db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.delete(db.get(Conversation, cid)); db.commit(); db.close()
