"""
可选向量检索基建（默认关闭）
- config.yaml embedding 段配置任意 OpenAI 兼容 embedding 服务后启用
- 记忆写入时计算向量、检索时余弦相似度参与打分
- 未启用/调用失败时全部静默回退到字面检索，零影响
"""
from __future__ import annotations

import logging
import math

import openai

from .config_loader import get_config

logger = logging.getLogger(__name__)
_client: openai.OpenAI | None = None
_client_signature: str = ""


def _embedding_config() -> dict:
    return get_config().get("embedding", {}) or {}


def embedding_enabled() -> bool:
    cfg = _embedding_config()
    return bool(cfg.get("enabled") and cfg.get("base_url") and cfg.get("api_key") and cfg.get("model"))


def _get_client() -> openai.OpenAI | None:
    global _client, _client_signature
    cfg = _embedding_config()
    signature = f"{cfg.get('base_url')}|{cfg.get('api_key')}"
    if _client is None or signature != _client_signature:
        try:
            _client = openai.OpenAI(
                base_url=cfg.get("base_url"),
                api_key=cfg.get("api_key"),
                timeout=15.0,
            )
            _client_signature = signature
        except Exception as exc:
            logger.warning("embedding 客户端初始化失败: %s", exc)
            return None
    return _client


def embed_text(text: str) -> list[float] | None:
    """计算单条文本向量；未启用或失败返回 None（调用方静默回退）"""
    if not embedding_enabled():
        return None
    text = (text or "").strip()
    if not text:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        response = client.embeddings.create(
            model=_embedding_config().get("model"),
            input=text[:1000],
        )
        return list(response.data[0].embedding)
    except Exception as exc:
        logger.warning("embedding 计算失败: %s", exc)
        return None


def cosine_similarity(vec_a: list[float] | None, vec_b: list[float] | None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
