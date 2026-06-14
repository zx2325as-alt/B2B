"""services 层：档案合并策略、完整度评分、关系无向化"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.sql_models import Base, Character, Relationship
from app.services.profiles import blend_traits, merge_background, merge_tags, profile_completeness
from app.services.relationships import find_pair_relationship, merge_duplicate_relationships


def test_merge_background_accumulates_new_sentences():
    old = "出身贸易世家。三十岁接管生意。"
    new = "三十岁接管生意。经历背叛后极度谨慎。"
    merged = merge_background(old, new)
    assert "贸易世家" in merged
    assert "极度谨慎" in merged
    assert merged.count("三十岁接管生意") == 1  # 重复句子不追加


def test_merge_background_empty_old_takes_new():
    assert merge_background("", "新背景内容。") == "新背景内容。"
    assert merge_background("旧背景。", "") == "旧背景。"


def test_merge_background_respects_cap():
    old = "句子。" * 50
    merged = merge_background(old, "全新的补充事实出现了。", cap=320)
    assert len(merged) <= 320


# ─── profiles ────────────────────────────────────────────────────────────────

def test_merge_tags_union_keeps_order_and_dedupes():
    assert merge_tags(["强势", "多疑"], ["多疑", "护短", " 强势 "]) == ["强势", "多疑", "护短"]


def test_merge_tags_cap():
    tags = [f"标签{i}" for i in range(20)]
    assert len(merge_tags(tags, [])) == 12


def test_blend_traits_ema_and_fill():
    old = {"openness": 0.8}
    new = {"openness": 0.3, "neuroticism": 0.6}
    blended = blend_traits(old, new, new_weight=0.4)
    assert blended["openness"] == 0.6   # 0.8*0.6 + 0.3*0.4
    assert blended["neuroticism"] == 0.6  # 旧档案缺失，直接采用
    assert "extraversion" not in blended  # 双方都没有的维度不臆造


def test_blend_traits_clamps_range():
    blended = blend_traits({}, {"openness": 1.7, "agreeableness": -0.2})
    assert blended["openness"] == 1.0
    assert blended["agreeableness"] == 0.0


class _FakeChar:
    def __init__(self, **kwargs):
        self.role = kwargs.get("role", "")
        self.background = kwargs.get("background", "")
        self.personality_tags = kwargs.get("personality_tags", [])
        self.core_traits = kwargs.get("core_traits", {})
        self.motivation = kwargs.get("motivation", "")
        self.weakness = kwargs.get("weakness", "")
        self.speaking_style = kwargs.get("speaking_style", "")


def test_completeness_empty_profile():
    result = profile_completeness(_FakeChar())
    assert result["score"] == 0
    assert "核心动机" in result["missing"]


def test_completeness_full_profile():
    char = _FakeChar(
        role="强势的谈判者",
        background="出身贸易世家，三十岁前接管家族生意，经历过一次重大背叛后变得极度谨慎，对外人始终保持距离。",
        personality_tags=["强势", "多疑", "护短"],
        core_traits={"openness": .5, "conscientiousness": .5, "extraversion": .5, "agreeableness": .5, "neuroticism": .5},
        motivation="夺回家族企业的实际控制权",
        weakness="无法拒绝妹妹的任何请求",
        speaking_style="短句、反问、施压式停顿",
    )
    result = profile_completeness(char, behavior_pattern_count=2, relationship_count=1, event_count=3)
    assert result["score"] == 100
    assert result["missing"] == []
    assert result["thin"] == []


def test_completeness_thin_content_gets_half_credit():
    # 内容偏短的字段只得一半权重，并出现在 thin 列表
    char = _FakeChar(motivation="m", personality_tags=["a", "b", "c"])
    result = profile_completeness(char)
    assert result["score"] == 18  # motivation 12*0.5 + tags 12
    assert "核心动机" in result["thin"]
    assert "大五人格" in result["missing"]


# ─── relationships ───────────────────────────────────────────────────────────

def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_chars(db, count=2):
    chars = [Character(name=f"角色{i}") for i in range(count)]
    db.add_all(chars)
    db.commit()
    return chars


def test_find_pair_relationship_direction_agnostic():
    db = _make_session()
    a, b = _seed_chars(db)
    rel = Relationship(source_id=a.id, target_id=b.id, rel_type="friend", strength=0.6, sentiment=0.2, history=[])
    db.add(rel)
    db.commit()
    assert find_pair_relationship(db, a.id, b.id).id == rel.id
    assert find_pair_relationship(db, b.id, a.id).id == rel.id  # 反向也命中同一条
    assert find_pair_relationship(db, a.id, a.id) is None


def test_merge_duplicate_relationships():
    db = _make_session()
    a, b = _seed_chars(db)
    forward = Relationship(
        source_id=a.id, target_id=b.id, rel_type="neutral",
        strength=0.4, sentiment=0.2, description="短",
        history=[{"date": "2026-01-01", "strength": 0.4, "sentiment": 0.2}],
    )
    backward = Relationship(
        source_id=b.id, target_id=a.id, rel_type="rival",
        strength=0.8, sentiment=-0.4, description="更长的关系描述",
        history=[{"date": "2026-02-01", "strength": 0.8, "sentiment": -0.4}],
    )
    db.add_all([forward, backward])
    db.commit()

    merged = merge_duplicate_relationships(db)
    assert merged == 1
    remaining = db.query(Relationship).all()
    assert len(remaining) == 1
    rel = remaining[0]
    assert rel.strength == 0.6                      # 平均
    assert rel.sentiment == -0.1
    assert rel.rel_type == "rival"                  # 泛化类型被具体类型替换
    assert rel.description == "更长的关系描述"
    assert len(rel.history) == 2                    # history 合并按时间排序
    assert rel.history[0]["date"] == "2026-01-01"


def test_merge_duplicate_relationships_idempotent():
    db = _make_session()
    a, b = _seed_chars(db)
    db.add(Relationship(source_id=a.id, target_id=b.id, strength=0.5, sentiment=0.0, history=[]))
    db.commit()
    assert merge_duplicate_relationships(db) == 0
    assert merge_duplicate_relationships(db) == 0
