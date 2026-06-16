"""P1 破冷启动：档案薄/空的在场角色，分析前用本会话对话推断「临时画像」注入上下文（不落主档案）。
验证 _is_thin_profile 判据 + _augment_cold_start 只为缺料的人推断 + 缓存防重复打 LLM。"""
import asyncio

import app.api.chat as chat
from app.api.chat import _augment_cold_start, _is_thin_profile, _quick_profile_cache
from app.api.deps import SessionLocal
from app.models.sql_models import Character, Conversation, Message


def _setup(db):
    conv = Conversation(title="冷启动", self_name="我")
    db.add(conv); db.commit(); db.refresh(conv)
    db.add(Character(name="我", motivation="想拉近关系", personality_tags=["直接"]))  # 有料
    db.add(Character(name="陌生人"))  # 全空 → thin
    db.commit()
    for i, (spk, txt) in enumerate([("我", "周末有空吗一起吃饭"), ("陌生人", "看情况吧 不一定"), ("我", "那我等你消息")]):
        db.add(Message(conversation_id=conv.id, role="user", message_index=i, character_name=spk, content=txt))
    db.commit()
    return conv


def _cleanup(db, cid):
    db.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
    db.delete(db.get(Conversation, cid)); db.commit()
    for nm in ("我", "陌生人"):
        c = db.query(Character).filter(Character.name == nm).first()
        if c:
            db.delete(c)
    db.commit()
    _quick_profile_cache.clear()


def test_is_thin_profile():
    assert _is_thin_profile(None) is True
    assert _is_thin_profile(Character(name="x")) is True                       # 全空 → thin
    assert _is_thin_profile(Character(name="y", motivation="想升职")) is False  # 有动机 → 不 thin


def test_cold_start_injects_only_thin_and_caches(monkeypatch):
    calls = {"n": 0}

    async def fake_infer(name, dialogue, scenario=""):
        calls["n"] += 1
        return [{"category": "在意点", "content": f"{name}怕被忽视", "evidence": "不一定"}]

    monkeypatch.setattr(chat.orchestrator, "infer_quick_profile", fake_infer)

    db = SessionLocal()
    _quick_profile_cache.clear()
    conv = _setup(db)
    cid = conv.id
    try:
        dialogue = chat._recent_dialogue_text(db, conv)
        block = asyncio.run(_augment_cold_start(db, conv, ["我", "陌生人"], dialogue))
        assert "陌生人·临时画像" in block      # 缺料的人被补
        assert "我·临时画像" not in block       # 有料的人不补
        assert calls["n"] == 1
        # 消息数未增长 → 命中缓存，不重复推断
        block2 = asyncio.run(_augment_cold_start(db, conv, ["我", "陌生人"], dialogue))
        assert calls["n"] == 1
        assert "陌生人·临时画像" in block2
    finally:
        _cleanup(db, cid); db.close()


def test_cold_start_skips_when_dialogue_too_short():
    db = SessionLocal()
    _quick_profile_cache.clear()
    conv = _setup(db)
    cid = conv.id
    try:
        assert asyncio.run(_augment_cold_start(db, conv, ["陌生人"], "短")) == ""  # 对话太少不推断
    finally:
        _cleanup(db, cid); db.close()
