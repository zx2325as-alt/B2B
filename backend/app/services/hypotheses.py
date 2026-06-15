"""
特质假设引擎：假设 → 验证 → 修正 → 沉淀 的循环
- 系统对每个人物维护一组带置信度的猜想（TraitHypothesis）
- 每次有新证据（导入 / 归档 / 会话累积）跑一轮：支持则升置信、反驳则降、新发现立新假设
- 置信度 ≥0.8 自动转正：写入扩展档案对应维度（或沉淀为诊断记忆）
- 置信度 ≤0.2 标记 rejected
这是"系统在持续琢磨这个人"的核心机制。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models.sql_models import Character, MemoryItem, TraitHypothesis
from .profiles import EXTENDED_DIMENSIONS, merge_extended_profile

logger = logging.getLogger("import")

MAX_ACTIVE_HYPOTHESES = 12
CONFIRM_THRESHOLD = 0.8
REJECT_THRESHOLD = 0.2

# 假设维度 → 扩展档案维度的转正映射（列表型维度直接写入）
_PROMOTABLE_DIMENSIONS = {"values", "desires", "fears", "interpersonal_patterns", "contradictions"}


def _clamp(value: Any, default: float = 0.4) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _promote_to_profile(db: Session, char: Character, hypothesis: TraitHypothesis) -> None:
    """假设转正：写入扩展档案对应维度；非档案维度沉淀为诊断记忆"""
    dimension = (hypothesis.dimension or "").strip()
    if dimension in _PROMOTABLE_DIMENSIONS:
        # 直接写规范形态：内容 + 假设的置信 + 支撑证据 + 时间（merge 会保留这些）
        entry: Any = {
            "content": hypothesis.hypothesis,
            "confidence": round(float(hypothesis.confidence or 0.8), 2),
            "evidence_ids": list(hypothesis.supporting_evidence_ids or []),
        }
        merged, added = merge_extended_profile(char.profile_json, {dimension: [entry]})
        if added:
            char.profile_json = merged
            char.version += 1
            char.updated_at = datetime.utcnow()
            db.add(char)
    # 不论是否进档案，都沉淀一条高置信记忆，保证可检索
    existing = db.query(MemoryItem).filter(
        MemoryItem.character_id == char.id,
        MemoryItem.content == hypothesis.hypothesis,
        MemoryItem.status == "active",
    ).first()
    if not existing:
        from ..harness.embeddings import embed_text
        db.add(MemoryItem(
            character_id=char.id,
            memory_type="diagnosis",
            content=hypothesis.hypothesis,
            embedding=embed_text((hypothesis.hypothesis or "")[:2000]),
            confidence=hypothesis.confidence,
            evidence_ids=list(hypothesis.supporting_evidence_ids or []),
            source="假设转正",
            status="active",
        ))
    db.flush()


async def run_hypothesis_round(
    db: Session,
    char: Character,
    new_evidence_texts: list[str],
    evidence_ids: list[int] | None = None,
) -> dict[str, int]:
    """对单个角色跑一轮假设演化。失败时静默返回（不阻塞调用方主流程）。"""
    from ..harness.orchestrator import orchestrator  # 延迟导入避免循环

    stats = {"supported": 0, "contradicted": 0, "new": 0, "confirmed": 0, "rejected": 0}
    evidence_texts = [t for t in (new_evidence_texts or []) if (t or "").strip()][:30]
    if not evidence_texts:
        return stats

    active = db.query(TraitHypothesis).filter(
        TraitHypothesis.character_id == char.id,
        TraitHypothesis.status == "active",
    ).order_by(TraitHypothesis.updated_at.desc()).limit(MAX_ACTIVE_HYPOTHESES).all()

    profile_block = json.dumps(
        {
            "name": char.name,
            "role": char.role or "",
            "personality_tags": char.personality_tags or [],
            "motivation": char.motivation or "",
            "weakness": char.weakness or "",
            "extended": char.profile_json or {},
        },
        ensure_ascii=False,
    )
    hypo_block = "\n".join(
        f"{h.id}. [{h.dimension}] {h.hypothesis}（当前置信度 {h.confidence:.2f}）"
        for h in active
    )
    evidence_block = "\n".join(f"- {t[:160]}" for t in evidence_texts)

    try:
        result = await orchestrator.update_trait_hypotheses(profile_block, hypo_block, evidence_block)
    except Exception as exc:
        logger.warning("假设轮失败 char=%s error=%s", char.name, exc)
        return stats
    if not isinstance(result, dict):
        return stats

    by_id = {h.id: h for h in active}
    new_evidence_ids = list(evidence_ids or [])

    for item in result.get("updates") or []:
        if not isinstance(item, dict):
            continue
        try:
            hypo = by_id.get(int(item.get("id")))
        except (TypeError, ValueError):
            hypo = None
        if not hypo:
            continue
        action = (item.get("action") or "").strip()
        hypo.confidence = _clamp(item.get("confidence"), hypo.confidence)
        hypo.updated_at = datetime.utcnow()
        if action == "support":
            stats["supported"] += 1
            hypo.supporting_evidence_ids = list(dict.fromkeys(
                list(hypo.supporting_evidence_ids or []) + new_evidence_ids))[:30]
        elif action == "contradict":
            stats["contradicted"] += 1
            hypo.contradicting_evidence_ids = list(dict.fromkeys(
                list(hypo.contradicting_evidence_ids or []) + new_evidence_ids))[:30]
        if hypo.confidence >= CONFIRM_THRESHOLD:
            hypo.status = "confirmed"
            stats["confirmed"] += 1
            _promote_to_profile(db, char, hypo)
        elif hypo.confidence <= REJECT_THRESHOLD:
            hypo.status = "rejected"
            stats["rejected"] += 1

    active_count = db.query(TraitHypothesis).filter(
        TraitHypothesis.character_id == char.id,
        TraitHypothesis.status == "active",
    ).count()
    for item in result.get("new_hypotheses") or []:
        if not isinstance(item, dict):
            continue
        if active_count >= MAX_ACTIVE_HYPOTHESES:
            break
        hypothesis_text = (item.get("hypothesis") or "").strip()
        if not hypothesis_text or len(hypothesis_text) < 6:
            continue
        # 已有相同假设不重复创建
        duplicated = db.query(TraitHypothesis).filter(
            TraitHypothesis.character_id == char.id,
            TraitHypothesis.hypothesis == hypothesis_text,
        ).first()
        if duplicated:
            continue
        dimension = (item.get("dimension") or "").strip()
        if dimension not in EXTENDED_DIMENSIONS and dimension != "心理特征":
            dimension = "心理特征"
        db.add(TraitHypothesis(
            character_id=char.id,
            hypothesis=hypothesis_text,
            dimension=dimension,
            confidence=_clamp(item.get("confidence"), 0.4),
            supporting_evidence_ids=new_evidence_ids[:10],
        ))
        active_count += 1
        stats["new"] += 1

    db.commit()
    if any(stats.values()):
        logger.info("假设轮完成 char=%s stats=%s", char.name, stats)
    return stats
