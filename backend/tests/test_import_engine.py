"""import_engine：实体清洗、对话解析、chunk 合并"""
from app.harness.import_engine import (
    _clean_entity_name,
    _extract_speaker_receiver,
    chunk_text,
    detect_import_type,
    parse_dialogue_lines,
    sanitize_import_entities,
    _merge_chunk_parse_results,
)


def test_clean_entity_name_strips_reporting_verbs():
    assert _clean_entity_name("张三说") == "张三"
    assert _clean_entity_name("李四回答道") == "李四"


def test_clean_entity_name_rejects_pronouns_and_garbage():
    assert _clean_entity_name("他说") == ""
    assert _clean_entity_name("他们回答道") == ""
    assert _clean_entity_name("旁白") == ""
    assert _clean_entity_name("12345") == ""


def test_extract_speaker_receiver_from_compound():
    speaker, receiver = _extract_speaker_receiver("张三对李四说")
    assert speaker == "张三"
    assert receiver == "李四"


def test_detect_import_type():
    assert detect_import_type("a.json", "{}") == "structured"
    assert detect_import_type("a.txt", "张三：你好\n李四：你也好") == "dialogue"
    # 含"X说/X问"句式的第三人称叙事 → narrative
    assert detect_import_type("a.txt", "张三说他不想去。李四问为什么。张三回答天太冷。") == "narrative"
    # 第一人称密集的自述 → 资料型
    first_person = "我出生在北方。我从小怕黑。我后来去了南方上学。我不喜欢应酬。我最在意家人。我每天跑步。我讨厌迟到。我习惯早起。"
    assert detect_import_type("a.txt", first_person) == "profile_document"
    # 没有任何说话句式的纯陈述（人物介绍/简历）→ 资料型
    assert detect_import_type("a.txt", "张三，男，38岁，从事外贸行业，常驻上海。") == "profile_document"


def test_parse_dialogue_lines_infers_receiver():
    parsed = parse_dialogue_lines("张三：你来了。\n李四：嗯，路上堵。\n张三：坐吧。")
    units = parsed["interaction_units"]
    assert len(units) == 3
    assert units[1]["speaker"] == "李四"
    assert units[1]["receiver"] == "张三"
    assert {c["name"] for c in parsed["characters"]} == {"张三", "李四"}


def test_sanitize_dedupes_units_and_builds_characters():
    parsed = {
        "characters": [{"name": "张三说", "personality_tags": [], "confidence": 0.5}],
        "interaction_units": [
            {"speaker": "张三", "receiver": "李四", "content": "你来了。", "receiver_confidence": 0.7},
            {"speaker": "张三", "receiver": "李四", "content": "你来了。", "receiver_confidence": 0.7},  # 重复
        ],
        "events": [],
        "relationships": [{"source": "张三", "target": "张三"}],  # 自指关系应被丢弃
        "plot_summary": {},
    }
    result = sanitize_import_entities(parsed, "dialogue")
    assert len(result["interaction_units"]) == 1
    assert result["relationships"] == []
    assert any(c["name"] == "张三" for c in result["characters"])


def test_chunk_text_overlap_and_coverage():
    text = "。".join(f"第{i}句" for i in range(400))
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert "".join(chunks).find("第399句") != -1  # 末尾不丢


def test_merge_chunk_parse_results():
    chunk_a = {
        "characters": [{"name": "张三", "personality_tags": ["强势"]}],
        "interaction_units": [{"speaker": "张三", "receiver": "李四", "content": "你来了。"}],
        "events": [{"actor": "张三", "summary": "见面"}],
        "relationships": [{"source": "张三", "target": "李四", "rel_type": "friend"}],
        "plot_summary": {"main_conflict": "信任危机", "turning_points": ["见面"]},
    }
    chunk_b = {
        "characters": [{"name": "张三", "personality_tags": ["多疑"]}, {"name": "王五"}],
        "interaction_units": [
            {"speaker": "张三", "receiver": "李四", "content": "你来了。"},  # 跨 chunk 重复
            {"speaker": "王五", "receiver": "张三", "content": "别吵了。"},
        ],
        "events": [{"actor": "王五", "summary": "劝架"}],
        "relationships": [{"source": "张三", "target": "李四", "rel_type": "rival"}],  # 重复对，应保留首个
        "plot_summary": {"turning_points": ["劝架"]},
    }
    merged = _merge_chunk_parse_results([chunk_a, chunk_b])
    assert {c["name"] for c in merged["characters"]} == {"张三", "王五"}
    assert len(merged["interaction_units"]) == 2
    assert len(merged["relationships"]) == 1
    assert merged["plot_summary"]["main_conflict"] == "信任危机"
    assert merged["plot_summary"]["turning_points"] == ["见面", "劝架"]
    # 张三的标签来自两个 chunk 合并
    zhang = next(c for c in merged["characters"] if c["name"] == "张三")
    assert set(zhang["personality_tags"]) >= {"强势", "多疑"}
