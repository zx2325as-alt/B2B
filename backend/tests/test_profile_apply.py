"""应用层：_apply_profile_candidate 融合策略、别名解析、角色合并"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.sql_models import (
    Base, Character, CharacterEvent, CharacterObservation, MemoryItem, Relationship,
)
from app.harness.graph_store import graph_store
from app.api.characters import _apply_profile_candidate
from app.services.identity import add_alias, find_character_by_name, merge_characters


@pytest.fixture(autouse=True)
def _disable_graph(monkeypatch):
    monkeypatch.setattr(graph_store, "enabled", False)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_char(db, name="测试角色", **kwargs):
    char = Character(name=name, personality_tags=[], core_traits={}, **kwargs)
    db.add(char)
    db.commit()
    db.refresh(char)
    return char


# ─── _apply_profile_candidate ────────────────────────────────────────────────

def test_apply_fills_empty_fields(db):
    char = _make_char(db)
    changed = _apply_profile_candidate(
        db, char, {"motivation": "夺回主导权", "personality_tags": ["强势"]},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert changed
    assert char.motivation == "夺回主导权"
    assert "强势" in char.personality_tags
    obs = db.query(CharacterObservation).filter_by(field="motivation").first()
    assert obs.status == "approved"
    assert obs.metadata_json["change_type"] == "新增"


def test_apply_merge_mode_deepens_existing(db):
    char = _make_char(db, motivation="夺回主导权")
    _apply_profile_candidate(
        db, char, {"motivation": "夺回主导权，并让所有低估过他的人付出代价"},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert "付出代价" in char.motivation
    obs = db.query(CharacterObservation).filter_by(field="motivation").first()
    assert obs.metadata_json["change_type"] == "深化"


def test_apply_shrink_guard_demotes_to_pending(db):
    rich = "夺回家族企业的实际控制权，并让所有低估过他的人付出代价"
    char = _make_char(db, motivation=rich)
    _apply_profile_candidate(
        db, char, {"motivation": "掌控公司"},  # 比现有内容短 → 信息量倒退
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert char.motivation == rich  # 未被覆盖
    obs = db.query(CharacterObservation).filter_by(field="motivation").first()
    assert obs.status == "pending"


def test_background_accumulates_never_loses_old_facts(db):
    old = "出身贸易世家，三十岁前接管家族生意。"
    char = _make_char(db, background=old)
    # 即使 AI 融合输出丢掉了旧事实，服务器端积累也会保留旧句子并追加新句子
    _apply_profile_candidate(
        db, char, {"background": "经历重大背叛后变得极度谨慎，对外人始终保持距离。"},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert "贸易世家" in char.background          # 旧事实保留
    assert "重大背叛" in char.background          # 新事实追加
    obs = db.query(CharacterObservation).filter_by(field="background").first()
    assert obs.metadata_json["change_type"] == "深化"


def test_background_skips_duplicate_sentences(db):
    old = "出身贸易世家，三十岁前接管家族生意。"
    char = _make_char(db, background=old)
    changed = _apply_profile_candidate(
        db, char, {"background": "出身贸易世家，三十岁前接管家族生意。"},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert char.background == old
    assert not changed


def test_apply_non_merge_mode_never_overwrites(db):
    char = _make_char(db, motivation="用户手填的动机")
    _apply_profile_candidate(
        db, char, {"motivation": "AI 生成的动机"},
        source="角色创建", evidence_note="测试", merge_mode=False,
    )
    assert char.motivation == "用户手填的动机"
    obs = db.query(CharacterObservation).filter_by(field="motivation").first()
    assert obs.status == "pending"


def test_apply_conflicts_go_to_pending(db):
    char = _make_char(db, weakness="怕黑")
    _apply_profile_candidate(
        db, char,
        {"conflicts": [{"field": "weakness", "existing": "怕黑", "new_evidence": "新文本显示他夜间独行", "suggestion": "请确认"}]},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert char.weakness == "怕黑"
    obs = db.query(CharacterObservation).filter_by(field="weakness").first()
    assert obs.status == "pending"
    assert obs.metadata_json["change_type"] == "矛盾"


def test_apply_traits_ema_blend(db):
    char = _make_char(db)
    char.core_traits = {"openness": 0.8}
    db.commit()
    _apply_profile_candidate(
        db, char, {"core_traits": {"openness": 0.3, "neuroticism": 0.6}},
        source="AI导入画像", evidence_note="测试", merge_mode=True,
    )
    assert char.core_traits["openness"] == 0.6   # EMA
    assert char.core_traits["neuroticism"] == 0.6  # 缺失直接补


# ─── 别名与合并 ──────────────────────────────────────────────────────────────

def test_find_character_by_alias(db):
    char = _make_char(db, name="张三")
    add_alias(char, "张总")
    db.commit()
    assert find_character_by_name(db, "张三").id == char.id
    assert find_character_by_name(db, "张总").id == char.id
    assert find_character_by_name(db, "李四") is None


def test_add_alias_dedupes_and_skips_own_name(db):
    char = _make_char(db, name="张三")
    assert add_alias(char, "张总") is True
    assert add_alias(char, "张总") is False
    assert add_alias(char, "张三") is False
    assert char.aliases == ["张总"]


def test_merge_characters_full(db):
    target = _make_char(db, name="张三", motivation="")
    source = _make_char(db, name="张总", motivation="掌控全局")
    other = _make_char(db, name="李四")
    db.add_all([
        CharacterEvent(character_id=source.id, title="源角色事件"),
        MemoryItem(character_id=source.id, memory_type="fact", content="记忆甲", confidence=0.7),
        Relationship(source_id=source.id, target_id=other.id, rel_type="rival", strength=0.7, sentiment=-0.5, history=[]),
        Relationship(source_id=target.id, target_id=source.id, rel_type="neutral", strength=0.5, sentiment=0.0, history=[]),
    ])
    db.commit()

    stats = merge_characters(db, target, source)
    db.commit()

    assert db.get(Character, source.id) is None                       # 源角色已删除
    assert "张总" in target.aliases                                    # 名字成为别名
    assert target.motivation == "掌控全局"                             # 空缺互补
    assert db.query(CharacterEvent).first().character_id == target.id  # 事件重指
    assert db.query(MemoryItem).first().character_id == target.id      # 记忆重指
    rels = db.query(Relationship).all()
    assert len(rels) == 1                                              # 自指删除，仅剩 target↔other
    assert {rels[0].source_id, rels[0].target_id} == {target.id, other.id}
    assert stats["events"] == 1 and stats["memories"] == 1


def test_merge_with_self_rejected(db):
    char = _make_char(db, name="张三")
    with pytest.raises(ValueError):
        merge_characters(db, char, char)
