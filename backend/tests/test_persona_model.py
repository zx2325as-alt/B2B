"""人物建模新链路：扩展档案合并、事实清洗、渲染"""
from app.services.profiles import merge_extended_profile, render_extended_profile
from app.harness.import_engine import sanitize_persona_facts


def test_merge_extended_list_dedupe_and_grow():
    old = {"values": ["家族荣誉高于一切"]}
    new = {
        "values": ["家族荣誉高于一切", "强者不应示弱"],
        "fears": [{"content": "害怕被至亲背叛"}],
    }
    merged, added = merge_extended_profile(old, new)
    assert added == 2
    assert merged["values"] == ["家族荣誉高于一切", "强者不应示弱"]
    assert merged["fears"][0]["content"] == "害怕被至亲背叛"


def test_merge_extended_dict_fill_and_extend():
    old = {"speech_fingerprint": {"catchphrases": ["来来来"], "sentence_style": ""}}
    new = {"speech_fingerprint": {"catchphrases": ["来来来", "莫谈"], "sentence_style": "短句带停顿"}}
    merged, added = merge_extended_profile(old, new)
    assert added >= 2
    assert set(merged["speech_fingerprint"]["catchphrases"]) == {"来来来", "莫谈"}
    assert merged["speech_fingerprint"]["sentence_style"] == "短句带停顿"


def test_merge_extended_never_removes():
    old = {"contradictions": [{"side_a": "轻视马超", "side_b": "频频提起", "interpretation": "在意"}]}
    merged, added = merge_extended_profile(old, {"contradictions": []})
    assert merged["contradictions"] == old["contradictions"]
    assert added == 0


def test_merge_extended_caps_items():
    new = {"values": [f"价值观{i}" for i in range(20)]}
    merged, _ = merge_extended_profile({}, new)
    assert len(merged["values"]) == 10


def test_render_extended_profile():
    text = render_extended_profile({
        "fears": [{"content": "害怕被背叛"}],
        "speech_fingerprint": {"catchphrases": ["来来来"]},
    })
    assert "恐惧" in text and "害怕被背叛" in text
    assert "语言指纹" in text


def test_render_extended_profile_empty():
    assert render_extended_profile({}) == ""
    assert render_extended_profile(None) == ""


def test_sanitize_persona_facts_subject_mapping_and_dedupe():
    parsed = {
        "subject": {"name": "张三", "confidence": 0.9},
        "persona_facts": [
            {"subject": "我", "category": "恐惧", "content": "从小害怕黑暗", "quote": "我从小怕黑", "confidence": 0.8},
            {"subject": "张三", "category": "恐惧", "content": "从小害怕黑暗", "quote": "重复", "confidence": 0.7},  # 重复
            {"subject": "他说", "category": "习惯", "content": "无效主体应被丢弃"},
            {"subject": "李四", "category": "不存在的类目", "content": "类目应兜底为心理特征"},
        ],
    }
    facts = sanitize_persona_facts(parsed)
    assert len(facts) == 2
    assert facts[0]["subject"] == "张三"          # "我" → 主体名
    assert facts[1]["category"] == "心理特征"      # 未知类目兜底


def test_sanitize_persona_facts_first_person_without_subject():
    parsed = {
        "subject": {},
        "persona_facts": [{"subject": "我", "category": "习惯", "content": "每天五点起床跑步"}],
    }
    facts = sanitize_persona_facts(parsed)
    assert facts[0]["subject"] == "主角"


def test_prompt_registry_render_with_name_param():
    """回归：模板参数含 'name' 键不得与 render 位置形参冲突
    （曾导致 import_profile_gen / character_profile_gen 全部失败）"""
    from app.harness.prompt_templates import prompt_registry
    out = prompt_registry.render('character_profile_gen', name='张三', role='CEO', background='无')
    assert '张三' in out['user']
    out2 = prompt_registry.render(
        'import_profile_gen', name='李四', current_profile='{}',
        dialogue_samples='a', event_samples='b', relationship_samples='c', rule_hints='d',
    )
    assert '李四' in out2['user']


def test_event_out_tolerates_null_event_date():
    """回归：弧光转折事件无具体日期(event_date=None)时 EventOut 不得校验失败
    （曾导致整个 /characters/{id}/events 接口 500，时间线页打不开）"""
    from app.schemas import EventOut
    from datetime import datetime
    class _E:
        id = 1; character_id = 1; title = "心理转折"; description = "x"
        event_date = None; emotion_label = None; importance = 5
        psychological_impact = "y"; arc_marker = True; created_at = datetime.utcnow()
    out = EventOut.model_validate(_E())
    assert out.event_date in (None, "")
    assert out.arc_marker is True


def test_multi_perspective_normalize_and_save_shape():
    """多视角分析 normalize：每个 viewer 产出独立的标准分析结构"""
    from app.harness.analysis_schema import normalize_chat_analysis
    raw_persp = {
        "viewer": "李经理",
        "inner_monologue": {"first_reaction": "他疯了", "defense": "沉默", "tendency": "备数据"},
        "emotions": {"intended": {"label": "压迫", "score": 8}, "surface": {"label": "平静", "score": 2},
                     "deep": {"label": "焦虑", "score": 9}, "suppressed": {"label": "愤怒", "score": 6}},
        "strategy": {"short_term": "沉默", "long_term": "反驳", "consistency_note": "符合谨慎人设"},
        "tags": {"primary": "风险", "secondary": "防御", "relation": "下属戒备"},
    }
    out = normalize_chat_analysis(raw_persp)
    out["viewer"] = raw_persp["viewer"]
    assert out["viewer"] == "李经理"
    assert "深层:焦虑(9)" in out["emotion_label"]
    assert "短期策略：沉默" in out["subtext"]
    assert out["emotion_score"] == 0.9
