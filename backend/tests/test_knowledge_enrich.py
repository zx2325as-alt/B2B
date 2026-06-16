"""上传资料自动充实档案：knowledge 上传除入向量库外，把资料抽取成立体档案融合进角色。
打桩 generate_import_profile（不调真实 LLM），验证 RAG 碎片 + 档案充实两条路都生效。"""
import app.api.characters as chars_api
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import SessionLocal
from app.models.sql_models import (
    Character, MemoryItem, CharacterObservation, PersonalitySnapshot, EvidenceSpan,
)

client = TestClient(app)


async def _fake_profile(**kw):
    return {
        "role": "产品经理",
        "motivation": "渴望被认可，证明自己",
        "weakness": "怕被否定",
        "personality_tags": ["强势", "敏感"],
        "core_traits": {"neuroticism": 0.6},
        "extended": {
            "fears": [{"content": "害怕被否定"}],
            "interpersonal_patterns": [{"context": "被质疑时", "pattern": "先反击再冷处理"}],
            "values": ["重视效率"],
        },
        "conflicts": [],
    }


def _cleanup(db, cid):
    for model in (MemoryItem, CharacterObservation, PersonalitySnapshot, EvidenceSpan):
        db.query(model).filter(model.character_id == cid).delete(synchronize_session=False)
    db.delete(db.get(Character, cid))
    db.commit()


def test_upload_enriches_profile_and_keeps_rag(monkeypatch):
    monkeypatch.setattr(chars_api.orchestrator, "generate_import_profile", _fake_profile)
    db = SessionLocal()
    char = Character(name="充实测试甲", role="")
    db.add(char); db.commit(); db.refresh(char)
    cid = char.id
    try:
        doc = ("赵明表面强势内心怕被否定，被质疑就反击或冷处理，重视效率，最怕努力被当作理所当然。" * 2).encode("utf-8")
        r = client.post(f"/api/v1/characters/{cid}/knowledge",
                        files={"file": ("赵明.txt", doc, "text/plain")}, params={"enrich_profile": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["chunks_added"] >= 1          # RAG 碎片仍入库
        assert body["profile_enriched"] is True   # 同时充实了档案

        db.expire_all(); char = db.get(Character, cid)
        pj = char.profile_json or {}
        assert pj.get("fears"), "恐惧维度应被充实"
        assert pj.get("interpersonal_patterns"), "人际模式应被充实"
        assert char.motivation  # 文本字段也被补全（原为空）
        # RAG 与档案并存
        assert db.query(MemoryItem).filter(MemoryItem.character_id == cid,
                                           MemoryItem.memory_type == "reference").count() >= 1
    finally:
        _cleanup(db, cid); db.close()


def test_upload_can_skip_enrich(monkeypatch):
    called = {"n": 0}
    async def _spy(**kw):
        called["n"] += 1
        return {}
    monkeypatch.setattr(chars_api.orchestrator, "generate_import_profile", _spy)
    db = SessionLocal()
    char = Character(name="充实测试乙", role="")
    db.add(char); db.commit(); db.refresh(char)
    cid = char.id
    try:
        doc = ("一些与该人物相关的较长资料内容用于切块。" * 3).encode("utf-8")
        r = client.post(f"/api/v1/characters/{cid}/knowledge",
                        files={"file": ("x.txt", doc, "text/plain")}, params={"enrich_profile": False})
        assert r.status_code == 200
        assert r.json()["profile_enriched"] is False
        assert called["n"] == 0  # 关闭开关时不触发档案抽取
    finally:
        _cleanup(db, cid); db.close()
