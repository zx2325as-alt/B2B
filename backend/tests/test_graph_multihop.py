"""B：Neo4j 多跳推理端点。打桩 graph_store（不依赖 Neo4j 在线），
验证 5 个场景的端点接线 + 立场传染的 predicted_stance 推断 + 不可用时优雅 503。"""
import app.api.characters as chars_api
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
_BASE = "/api/v1/characters/graph/multi-hop"


def _patch_available(monkeypatch):
    monkeypatch.setattr(chars_api.graph_store, "health", lambda: {"available": True})


def test_hubs(monkeypatch):
    _patch_available(monkeypatch)
    monkeypatch.setattr(chars_api.graph_store, "central_hubs",
                        lambda limit=10: [{"person": {"id": 1, "name": "林然"}, "degree": 29, "avg_sentiment": 0.37}])
    r = client.get(f"{_BASE}/hubs")
    assert r.status_code == 200
    assert r.json()["hubs"][0]["degree"] == 29


def test_path(monkeypatch):
    _patch_available(monkeypatch)
    monkeypatch.setattr(chars_api.graph_store, "shortest_path",
                        lambda a, b, max_hops=5: {"nodes": [{"id": a, "name": "A"}, {"id": b, "name": "B"}], "hops": 1})
    r = client.get(f"{_BASE}/path", params={"a_id": 1, "b_id": 2})
    assert r.status_code == 200
    assert r.json()["path"]["hops"] == 1


def test_intermediaries(monkeypatch):
    _patch_available(monkeypatch)
    monkeypatch.setattr(chars_api.graph_store, "find_intermediaries",
                        lambda me, target, limit=10: [{"person": {"id": 5, "name": "牵线人"}, "combined": 1.4}])
    r = client.get(f"{_BASE}/intermediaries", params={"me_id": 3, "target_id": 2})
    assert r.status_code == 200
    assert r.json()["intermediaries"][0]["person"]["name"] == "牵线人"


def test_sentiment_propagation_predicts_stance(monkeypatch):
    _patch_available(monkeypatch)
    # 两段同号(正×正)→倾向友好；异号(正×负)→倾向戒备；接近0→中性
    monkeypatch.setattr(chars_api.graph_store, "propagate_sentiment", lambda me, limit=12: [
        {"person": {"id": 9, "name": "友友"}, "via": {"id": 1, "name": "中"}, "s1": 0.6, "s2": 0.7, "t1": "friend", "t2": "friend"},
        {"person": {"id": 10, "name": "戒戒"}, "via": {"id": 1, "name": "中"}, "s1": 0.6, "s2": -0.7, "t1": "friend", "t2": "rival"},
        {"person": {"id": 11, "name": "中中"}, "via": {"id": 1, "name": "中"}, "s1": 0.0, "s2": 0.5, "t1": "neutral", "t2": "friend"},
    ])
    r = client.get(f"{_BASE}/sentiment-propagation", params={"me_id": 3})
    assert r.status_code == 200
    links = {l["person"]["name"]: l["predicted_stance"] for l in r.json()["links"]}
    assert links["友友"] == "倾向友好"
    assert links["戒戒"] == "倾向戒备"
    assert links["中中"] == "中性/不确定"


def test_evidence_chain(monkeypatch):
    _patch_available(monkeypatch)
    monkeypatch.setattr(chars_api.graph_store, "evidence_chain",
                        lambda pid, limit=12: [{"memory": {"id": 1, "content": "他很守时", "confidence": 0.9},
                                                "evidence": [{"id": 7, "quote": "从不迟到"}]}])
    r = client.get(f"{_BASE}/evidence-chain", params={"person_id": 1})
    assert r.status_code == 200
    assert r.json()["chains"][0]["evidence"][0]["quote"] == "从不迟到"


def test_graceful_503_when_graph_down(monkeypatch):
    monkeypatch.setattr(chars_api.graph_store, "health", lambda: {"available": False, "reason": "down"})
    r = client.get(f"{_BASE}/hubs")
    assert r.status_code == 503  # Neo4j 不可用时优雅降级，不 500
