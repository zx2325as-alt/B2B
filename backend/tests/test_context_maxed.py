"""Q3 上下文拉满：RAG 召回上限提高 + 多跳关系（牵线人/关系链）注入证据包渲染。
多跳在图谱不可用时必须安全返回空、不崩。"""
from app.harness.retrieval_engine import _MEMORY_TOP_N, _multihop_facts, render_evidence_pack


class _C:
    def __init__(self, i):
        self.id = i


def test_multihop_safe_when_graph_unavailable():
    assert _multihop_facts(None, _C(2)) == {}            # 缺人安全
    assert isinstance(_multihop_facts(_C(1), _C(2)), dict)  # 图谱down也不崩


def test_render_includes_multihop_section():
    pack = {"multihop": {
        "intermediaries": [{"person": {"name": "王姐", "id": 3}, "my_rel": "同事",
                            "my_sentiment": 0.6, "target_rel": "闺蜜", "target_sentiment": 0.8}],
        "path": {"nodes": [{"name": "我", "id": 1}, {"name": "王姐", "id": 3}, {"name": "对方", "id": 2}], "hops": 2},
    }}
    out = render_evidence_pack(pack)
    assert "牵线人" in out and "王姐" in out
    assert "关系链" in out and "我 → 王姐 → 对方" in out


def test_retrieval_caps_raised():
    assert _MEMORY_TOP_N >= 20   # 长期记忆召回上限已拉高
