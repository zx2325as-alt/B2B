"""analysis_schema：结构化协议 normalize 与 legacy 兼容读取"""
from app.harness.analysis_schema import (
    normalize_chat_analysis,
    extract_emotion_struct,
    extract_strategy_struct,
    parse_legacy_emotion_label,
)


def _sample_result():
    return {
        "reply": "  随便你怎么想。 ",
        "inner_monologue": {"first_reaction": "他又来了", "defense": "假装无所谓", "tendency": "转移话题"},
        "emotions": {
            "intended": {"label": "愧疚", "score": 7},
            "surface": {"label": "平静", "score": 3},
            "deep": {"label": "愤怒", "score": 8.6},
            "suppressed": {"label": "恐惧", "score": 15},  # 越界，应被裁剪到 10
        },
        "strategy": {"short_term": "压制对方", "long_term": "维持控制", "consistency_note": "与既往一致"},
        "tags": {"primary": "权力争夺", "secondary": "防御", "relation": "信任下降"},
    }


def test_normalize_derives_legacy_fields():
    result = normalize_chat_analysis(_sample_result())
    assert result["reply"] == "随便你怎么想。"
    assert "试图激发:愧疚(7)" in result["emotion_label"]
    assert "深层:愤怒(9)" in result["emotion_label"]  # 8.6 四舍五入
    assert "压抑:恐惧(10)" in result["emotion_label"]  # 越界裁剪
    assert result["emotion_score"] == 0.9
    assert "短期策略：压制对方" in result["subtext"]
    assert "长期策略：维持控制" in result["subtext"]
    assert "主:权力争夺" in result["psychological_tag"]
    assert "第一反应：他又来了" in result["inner_monologue_text"]


def test_normalize_tolerates_missing_pieces():
    result = normalize_chat_analysis({"reply": "嗯", "emotions": {}, "strategy": None, "tags": []})
    assert result["reply"] == "嗯"
    assert result["emotions"]["deep"] == {"label": "", "score": 0}
    assert result["emotion_score"] == 0.0


def test_extract_emotion_prefers_analysis_json():
    analysis_json = {"emotions": {"deep": {"label": "委屈", "score": 6}}}
    struct = extract_emotion_struct(analysis_json, "深层:愤怒(9)")
    assert struct["deep"]["label"] == "委屈"
    assert struct["deep"]["score"] == 6


def test_extract_emotion_falls_back_to_legacy_label():
    struct = extract_emotion_struct(None, "试图激发:愧疚(7)｜表层:平静(3)｜深层:愤怒(9)｜压抑:恐惧(5)")
    assert struct["intended"] == {"label": "愧疚", "score": 7}
    assert struct["deep"] == {"label": "愤怒", "score": 9}


def test_extract_strategy_falls_back_to_legacy_text():
    struct = extract_strategy_struct(None, "短期策略：试探\n长期策略：拉拢\n一致性说明：正常")
    assert struct["short_term"] == "试探"
    assert struct["long_term"] == "拉拢"
    assert struct["consistency_note"] == "正常"


def test_legacy_label_parse_handles_garbage():
    struct = parse_legacy_emotion_label("完全不符合格式的字符串")
    assert struct["deep"] == {"label": "", "score": 0}
