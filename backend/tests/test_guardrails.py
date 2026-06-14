"""OutputGuardrails：JSON 提取、截断修复、嵌套校验"""
import pytest

from app.harness.model_router import OutputGuardrails, GuardrailError

guardrails = OutputGuardrails()


def test_extract_plain_json():
    assert guardrails.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_markdown_fence():
    raw = '```json\n{"reply": "你好", "score": 0.5}\n```'
    assert guardrails.extract_json(raw)["reply"] == "你好"


def test_extract_json_with_leading_text():
    raw = '好的，以下是结果：\n{"value": "测试"}'
    assert guardrails.extract_json(raw) == {"value": "测试"}


def test_repair_truncated_json():
    # 模拟 max_tokens 截断：缺右括号与引号
    raw = '{"items": [{"name": "甲", "score": 3}, {"name": "乙", "sco'
    result = guardrails.extract_json(raw)
    assert isinstance(result, dict)
    assert result["items"][0]["name"] == "甲"


def test_extract_invalid_raises():
    with pytest.raises(GuardrailError):
        guardrails.extract_json("完全不是 JSON 的内容")


def test_validate_chat_analysis_nested_ok():
    output = {
        "reply": "嗯。",
        "inner_monologue": {"first_reaction": "a", "defense": "b", "tendency": "c"},
        "emotions": {
            "intended": {"label": "愧疚", "score": 7},
            "surface": {"label": "平静", "score": 3},
            "deep": {"label": "愤怒", "score": 8},
            "suppressed": {"label": "恐惧", "score": 5},
        },
        "strategy": {"short_term": "x", "long_term": "y", "consistency_note": "z"},
        "tags": {"primary": "p", "secondary": "s", "relation": "r"},
    }
    assert guardrails.validate("chat_analysis", output) is output


def test_validate_chat_analysis_missing_nested_field():
    output = {
        "reply": "嗯。",
        "inner_monologue": {"first_reaction": "a", "defense": "b"},  # 缺 tendency
        "emotions": {"intended": {}, "surface": {}, "deep": {}, "suppressed": {}},
        "strategy": {"short_term": "", "long_term": "", "consistency_note": ""},
        "tags": {"primary": "", "secondary": "", "relation": ""},
    }
    with pytest.raises(GuardrailError):
        guardrails.validate("chat_analysis", output)


def test_validate_missing_top_field():
    with pytest.raises(GuardrailError):
        guardrails.validate("chat_analysis", {"reply": "只有一个字段"})
