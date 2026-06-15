import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character, CharacterEvent, Relationship, CharacterObservation,
    Conversation, Message, ImportFile, InteractionUnit,
    EvidenceSpan, MemoryItem, PersonalitySnapshot, AgentRun, RetrievalTrace, StructuredDiagnosis,
)
from ..schemas import (
    CharacterCreate, CharacterUpdate, CharacterOut, CharacterMergeRequest,
    EventCreate, EventOut,
    RelationshipCreate, RelationshipUpdate, RelationshipOut,
    ObservationReview, ObservationOut, ImportCommitRequest, BehaviorPatternPayload,
    MessageOut, EvidenceSpanOut, MemoryItemOut, PersonalitySnapshotOut, StructuredDiagnosisOut,
    CharacterReviewRequest, CharacterReviewOut,
)
from ..harness.orchestrator import orchestrator
from ..harness.import_engine import extract_text_from_file, build_import_preview, chunk_text, semantic_chunk_text, detect_import_type, classify_behavior_pattern_category
from ..harness.graph_store import graph_store
from ..services.profiles import (
    EXTENDED_DIMENSIONS,
    PROFILE_TEXT_FIELDS,
    blend_traits,
    fact_confidence,
    fact_content,
    merge_background,
    merge_extended_profile,
    merge_tags,
    profile_completeness,
    render_extended_profile,
)
from ..services.relationships import find_pair_relationship
from ..services.identity import add_alias, find_character_by_name, merge_characters
from ..services.hypotheses import run_hypothesis_round
from ..models.sql_models import TraitHypothesis
from ..schemas import TraitHypothesisOut
from .deps import get_db, SessionLocal

router = APIRouter(prefix="/characters", tags=["characters"])
import_logger = logging.getLogger("import")

BIG_FIVE_KEYS = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
PROFILE_MODULES = [
    "基础信息",
    "人格模型",
    "行为模式",
    "核心动机",
    "核心弱点",
    "说话风格",
    "关系网络",
    "事件时间线",
]


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


GENERIC_IMPORT_MEMORY_VALUES = {
    "陈述事实", "补充说明", "回答", "询问", "提问", "直接陈述", "直接回答",
    "解释", "中性", "对话", "发言", "叙述", "未知", "无",
}


def _unit_analysis_mode(unit: dict[str, Any]) -> str:
    return (unit.get("analysis_mode") or "dialogue").strip() or "dialogue"


def _should_run_import_analysis(unit: dict[str, Any]) -> bool:
    if _unit_analysis_mode(unit) != "dialogue":
        return False
    speaker = (unit.get("speaker") or "").strip()
    receiver = (unit.get("receiver") or "").strip()
    return bool(speaker and receiver and speaker != receiver)


def _is_useful_import_memory(value: str) -> bool:
    value = (value or "").strip()
    if not value or value in GENERIC_IMPORT_MEMORY_VALUES:
        return False
    return len(value) >= 3


def _build_import_fact_memory(unit: dict[str, Any]) -> str:
    speaker = (unit.get("speaker") or "").strip()
    content = (unit.get("content") or "").strip().strip("“”\"")
    if not speaker or not content:
        return ""
    return f"{speaker}相关证据：{content[:180]}"


def _resolve_mapping(role_mappings: list, original_name: str) -> dict:
    for mapping in role_mappings:
        if mapping.original_name == original_name:
            return {
                "name": mapping.resolved_name.strip() or original_name,
                "original_name": original_name,
                "action": mapping.action,
            }
    return {"name": original_name, "original_name": original_name, "action": "create"}


def _ensure_character_from_mapping(db: Session, mapping: dict, parsed_character: dict) -> tuple[Character, bool]:
    """
    创建/链接角色（不做 AI 画像）。返回 (角色, 是否新建)。
    命中顺序：本名 → 别名；用户把"张总"映射到"张三"时自动把"张总"记为别名，
    下次导入同一称呼直接归并到同一角色。
    """
    resolved_name = mapping["name"]
    original_name = (mapping.get("original_name") or "").strip()
    existing = find_character_by_name(db, resolved_name)
    if existing:
        # 原始称呼与角色本名不同 → 记为别名，沉淀同一性知识
        if original_name and original_name != existing.name and add_alias(existing, original_name):
            db.flush()
        return existing, False

    char = Character(
        name=resolved_name,
        aliases=[original_name] if original_name and original_name != resolved_name else [],
        role=parsed_character.get("role", "") or "",
        background=parsed_character.get("background", "") or "",
        avatar_color="#00d4ff",
        personality_tags=parsed_character.get("personality_tags", []) or [],
        core_traits={},
        weakness="",
        motivation="",
        speaking_style="",
    )
    db.add(char)
    db.flush()
    db.refresh(char)
    graph_store.sync_character(char)
    return char, True


def _collect_character_evidence(preview: dict[str, Any], char_name: str, max_lines: int = 14) -> tuple[list[str], list[str], list[str], list[str]]:
    """从导入预览中收集某角色的真实证据：本人台词、别人对其说的话、事件、关系、规则推断提示"""
    lines: list[str] = []
    received: list[str] = []
    for unit in preview.get("interaction_units") or []:
        speaker = (unit.get("speaker") or "").strip()
        receiver = (unit.get("receiver") or "").strip()
        content = (unit.get("content") or "").strip()
        if not content:
            continue
        if speaker == char_name:
            lines.append(f"对{receiver or '？'}说：「{content[:120]}」")
        elif receiver == char_name:
            # 别人对他说的话同样是证据：反映其地位、关系与他人对他的态度
            received.append(f"{speaker or '某人'}对他说：「{content[:100]}」")
    # 台词过多时均匀采样，保证覆盖开头/中段/结尾
    if len(lines) > max_lines:
        step = len(lines) / max_lines
        lines = [lines[int(i * step)] for i in range(max_lines)]
    if len(received) > 6:
        step = len(received) / 6
        received = [received[int(i * step)] for i in range(6)]
    lines = lines + received

    events: list[str] = []
    for event in preview.get("events") or []:
        participants = _dedupe_names([event.get("actor", "")] + list(event.get("participants") or []))
        if char_name not in participants:
            continue
        summary = (event.get("summary") or event.get("action") or "").strip()
        if summary:
            events.append(summary[:100])

    relationships: list[str] = []
    for rel in preview.get("relationships") or []:
        source = (rel.get("source") or "").strip()
        target = (rel.get("target") or "").strip()
        if char_name not in (source, target):
            continue
        other = target if source == char_name else source
        desc = (rel.get("description") or "").strip()
        relationships.append(f"与{other}：{rel.get('rel_type') or 'neutral'}{('，' + desc[:60]) if desc else ''}")

    # 人物事实（资料型导入的主要证据来源；对话型导入的补充证据）
    facts: list[str] = []
    for fact in preview.get("persona_facts") or []:
        if (fact.get("subject") or "").strip() != char_name:
            continue
        content = (fact.get("content") or "").strip()
        if not content:
            continue
        category = (fact.get("category") or "").strip()
        time_hint = (fact.get("time_hint") or "").strip()
        facts.append(f"[{category}]{('(' + time_hint + ')') if time_hint else ''} {content}")
    if len(facts) > 24:
        step = len(facts) / 24
        facts = [facts[int(i * step)] for i in range(24)]
    lines = lines + facts

    hints: list[str] = []
    modeling = (preview.get("character_modeling") or {}).get(char_name) or {}
    if modeling.get("traits"):
        hints.append("规则推断标签：" + "、".join([str(t) for t in modeling["traits"]][:6]))
    pattern_names = [str(p.get("name") or "") for p in (modeling.get("behavior_patterns") or [])]
    pattern_names = [p for p in pattern_names if p]
    if pattern_names:
        hints.append("规则推断行为模式：" + "、".join(pattern_names[:5]))
    return lines, events[:6], relationships[:6], hints


def _apply_profile_candidate(
    db: Session,
    char: Character,
    candidate: dict[str, Any],
    *,
    source: str,
    evidence_note: str,
    base_confidence: float = 0.78,
    merge_mode: bool = True,
) -> bool:
    """
    统一档案应用入口——新建 / 导入融合 / AI 建议三条链路共用：
    - 文本字段：空则填；非空时融合模式直接深化（AI 已合并旧档案），非融合模式进待审核
    - personality_tags：并集
    - core_traits：EMA 融合
    - conflicts：进待审核，不悄悄改写
    返回是否发生了变更。
    """
    changed = False
    evidence_note = (evidence_note or "").strip() or "AI 档案候选"

    for field, module in PROFILE_TEXT_FIELDS:
        new_value = str(candidate.get(field) or "").strip()
        if not new_value:
            continue
        old_value = str(getattr(char, field, "") or "").strip()
        if old_value == new_value:
            continue
        if not old_value:
            setattr(char, field, new_value)
            _create_change_observation(
                db, char.id, field, old_value, new_value,
                source, evidence_note, base_confidence, module, "新增",
            )
            changed = True
        elif merge_mode:
            # 背景故事走服务器端确定性积累：旧句子全保留，新句子去重追加，
            # 不依赖 AI 自觉保留旧事实
            if field == "background":
                accumulated = merge_background(old_value, new_value)
                if accumulated != old_value:
                    setattr(char, field, accumulated)
                    _create_change_observation(
                        db, char.id, field, old_value, accumulated,
                        source, evidence_note, base_confidence, module, "深化",
                    )
                    changed = True
                continue
            # 其余字段严格单调：候选比现有内容短即视为信息量倒退，
            # 一律降级待审核——自动链路只许增厚，不许变薄
            if len(old_value) >= 10 and len(new_value) < len(old_value):
                _create_change_observation(
                    db, char.id, field, old_value, new_value,
                    source, f"{evidence_note}（候选内容短于现有档案，已拦截直接覆盖）",
                    round(max(0.0, base_confidence - 0.2), 2), module, "更新",
                    status="pending",
                )
                continue
            # 融合模式：候选档案已在旧档案基础上深化，直接应用并留痕
            setattr(char, field, new_value)
            _create_change_observation(
                db, char.id, field, old_value, new_value,
                source, evidence_note, base_confidence, module, "深化",
            )
            changed = True
        else:
            # 非融合模式：不覆盖已有内容（如用户手填），进待审核
            _create_change_observation(
                db, char.id, field, old_value, new_value,
                source, evidence_note, round(max(0.0, base_confidence - 0.1), 2), module, "更新",
                status="pending",
            )

    merged_tags = merge_tags(char.personality_tags, candidate.get("personality_tags"))
    if merged_tags != list(char.personality_tags or []):
        _create_change_observation(
            db, char.id, "personality_tags",
            list(char.personality_tags or []), merged_tags,
            source, evidence_note, base_confidence, "人格模型", "更新",
        )
        char.personality_tags = merged_tags
        changed = True

    blended = blend_traits(char.core_traits, candidate.get("core_traits"))
    current_subset = {
        key: value for key, value in (char.core_traits or {}).items()
        if key in BIG_FIVE_KEYS and isinstance(value, (int, float))
    }
    if blended and blended != current_subset:
        char.core_traits = {**(char.core_traits or {}), **blended}
        changed = True

    # 扩展人物模型（八维度）：只增不减地合并到 profile_json
    extended_candidate = candidate.get("extended")
    if isinstance(extended_candidate, dict) and extended_candidate:
        merged_extended, added_count = merge_extended_profile(char.profile_json, extended_candidate)
        if added_count:
            char.profile_json = merged_extended
            _create_change_observation(
                db, char.id, "profile_extended",
                "", f"扩展人物模型新增 {added_count} 条（价值观/恐惧/人际模式/矛盾性等）",
                source, evidence_note, base_confidence, "人格模型", "深化",
            )
            changed = True

    for conflict in candidate.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        field = (conflict.get("field") or "").strip()
        new_evidence = str(conflict.get("new_evidence") or "").strip()
        if not field or not new_evidence or not hasattr(char, field):
            continue
        _create_change_observation(
            db, char.id, field,
            str(conflict.get("existing") or getattr(char, field, "") or ""),
            new_evidence,
            source,
            str(conflict.get("suggestion") or "新证据与已有档案矛盾，请人工确认"),
            0.6,
            _resolve_profile_module(field),
            "矛盾",
            status="pending",
        )

    if changed:
        char.version += 1
        char.updated_at = datetime.utcnow()
        db.add(char)
        db.flush()
        graph_store.sync_character(char)
    return changed


async def _enrich_import_profiles(
    db: Session,
    preview: dict[str, Any],
    resolved_chars: dict[str, Character],
    concurrency: int = 3,
) -> tuple[int, dict[str, str]]:
    """
    渐进式档案融合：AI 同时看到角色当前档案 + 本次导入的新证据，
    输出深化后的完整档案。多次导入 = 多轮深化，档案逐渐丰满。
    无任何证据（台词/被提及/事件/关系）的角色不调 AI，避免凭名字脑补。
    返回 (深化角色数, {角色名: ok|unchanged|failed|no_evidence})。
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _enrich(original_name: str, char: Character):
        lines, event_samples, rel_samples, hints = _collect_character_evidence(preview, original_name)
        if not lines and not event_samples and not rel_samples:
            return char, None, "no_evidence"
        current_profile = json.dumps(_build_snapshot_payload(char), ensure_ascii=False)
        try:
            async with semaphore:
                profile = await orchestrator.generate_import_profile(
                    char.name,
                    current_profile,
                    "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines)),
                    "\n".join(f"- {item}" for item in event_samples),
                    "\n".join(f"- {item}" for item in rel_samples),
                    "\n".join(hints),
                )
            if isinstance(profile, dict):
                return char, profile, "ok"
            return char, None, "failed"
        except Exception as exc:
            import_logger.warning("导入画像生成失败 char=%s error=%s", char.name, exc)
            return char, None, "failed"

    results = await asyncio.gather(*(_enrich(name, char) for name, char in resolved_chars.items()))
    enriched = 0
    status_map: dict[str, str] = {}
    for char, profile, status in results:
        if not profile:
            status_map[char.name] = status
            continue
        evidence_note = (profile.get("evidence_notes") or "").strip() or "基于导入文本台词证据融合深化"
        if _apply_profile_candidate(
            db, char, profile,
            source="AI导入画像",
            evidence_note=evidence_note,
            base_confidence=0.8,
            merge_mode=True,
        ):
            _create_personality_snapshot(db, char, source="AI导入画像")
            enriched += 1
            status_map[char.name] = "ok"
        else:
            status_map[char.name] = "unchanged"

        # 人物弧光：检测到转折点 → 写入时间线（importance=5，标注心理转折）
        arc = profile.get("arc") or {}
        turning_point = (arc.get("turning_point") or "").strip()
        if turning_point:
            impact = "；".join(filter(None, [
                f"转折前：{(arc.get('start_state') or '').strip()}" if arc.get("start_state") else "",
                f"转折后：{(arc.get('end_state') or '').strip()}" if arc.get("end_state") else "",
            ]))
            exists = db.query(CharacterEvent).filter(
                CharacterEvent.character_id == char.id,
                CharacterEvent.arc_marker.is_(True),
                CharacterEvent.description == turning_point[:500],
            ).first()
            if not exists:
                db.add(CharacterEvent(
                    character_id=char.id,
                    title=f"心理转折：{turning_point[:30]}",
                    description=turning_point[:500],
                    event_date="",
                    psychological_impact=impact[:500],
                    arc_marker=True,
                    importance=5,
                    emotion_label="转折",
                ))
                db.flush()
    db.commit()
    return enriched, status_map


def _infer_rel_type(sentiment: float, interaction_type: str) -> str:
    if interaction_type in {"conflict", "对抗"}:
        return "rival"
    if interaction_type in {"support", "信任", "合作"}:
        return "ally"
    if sentiment >= 0.35:
        return "friend"
    if sentiment <= -0.35:
        return "rival"
    return "neutral"


def _merge_metadata(import_file: ImportFile, extra: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(import_file.metadata_json or {})
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(metadata.get(key), dict):
            merged_child = dict(metadata.get(key) or {})
            merged_child.update(value)
            metadata[key] = merged_child
        else:
            metadata[key] = value
    return metadata


def _create_evidence_span(
    db: Session,
    *,
    character_id: int | None = None,
    source_type: str = "unknown",
    source_id: int | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
    import_file_id: int | None = None,
    interaction_unit_id: int | None = None,
    character_event_id: int | None = None,
    relationship_id: int | None = None,
    observation_id: int | None = None,
    supports_type: str = "memory",
    supports_id: int | None = None,
    polarity: str = "supports",
    quote: str = "",
    interpretation: str = "",
    confidence: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> EvidenceSpan:
    evidence = EvidenceSpan(
        character_id=character_id,
        source_type=source_type,
        source_id=source_id,
        conversation_id=conversation_id,
        message_id=message_id,
        import_file_id=import_file_id,
        interaction_unit_id=interaction_unit_id,
        character_event_id=character_event_id,
        relationship_id=relationship_id,
        observation_id=observation_id,
        supports_type=supports_type,
        supports_id=supports_id,
        polarity=polarity,
        quote=(quote or "")[:2000],
        interpretation=(interpretation or "")[:2000],
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        metadata_json=metadata or {},
    )
    db.add(evidence)
    db.flush()
    graph_store.sync_evidence(evidence)
    return evidence


def _create_memory_item(
    db: Session,
    *,
    character_id: int,
    memory_type: str,
    content: str,
    confidence: float,
    source: str,
    evidence_ids: list[int] | None = None,
) -> MemoryItem | None:
    normalized = (content or "").strip()
    if not normalized:
        return None
    existing = db.query(MemoryItem).filter(
        MemoryItem.character_id == character_id,
        MemoryItem.memory_type == memory_type,
        MemoryItem.content == normalized,
        MemoryItem.status == "active",
    ).first()
    if existing:
        merged_ids = list(dict.fromkeys(list(existing.evidence_ids or []) + list(evidence_ids or [])))
        existing.evidence_ids = merged_ids
        existing.confidence = max(float(existing.confidence or 0.0), max(0.0, min(1.0, float(confidence or 0.0))))
        existing.updated_at = datetime.utcnow()
        db.flush()
        graph_store.sync_memory(existing)
        return existing
    from ..harness.embeddings import embed_text
    memory = MemoryItem(
        character_id=character_id,
        memory_type=memory_type,
        content=normalized[:2000],
        embedding=embed_text(normalized[:2000]),
        confidence=max(0.0, min(1.0, float(confidence or 0.0))),
        evidence_ids=list(evidence_ids or []),
        source=source,
        status="active",
    )
    db.add(memory)
    db.flush()
    graph_store.sync_memory(memory)
    return memory


@router.post("/maintenance/backfill-embeddings")
def backfill_embeddings(limit: int = 500, db: Session = Depends(get_db)):
    """给历史上没有向量的记忆补算 embedding（开启向量检索后运行一次即可）。
    分批处理，返回本批补了多少、还剩多少，可重复调用直到 remaining=0。"""
    from ..harness.embeddings import embed_text, embedding_enabled
    if not embedding_enabled():
        return {
            "ok": False,
            "reason": "embedding 未启用：检查 config 的 embedding.enabled / base_url / api_key / model",
            "updated": 0,
            "remaining": db.query(MemoryItem).filter(MemoryItem.embedding.is_(None)).count(),
        }
    rows = (
        db.query(MemoryItem)
        .filter(MemoryItem.embedding.is_(None), MemoryItem.status == "active")
        .limit(max(1, min(limit, 2000)))
        .all()
    )
    updated = 0
    for memory in rows:
        vector = embed_text((memory.content or "")[:2000])
        if vector:
            memory.embedding = vector
            updated += 1
    db.commit()
    remaining = db.query(MemoryItem).filter(MemoryItem.embedding.is_(None), MemoryItem.status == "active").count()
    return {"ok": True, "updated": updated, "remaining": remaining}


# ── RAG 参考资料库（上传的资料切块入向量库，对话/分析时作为依据被检索召回） ──
KNOWLEDGE_CHUNK_SIZE = 700
KNOWLEDGE_CHUNK_OVERLAP = 100
KNOWLEDGE_MAX_CHUNKS = 80


@router.post("/{character_id}/knowledge")
async def upload_knowledge(character_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """给角色上传参考资料：抽取文本 → 切块 → 算向量 → 存为 reference 记忆。
    这些块会被现有语义检索自动召回，作为对话/分析的依据。"""
    char = db.get(Character, character_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    from ..harness.embeddings import embed_text, embedding_enabled
    raw = await file.read()
    try:
        text = await extract_text_from_file(file.filename, raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    text = (text or "").strip()
    if len(text) < 10:
        raise HTTPException(400, "未能从文件中提取到有效文本")

    source = f"资料:{file.filename}"[:200]
    # 同名资料先清掉旧块，避免重复
    db.query(MemoryItem).filter(MemoryItem.character_id == character_id, MemoryItem.source == source).delete(synchronize_session=False)
    # 语义分块：整句打包不切句，每块是连贯语义单元 → embedding 更准、召回更稳
    chunks = semantic_chunk_text(text, target_size=KNOWLEDGE_CHUNK_SIZE, overlap_sentences=1)
    truncated = len(chunks) > KNOWLEDGE_MAX_CHUNKS
    chunks = chunks[:KNOWLEDGE_MAX_CHUNKS]
    added = 0
    for chunk in chunks:
        content = chunk.strip()
        if len(content) < 10:
            continue
        db.add(MemoryItem(
            character_id=character_id,
            memory_type="reference",
            content=content[:2000],
            embedding=embed_text(content[:2000]) if embedding_enabled() else None,
            confidence=0.6,
            evidence_ids=[],
            source=source,
            status="active",
        ))
        added += 1
    db.commit()
    # 自主判断：短资料其实更适合走"导入→丰富档案"，给个提示但仍按资料入库
    hint = ""
    if len(text) < 400 and detect_import_type(file.filename, text) == "profile_document":
        hint = "这份资料较短、像人物简介——若想直接丰富档案，可改用「导入」功能。"
    return {
        "ok": True, "source": source, "chunks_added": added, "chars": len(text),
        "embedded": embedding_enabled(), "truncated": truncated, "hint": hint,
    }


@router.get("/{character_id}/knowledge")
def list_knowledge(character_id: int, db: Session = Depends(get_db)):
    """列出该角色的参考资料（按来源文件聚合块数）。"""
    rows = db.query(MemoryItem).filter(
        MemoryItem.character_id == character_id,
        MemoryItem.memory_type == "reference",
        MemoryItem.status == "active",
    ).all()
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        src = row.source or "资料"
        item = by_source.setdefault(src, {"source": src, "chunks": 0, "embedded": 0})
        item["chunks"] += 1
        if row.embedding:
            item["embedded"] += 1
    return {"character_id": character_id, "files": list(by_source.values()), "total_chunks": len(rows)}


@router.delete("/{character_id}/knowledge")
def delete_knowledge(character_id: int, source: str = "", db: Session = Depends(get_db)):
    """删除该角色的参考资料：指定 source 删该文件，否则删全部 reference 块。"""
    q = db.query(MemoryItem).filter(
        MemoryItem.character_id == character_id,
        MemoryItem.memory_type == "reference",
    )
    if source:
        q = q.filter(MemoryItem.source == source)
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": deleted}


# ── 直接 JSON 档案导入（所见即所存，不走 AI 分析）─────────────────────────
# 一份完整模板：可下载、填写后直接上传落库。覆盖基础字段 + 大五人格 + 立体档案八维度 + 事件 + 关系。
PROFILE_JSON_TEMPLATE: dict[str, Any] = {
    "version": "profile-json/v1",
    "_说明": "characters 必填；同名（或别名命中）则更新已有角色，否则新建。提供的字段直接覆盖保存，未提供的字段保持原样。relationships/events 可选。",
    "characters": [
        {
            "name": "张三",
            "aliases": ["张总", "老张"],
            "role": "项目经理",
            "age": 35,
            "avatar_color": "#00d4ff",
            "background": "白手起家的创业者，经历过一次失败后转做管理，做事雷厉风行。",
            "personality_tags": ["强势", "完美主义", "外冷内热"],
            "core_traits": {
                "openness": 0.6, "conscientiousness": 0.85,
                "extraversion": 0.7, "agreeableness": 0.4, "neuroticism": 0.5
            },
            "motivation": "证明自己的判断是对的，重新赢得话语权。",
            "weakness": "怕失控，被否定时容易上头。",
            "speaking_style": "短促命令式，爱用反问，少寒暄。",
            "profile_json": {
                "values": ["重视效率与结果", "认为承诺必须兑现"],
                "desires": [{"surface": "想拿下这个项目", "deep": "渴望被团队真正认可"}],
                "fears": [{"content": "怕局面失控、被人看穿不自信"}],
                "interpersonal_patterns": [{"context": "面对下属", "pattern": "先施压立威，再私下安抚"}],
                "key_experiences": [{"event": "第一次创业失败", "impact": "从此凡事留后手、不轻易信人"}],
                "speech_fingerprint": {
                    "catchphrases": ["这事得抓紧", "你觉得呢？"],
                    "sentence_style": "短句、命令式、爱反问",
                    "avoided_topics": ["家庭", "那次失败"]
                },
                "contradictions": [{"side_a": "嘴上说不在乎别人评价", "side_b": "却频频打听别人怎么说他", "interpretation": "极度在意但要面子"}],
                "self_image_vs_public": {"self": "果断可靠的领导者", "public": "难搞、强势的老板"}
            },
            "events": [
                {"title": "晋升为项目经理", "description": "临危受命接手烂摊子项目。", "event_date": "2022-03", "emotion_label": "振奋", "importance": 4, "arc_marker": True}
            ]
        },
        {
            "name": "李四",
            "role": "技术骨干",
            "personality_tags": ["内敛", "较真"],
            "motivation": "把事情做对，不愿被外行指挥。",
            "weakness": "不善表达，容易憋着。",
            "profile_json": {
                "values": ["重视专业与逻辑"],
                "fears": [{"content": "怕努力被无视"}]
            }
        }
    ],
    "relationships": [
        {"source": "张三", "target": "李四", "rel_type": "rival", "strength": 0.6, "sentiment": -0.3, "description": "表面合作、暗自较劲的上下级。"}
    ]
}

_DIRECT_SCALAR_FIELDS = ("role", "background", "motivation", "weakness", "speaking_style")


def _clamp01(value: Any) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return None


def _apply_direct_character(db: Session, item: dict) -> tuple[Character | None, bool]:
    """把一条 JSON 角色直接落库（同名/别名命中则更新，否则新建）。返回 (char, created)。"""
    name = (item.get("name") or "").strip()
    if not name:
        return None, False
    char = find_character_by_name(db, name)
    created = char is None
    if created:
        char = Character(name=name)
        db.add(char)
    for field in _DIRECT_SCALAR_FIELDS:
        if item.get(field) is not None:
            setattr(char, field, str(item[field]))
    if isinstance(item.get("age"), int):
        char.age = item["age"]
    if (item.get("avatar_color") or "").strip():
        char.avatar_color = str(item["avatar_color"]).strip()[:20]
    for alias in item.get("aliases") or []:
        add_alias(char, str(alias))
    if isinstance(item.get("personality_tags"), list):
        char.personality_tags = merge_tags([], item["personality_tags"])
    if isinstance(item.get("core_traits"), dict):
        traits = dict(char.core_traits or {})
        for key, value in item["core_traits"].items():
            if key in BIG_FIVE_KEYS:
                clamped = _clamp01(value)
                if clamped is not None:
                    traits[key] = clamped
        char.core_traits = traits
    # 立体档案：只写入合法维度，顶层合并（不动未提供的维度），所见即所存
    if isinstance(item.get("profile_json"), dict):
        profile = dict(char.profile_json or {})
        for key, value in item["profile_json"].items():
            if key in EXTENDED_DIMENSIONS:
                profile[key] = value
        char.profile_json = profile
    char.version = (char.version or 1) + (0 if created else 1)
    char.updated_at = datetime.utcnow()
    return char, created


def _apply_direct_events(db: Session, char: Character, events: Any) -> int:
    if not isinstance(events, list):
        return 0
    existing = {
        ((e.title or ""), (e.event_date or ""))
        for e in db.query(CharacterEvent).filter_by(character_id=char.id).all()
    }
    added = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        title = (event.get("title") or "").strip()
        if not title:
            continue
        date = (event.get("event_date") or "").strip()
        if (title, date) in existing:
            continue
        existing.add((title, date))
        importance = event.get("importance")
        db.add(CharacterEvent(
            character_id=char.id,
            title=title[:200],
            description=(event.get("description") or "").strip(),
            event_date=date[:50],
            emotion_label=(event.get("emotion_label") or "").strip()[:50],
            importance=importance if isinstance(importance, int) and 1 <= importance <= 5 else 3,
            psychological_impact=(event.get("psychological_impact") or "").strip(),
            arc_marker=bool(event.get("arc_marker")),
        ))
        added += 1
    return added


def _apply_direct_relationship(db: Session, rel: dict, name_to_char: dict) -> bool:
    def _resolve(key: str) -> Character | None:
        nm = (rel.get(key) or "").strip()
        return name_to_char.get(nm) or find_character_by_name(db, nm)
    source, target = _resolve("source"), _resolve("target")
    if not source or not target or source.id == target.id:
        return False
    pair = find_pair_relationship(db, source.id, target.id)
    if not pair:
        pair = Relationship(source_id=source.id, target_id=target.id)
        db.add(pair)
    if (rel.get("rel_type") or "").strip():
        pair.rel_type = rel["rel_type"].strip()[:50]
    strength = _clamp01(rel.get("strength"))
    if strength is not None:
        pair.strength = strength
    try:
        pair.sentiment = max(-1.0, min(1.0, float(rel.get("sentiment"))))
    except (TypeError, ValueError):
        pass
    if (rel.get("description") or "").strip():
        pair.description = rel["description"].strip()
    pair.updated_at = datetime.utcnow()
    return True


@router.get("/import-profile-json/template")
def get_import_profile_json_template():
    """下载直接导入用的完整 JSON 模板（填好后上传到 /import-profile-json）。"""
    return PROFILE_JSON_TEMPLATE


@router.post("/import-profile-json")
async def import_profile_json(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """按 JSON 直接导入人物档案：所见即所存，不走 AI 分析。
    支持 {characters:[...], relationships:[...]} / 角色数组 / 单个角色对象三种形态。
    同名（或别名命中）更新已有角色，否则新建；提供的字段覆盖，未提供的保持原样。"""
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception as exc:
        raise HTTPException(400, f"JSON 解析失败：{exc}")

    if isinstance(data, dict) and isinstance(data.get("characters"), list):
        char_items, rel_items = data["characters"], (data.get("relationships") or [])
    elif isinstance(data, list):
        char_items, rel_items = data, []
    elif isinstance(data, dict) and (data.get("name") or "").strip():
        char_items, rel_items = [data], []
    else:
        raise HTTPException(400, "JSON 结构不对：应为 {characters:[...], relationships:[...]}、角色数组、或单个角色对象")

    created = updated = events_added = 0
    name_to_char: dict[str, Character] = {}
    details = []
    for item in char_items:
        if not isinstance(item, dict):
            continue
        char, is_new = _apply_direct_character(db, item)
        if not char:
            continue
        db.flush()  # 拿到 char.id 供事件/关系引用
        name_to_char[char.name] = char
        if is_new:
            created += 1
        else:
            updated += 1
        ev_added = _apply_direct_events(db, char, item.get("events"))
        events_added += ev_added
        try:
            graph_store.sync_character(char)
        except Exception:
            pass
        details.append({"name": char.name, "id": char.id, "action": "created" if is_new else "updated", "events_added": ev_added})

    rel_added = sum(
        1 for rel in rel_items
        if isinstance(rel, dict) and _apply_direct_relationship(db, rel, name_to_char)
    )
    db.commit()
    if not details:
        raise HTTPException(400, "未解析到任何有效角色（每个角色至少需要 name 字段）")
    return {
        "ok": True,
        "characters_created": created,
        "characters_updated": updated,
        "events_added": events_added,
        "relationships_added": rel_added,
        "details": details,
    }


def _build_snapshot_payload(char: Character) -> dict[str, Any]:
    return {
        "basic_info": {
            "name": char.name,
            "role": char.role or "",
            "background": char.background or "",
            "age": char.age,
        },
        "personality_model": {
            "tags": char.personality_tags or [],
            "core_traits": char.core_traits or {},
        },
        "core_motivation": char.motivation or "",
        "core_weakness": char.weakness or "",
        "speaking_style": char.speaking_style or "",
    }


def _create_personality_snapshot(
    db: Session,
    char: Character,
    *,
    source: str,
    supporting_evidence: list[int] | None = None,
    conflicting_evidence: list[int] | None = None,
    critic_result: dict[str, Any] | None = None,
) -> PersonalitySnapshot:
    latest = db.query(PersonalitySnapshot).filter(
        PersonalitySnapshot.character_id == char.id
    ).order_by(PersonalitySnapshot.version.desc()).first()
    snapshot = PersonalitySnapshot(
        character_id=char.id,
        version=(latest.version if latest else 0) + 1,
        profile_json=_build_snapshot_payload(char),
        supporting_evidence=list(supporting_evidence or []),
        conflicting_evidence=list(conflicting_evidence or []),
        critic_result=critic_result or {"status": "not_reviewed", "reason": "第二阶段证据层基础快照，尚未接入 Critic Agent。"},
        source=source,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _clip_text(text: str | None, limit: int = 700) -> str:
    return " ".join((text or "").split())[:limit]


def _review_window_filter(query, model, window_days: int | None):
    if not window_days:
        return query
    cutoff = datetime.utcnow() - timedelta(days=max(1, int(window_days)))
    if hasattr(model, "created_at"):
        return query.filter(model.created_at >= cutoff)
    return query


def _build_review_corpus(db: Session, char: Character, body: CharacterReviewRequest) -> dict[str, Any]:
    relationships = db.query(Relationship).filter(
        (Relationship.source_id == char.id) | (Relationship.target_id == char.id)
    ).all()
    events_query = db.query(CharacterEvent).filter(CharacterEvent.character_id == char.id)
    events_query = _review_window_filter(events_query, CharacterEvent, body.window_days)
    events = events_query.order_by(CharacterEvent.created_at.desc()).limit(80).all()

    memories_query = db.query(MemoryItem).filter(
        MemoryItem.character_id == char.id,
        MemoryItem.status == "active",
    )
    memories_query = _review_window_filter(memories_query, MemoryItem, body.window_days)
    memories = memories_query.order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).limit(
        min(max(body.max_memories, 1), 300)
    ).all()

    evidence_query = db.query(EvidenceSpan).filter(EvidenceSpan.character_id == char.id)
    evidence_query = _review_window_filter(evidence_query, EvidenceSpan, body.window_days)
    evidence = evidence_query.order_by(EvidenceSpan.created_at.desc()).limit(
        min(max(body.max_evidence, 1), 500)
    ).all()

    diagnoses_query = db.query(StructuredDiagnosis).filter(
        (StructuredDiagnosis.speaker_id == char.id) | (StructuredDiagnosis.listener_id == char.id)
    )
    diagnoses_query = _review_window_filter(diagnoses_query, StructuredDiagnosis, body.window_days)
    diagnoses = diagnoses_query.order_by(StructuredDiagnosis.created_at.desc()).limit(
        min(max(body.max_diagnoses, 1), 300)
    ).all()

    messages_query = db.query(Message).filter(
        (Message.character_id == char.id)
        | (Message.character_name == char.name)
        | (Message.receiver_id == char.id)
        | (Message.receiver_name == char.name)
    )
    messages_query = _review_window_filter(messages_query, Message, body.window_days)
    messages = list(reversed(messages_query.order_by(Message.created_at.desc()).limit(
        min(max(body.max_messages, 1), 800)
    ).all()))

    latest_snapshot = db.query(PersonalitySnapshot).filter(
        PersonalitySnapshot.character_id == char.id
    ).order_by(PersonalitySnapshot.version.desc()).first()
    corpus = {
        "character": _build_snapshot_payload(char),
        "latest_snapshot": {
            "id": latest_snapshot.id,
            "version": latest_snapshot.version,
            "source": latest_snapshot.source,
            "profile_json": latest_snapshot.profile_json or {},
            "critic_result": latest_snapshot.critic_result or {},
        } if latest_snapshot else {},
        "scope": {
            "window_days": body.window_days,
            "generated_at": datetime.utcnow().isoformat(),
            "message_count": len(messages),
            "evidence_count": len(evidence),
            "memory_count": len(memories),
            "diagnosis_count": len(diagnoses),
            "event_count": len(events),
            "relationship_count": len(relationships),
        },
        "relationships": [
            {
                "id": rel.id,
                "source_id": rel.source_id,
                "source_name": rel.source.name if rel.source else "",
                "target_id": rel.target_id,
                "target_name": rel.target.name if rel.target else "",
                "rel_type": rel.rel_type,
                "strength": rel.strength,
                "sentiment": rel.sentiment,
                "description": _clip_text(rel.description, 300),
                "history_tail": (rel.history or [])[-5:],
            }
            for rel in relationships
        ],
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "description": _clip_text(event.description, 500),
                "event_date": event.event_date or "",
                "emotion_label": event.emotion_label or "",
                "importance": event.importance,
            }
            for event in events
        ],
        "memories": [
            {
                "id": memory.id,
                "memory_type": memory.memory_type,
                "content": _clip_text(memory.content, 500),
                "confidence": memory.confidence,
                "evidence_ids": memory.evidence_ids or [],
                "source": memory.source,
            }
            for memory in memories
        ],
        "evidence": [
            {
                "id": item.id,
                "source_type": item.source_type,
                "supports_type": item.supports_type,
                "polarity": item.polarity,
                "quote": _clip_text(item.quote, 500),
                "interpretation": _clip_text(item.interpretation, 500),
                "confidence": item.confidence,
                "created_at": item.created_at.isoformat() if item.created_at else "",
            }
            for item in evidence
        ],
        "diagnoses": [
            {
                "id": report.id,
                "diagnosis_type": report.diagnosis_type,
                "status": report.status,
                "confidence": report.confidence,
                "summary": _clip_text((report.critic_json or {}).get("revised_summary") or (report.result_json or {}).get("summary"), 500),
                "evidence_ids": report.evidence_ids or [],
                "conflicting_evidence_ids": report.conflicting_evidence_ids or [],
                "created_at": report.created_at.isoformat() if report.created_at else "",
            }
            for report in diagnoses
        ],
        "messages": [
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "speaker": message.character_name or "",
                "receiver": message.receiver_name or "",
                "content": _clip_text(message.content, 700),
                "intent": message.intent or "",
                "strategy": message.strategy or "",
                "emotion": message.emotion or "",
                "subtext": _clip_text(message.subtext, 500),
                "psychological_tag": message.psychological_tag or "",
                "created_at": message.created_at.isoformat() if message.created_at else "",
            }
            for message in messages
        ],
    }
    return corpus


def _review_corpus_summary(corpus: dict[str, Any]) -> dict[str, Any]:
    scope = corpus.get("scope") or {}
    return {
        "character": (corpus.get("character") or {}).get("basic_info", {}),
        "scope": scope,
        "top_evidence_ids": [item.get("id") for item in (corpus.get("evidence") or [])[:30]],
        "top_memory_ids": [item.get("id") for item in (corpus.get("memories") or [])[:30]],
        "diagnosis_status_counts": {
            status: len([item for item in corpus.get("diagnoses", []) if item.get("status") == status])
            for status in ["approved", "downgraded", "insufficient", "rejected"]
        },
    }


def _approved_indexes(values: Any, fallback_len: int) -> set[int]:
    if isinstance(values, list):
        indexes = set()
        for value in values:
            try:
                indexes.add(int(value))
            except Exception:
                continue
        return indexes
    return set(range(fallback_len))


def _evidence_ids_from_review(items: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for item in items or []:
        values = []
        values.extend(item.get("evidence_ids") or [])
        values.extend(item.get("supporting_evidence_ids") or [])
        values.extend(item.get("conflicting_evidence_ids") or [])
        for value in values:
            try:
                ids.append(int(value))
            except Exception:
                continue
    return list(dict.fromkeys(ids))


def _update_import_status(db: Session, import_file: ImportFile, status: str, message: str, **extra: Any) -> None:
    import_file.status = status
    import_file.metadata_json = _merge_metadata(
        import_file,
        {
            "progress": {
                "message": message,
                "updated_at": datetime.utcnow().isoformat(),
            },
            **extra,
        },
    )
    db.add(import_file)
    db.commit()
    db.refresh(import_file)


def _format_behavior_pattern_reason(
    source: str,
    confidence: float,
    category: str = "互动策略",
    trigger: str = "",
    example: str = "",
) -> str:
    return _build_observation_reason(
        source=source or "AI自动识别",
        evidence=example or trigger or "行为模式识别结果",
        confidence=confidence,
        change_type="新增",
        module="行为模式",
        category=category or "互动策略",
        trigger=trigger,
        example=example,
    )


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_tag_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [item.strip() for item in text.replace("/", "、").replace(",", "、").split("、") if item.strip()]
    return []


def _normalize_core_traits(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        source = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            source = parsed if isinstance(parsed, dict) else {}
        except Exception:
            source = {}
    else:
        source = {}
    return {key: source.get(key, None) for key in BIG_FIVE_KEYS}


def _build_observation_reason(
    source: str,
    evidence: str,
    confidence: float,
    change_type: str,
    module: str,
    category: str = "",
    trigger: str = "",
    example: str = "",
) -> str:
    lines = [
        f"来源：{source or 'AI自动识别'}",
        f"依据：{evidence or 'AI 解析结果'}",
        f"置信度：{max(0.0, min(1.0, float(confidence or 0.0))):.2f}",
        f"类型：{change_type or '新增'}",
        f"模块：{module or '角色档案'}",
    ]
    if category:
        lines.append(f"分类：{category}")
    if trigger:
        lines.append(f"触发：{trigger}")
    if example:
        lines.append(f"示例：{example}")
    return "\n".join(lines)


def _parse_observation_reason(reason: str) -> dict[str, Any]:
    metadata = {
        "source": "AI自动识别",
        "evidence": "",
        "confidence": 0.0,
        "change_type": "新增",
        "module": "",
        "category": "",
        "trigger": "",
        "example": "",
    }
    for raw_line in (reason or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("来源："):
            metadata["source"] = line.replace("来源：", "", 1).strip() or metadata["source"]
        elif line.startswith("依据："):
            metadata["evidence"] = line.replace("依据：", "", 1).strip()
        elif line.startswith("置信度："):
            metadata["confidence"] = _safe_float(line.replace("置信度：", "", 1).strip(), 0.0)
        elif line.startswith("类型："):
            metadata["change_type"] = line.replace("类型：", "", 1).strip() or metadata["change_type"]
        elif line.startswith("模块："):
            metadata["module"] = line.replace("模块：", "", 1).strip()
        elif line.startswith("分类："):
            metadata["category"] = line.replace("分类：", "", 1).strip()
        elif line.startswith("触发："):
            metadata["trigger"] = line.replace("触发：", "", 1).strip()
        elif line.startswith("示例："):
            metadata["example"] = line.replace("示例：", "", 1).strip()
    return metadata


def _build_observation_metadata(
    source: str,
    evidence: str,
    confidence: float,
    change_type: str,
    module: str,
    category: str = "",
    trigger: str = "",
    example: str = "",
) -> dict[str, Any]:
    return {
        "source": source or "AI自动识别",
        "evidence": evidence or "AI 解析结果",
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 2),
        "change_type": change_type or "新增",
        "module": module or "角色档案",
        "category": category,
        "trigger": trigger,
        "example": example,
    }


def _observation_metadata(observation: CharacterObservation) -> dict[str, Any]:
    """读取 observation 元数据：优先结构化 metadata_json，历史数据回退解析 reason 文本"""
    metadata = getattr(observation, "metadata_json", None)
    if isinstance(metadata, dict) and metadata.get("source"):
        return metadata
    return _parse_observation_reason(observation.reason or "")


def _resolve_profile_module(field: str, metadata: dict[str, Any] | None = None) -> str:
    if metadata and metadata.get("module"):
        return metadata["module"]
    mapping = {
        "name": "基础信息",
        "role": "基础信息",
        "background": "基础信息",
        "age": "基础信息",
        "personality_tags": "人格模型",
        "core_traits": "人格模型",
        "behavior_pattern": "行为模式",
        "motivation": "核心动机",
        "weakness": "核心弱点",
        "speaking_style": "说话风格",
        "relationship_network": "关系网络",
        "event_timeline": "事件时间线",
    }
    return mapping.get(field, "基础信息")


def _infer_change_type(old_value: Any, new_value: Any, prefer_override: bool = False) -> str:
    old_text = _stringify_value(old_value)
    new_text = _stringify_value(new_value)
    if not old_text and new_text:
        return "新增"
    if old_text and new_text and old_text != new_text:
        return "覆盖" if prefer_override else "更新"
    return "新增"


def _create_change_observation(
    db: Session,
    char_id: int,
    field: str,
    old_value: Any,
    new_value: Any,
    source: str,
    evidence: str,
    confidence: float,
    module: str,
    change_type: str,
    status: str = "approved",
    category: str = "",
    trigger: str = "",
    example: str = "",
) -> CharacterObservation | None:
    normalized_new_value = _stringify_value(new_value)
    if not normalized_new_value and field not in {"relationship_network", "event_timeline"}:
        return None
    existing = db.query(CharacterObservation).filter(
        CharacterObservation.character_id == char_id,
        CharacterObservation.field == field,
        CharacterObservation.new_value == normalized_new_value,
    ).order_by(CharacterObservation.created_at.desc()).first()
    if existing:
        return existing
    observation = CharacterObservation(
        character_id=char_id,
        field=field,
        old_value=_stringify_value(old_value),
        new_value=normalized_new_value,
        reason=_build_observation_reason(
            source=source,
            evidence=evidence,
            confidence=confidence,
            change_type=change_type,
            module=module,
            category=category,
            trigger=trigger,
            example=example,
        ),
        metadata_json=_build_observation_metadata(
            source=source,
            evidence=evidence,
            confidence=confidence,
            change_type=change_type,
            module=module,
            category=category,
            trigger=trigger,
            example=example,
        ),
        status=status,
        reviewed_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(observation)
    db.flush()
    evidence_span = _create_evidence_span(
        db,
        character_id=char_id,
        source_type=source,
        source_id=observation.id,
        observation_id=observation.id,
        supports_type=field,
        supports_id=observation.id,
        quote=example or evidence or normalized_new_value,
        interpretation=f"{module} / {change_type}：{normalized_new_value}",
        confidence=confidence,
        metadata={
            "module": module,
            "field": field,
            "category": category,
            "trigger": trigger,
        },
    )
    memory_type = {
        "personality_tags": "diagnosis",
        "core_traits": "diagnosis",
        "motivation": "fact",
        "weakness": "emotion",
        "speaking_style": "pragmatics",
        "behavior_pattern": "pragmatics",
        "relationship_network": "relationship",
        "event_timeline": "fact",
    }.get(field, "fact")
    _create_memory_item(
        db,
        character_id=char_id,
        memory_type=memory_type,
        content=normalized_new_value,
        confidence=confidence,
        source=source,
        evidence_ids=[evidence_span.id],
    )
    return observation


def _coerce_observation_value(field: str, value: str) -> Any:
    if field == "personality_tags":
        return _normalize_tag_list(value)
    if field == "core_traits":
        return {key: val for key, val in _normalize_core_traits(value).items() if val is not None}
    if field == "age":
        text = (value or "").strip()
        return int(text) if text.isdigit() else None
    return value


def _split_speaking_style_tags(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace("/", "、").replace(",", "、").split("、") if item.strip()]


# ── 方向2：行为模式派生（从人际模式 + 互动 strategy 聚合，只读展示，不落库、不计完整度）──
_DERIVED_MAX_PER_CATEGORY = 6


def _norm_label(text: str) -> str:
    return "".join((text or "").split())[:60]


def _character_interaction_units(db: Session, char: Character, limit: int = 300) -> list:
    """取该角色（含别名）作为发言者的交互单元——行为模式的 strategy 原料。"""
    names = [char.name] + list(char.aliases or [])
    return db.query(InteractionUnit).filter(InteractionUnit.speaker.in_(names)).limit(limit).all()


def _derive_behavior_patterns(profile_json: dict, strategy_units: list[dict]) -> dict[str, list]:
    """从「人际模式」立体维度 + 互动 strategy 聚合出行为模式分组。每条标 derived=True、注明来源。"""
    groups: dict[str, list] = {"攻击型行为": [], "防御型行为": [], "互动策略": []}
    seen: set[str] = set()

    def _add(label: str, category: str, source: str, evidence: str, confidence: float, example: str = "") -> None:
        key = _norm_label(label)
        if not key or len(key) < 2 or key in seen:
            return
        seen.add(key)
        groups.setdefault(category, [])
        groups[category].append({
            "label": label[:60],
            "source": source,
            "evidence": (evidence or "")[:200] or None,
            "confidence": round(float(confidence), 2),
            "trigger": None,
            "example": (example or "")[:80] or None,
            "derived": True,
        })

    # 1) 人际模式 → 行为模式（兼容裸串 / {context,pattern} / 规范 {content}）
    for item in (profile_json or {}).get("interpersonal_patterns") or []:
        text = fact_content(item)
        if not text:
            continue
        _add(text, classify_behavior_pattern_category(text), "派生·人际模式", text, fact_confidence(item) or 0.6)

    # 2) 互动 strategy 聚合 → 重复出现即一种稳定行为模式
    counter: dict[str, int] = {}
    sample: dict[str, str] = {}
    for unit in strategy_units:
        strategy = (unit.get("strategy") or "").strip()
        if not strategy:
            continue
        counter[strategy] = counter.get(strategy, 0) + 1
        sample.setdefault(strategy, (unit.get("content") or "").strip())
    for strategy, count in sorted(counter.items(), key=lambda kv: kv[1], reverse=True):
        category = classify_behavior_pattern_category(f"{strategy} {sample.get(strategy, '')}")
        _add(strategy, category, "派生·互动策略", f"对话中出现 {count} 次", min(0.95, 0.5 + count * 0.1), sample.get(strategy, ""))

    for key in groups:
        groups[key] = groups[key][:_DERIVED_MAX_PER_CATEGORY]
    return groups


def _build_profile_view(
    char: Character,
    relationships: list[Relationship],
    events: list[CharacterEvent],
    observations: list[CharacterObservation],
) -> dict[str, Any]:
    behavior_groups = {
        "攻击型行为": [],
        "防御型行为": [],
        "互动策略": [],
    }
    for observation in observations:
        if observation.field != "behavior_pattern" or observation.status != "approved":
            continue
        metadata = _observation_metadata(observation)
        category = metadata.get("category") or "互动策略"
        behavior_groups.setdefault(category, [])
        behavior_groups[category].append(
            {
                "id": observation.id,
                "label": observation.new_value,
                "source": metadata.get("source") or "AI自动识别",
                "evidence": metadata.get("evidence") or None,
                "confidence": round(_safe_float(metadata.get("confidence"), 0.0), 2),
                "trigger": metadata.get("trigger") or None,
                "example": metadata.get("example") or None,
            }
        )
    relationship_items = []
    for relation in relationships:
        counterpart = relation.target if relation.source_id == char.id else relation.source
        relationship_items.append(
            {
                "id": relation.id,
                "target_id": counterpart.id if counterpart else None,
                "target_name": counterpart.name if counterpart else "",
                "rel_type": relation.rel_type,
                "strength": relation.strength,
                "sentiment": relation.sentiment,
                "description": relation.description or None,
            }
        )
    event_items = [
        {
            "id": event.id,
            "title": event.title,
            "description": event.description or None,
            "event_date": event.event_date or None,
            "emotion_label": event.emotion_label or None,
            "importance": event.importance,
        }
        for event in events
    ]
    return {
        "basic_info": {
            "name": char.name,
            "role": char.role or None,
            "background": char.background or None,
            "age": char.age,
        },
        "personality_model": {
            "tags": list(char.personality_tags or []),
            "core_traits": _normalize_core_traits(char.core_traits),
        },
        "behavior_patterns": behavior_groups,
        "core_motivation": char.motivation or None,
        "core_weakness": char.weakness or None,
        "speaking_style": {
            "summary": char.speaking_style or None,
            "tags": _split_speaking_style_tags(char.speaking_style or ""),
        },
        "relationship_network": relationship_items,
        "event_timeline": event_items,
    }


def _build_ai_update_log(observations: list[CharacterObservation]) -> dict[str, Any]:
    grouped = {module: [] for module in PROFILE_MODULES}
    total = 0
    approved = 0
    pending = 0
    for observation in observations:
        if observation.status == "archived":
            continue
        metadata = _observation_metadata(observation)
        source = metadata.get("source") or "AI自动识别"
        if source == "手动编辑":
            continue
        module = _resolve_profile_module(observation.field, metadata)
        grouped.setdefault(module, [])
        grouped[module].append(
            {
                "id": observation.id,
                "field": observation.field,
                "title": observation.new_value or observation.field,
                "old_value": observation.old_value or None,
                "new_value": observation.new_value or None,
                "source": source,
                "evidence": metadata.get("evidence") or None,
                "confidence": round(_safe_float(metadata.get("confidence"), 0.0), 2),
                "change_type": metadata.get("change_type") or "新增",
                "status": observation.status,
                "category": metadata.get("category") or None,
                "trigger": metadata.get("trigger") or None,
                "example": metadata.get("example") or None,
                "created_at": observation.created_at.isoformat() if observation.created_at else "",
            }
        )
        total += 1
        if observation.status == "approved":
            approved += 1
        if observation.status == "pending":
            pending += 1
    for module in grouped:
        grouped[module].sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {
        "summary": {
            "total": total,
            "approved": approved,
            "pending": pending,
        },
        "groups": grouped,
    }


def _apply_character_profiles(db: Session, preview: dict[str, Any], resolved_chars: dict[str, Character]) -> int:
    profile_payload = preview.get("character_profiles") or {}
    total_changes = 0
    for original_name, char in resolved_chars.items():
        profile = profile_payload.get(original_name) or {}
        changed = False
        basic_info = profile.get("basic_info") or {}
        personality_model = profile.get("personality_model") or {}
        speaking_style = profile.get("speaking_style") or {}

        # 铁律：规则层弱推断只允许填空缺，永远不覆盖已有内容
        # （覆盖曾导致"每次导入都把好档案冲掉"——深化只能由证据融合层做）
        for field in ("role", "background"):
            new_value = (basic_info.get(field) or "").strip()
            old_value = (getattr(char, field, "") or "").strip()
            if new_value and not old_value:
                setattr(char, field, new_value)
                _create_change_observation(
                    db,
                    char.id,
                    field,
                    old_value,
                    new_value,
                    "导入文本",
                    f"{field} 已由导入档案补全",
                    0.78,
                    "基础信息",
                    "新增",
                )
                changed = True
                total_changes += 1

        new_tags = _normalize_tag_list(personality_model.get("tags"))
        merged_tags = list(char.personality_tags or [])
        for tag in new_tags:
            if tag and tag not in merged_tags:
                merged_tags.append(tag)
        if merged_tags != list(char.personality_tags or []):
            _create_change_observation(
                db,
                char.id,
                "personality_tags",
                list(char.personality_tags or []),
                merged_tags,
                "导入文本",
                f"识别出 {len(new_tags)} 个人格标签",
                0.81,
                "人格模型",
                _infer_change_type(char.personality_tags, merged_tags),
            )
            char.personality_tags = merged_tags[:10]
            changed = True
            total_changes += 1

        new_core_traits = {
            key: value
            for key, value in _normalize_core_traits(personality_model.get("core_traits")).items()
            if value is not None
        }
        merged_core_traits = dict(char.core_traits or {})
        for key, value in new_core_traits.items():
            merged_core_traits[key] = value
        if merged_core_traits != dict(char.core_traits or {}):
            _create_change_observation(
                db,
                char.id,
                "core_traits",
                dict(char.core_traits or {}),
                merged_core_traits,
                "导入文本",
                "导入文本补全了人格模型量化结构",
                0.74,
                "人格模型",
                _infer_change_type(char.core_traits, merged_core_traits),
            )
            char.core_traits = merged_core_traits
            changed = True
            total_changes += 1

        profile_fields = [
            ("motivation", profile.get("core_motivation"), "核心动机"),
            ("weakness", profile.get("core_weakness"), "核心弱点"),
            ("speaking_style", speaking_style.get("summary"), "说话风格"),
        ]
        for field, new_value, module in profile_fields:
            new_value = (new_value or "").strip()
            old_value = (getattr(char, field, "") or "").strip()
            # 同上：规则层只填空缺，不覆盖（如 speaking_style 的"简短/反问"标签拼接
            # 不能冲掉 AI 写的丰富描述）
            if new_value and not old_value:
                setattr(char, field, new_value)
                evidence = speaking_style.get("summary") if field == "speaking_style" else f"{module} 已由导入解析补全"
                _create_change_observation(
                    db,
                    char.id,
                    field,
                    old_value,
                    new_value,
                    "导入文本",
                    evidence,
                    0.77,
                    module,
                    "新增",
                )
                changed = True
                total_changes += 1

        for category, items in (profile.get("behavior_patterns") or {}).items():
            for item in items or []:
                label = (item.get("label") or "").strip()
                if not label:
                    continue
                if db.query(CharacterObservation).filter(
                    CharacterObservation.character_id == char.id,
                    CharacterObservation.field == "behavior_pattern",
                    CharacterObservation.new_value == label,
                ).first():
                    continue
                _create_change_observation(
                    db,
                    char.id,
                    "behavior_pattern",
                    "",
                    label,
                    item.get("source") or "导入文本",
                    item.get("evidence") or item.get("example") or "导入文本识别出的稳定行为模式",
                    _safe_float(item.get("confidence"), 0.8),
                    "行为模式",
                    "新增",
                    category=category,
                    trigger=item.get("trigger") or "",
                    example=item.get("example") or "",
                )
                changed = True
                total_changes += 1

        if changed:
            char.version += 1
            char.updated_at = datetime.utcnow()
            db.add(char)
            db.flush()
            graph_store.sync_character(char)
            supporting_evidence = [
                item.id for item in db.query(EvidenceSpan).filter(
                    EvidenceSpan.character_id == char.id,
                    EvidenceSpan.source_type.in_(["导入文本", "AI导入解析"]),
                ).order_by(EvidenceSpan.created_at.desc()).limit(20).all()
            ]
            _create_personality_snapshot(
                db,
                char,
                source="导入文本",
                supporting_evidence=supporting_evidence,
            )
    db.commit()
    return total_changes


async def _enhance_import_preview(import_file_id: int, filename: str, content_text: str) -> None:
    db = SessionLocal()
    try:
        import_file = db.get(ImportFile, import_file_id)
        if not import_file:
            return
        existing_characters = [
            {"id": char.id, "name": char.name, "role": char.role or "", "aliases": list(char.aliases or [])}
            for char in db.query(Character).all()
        ]
        import_logger.info("导入预览 AI 增强开始 import_file_id=%s filename=%s", import_file_id, filename)
        preview = await build_import_preview(filename, content_text, existing_characters, enable_ai=True)
        import_file.summary = (preview.get("plot_summary", {}) or {}).get("main_conflict", import_file.summary)
        warning_message = (preview.get("warning_message") or "").strip()
        progress_message = warning_message or "AI 预览增强完成"
        _update_import_status(
            db,
            import_file,
            "preview_ready",
            progress_message,
            preview_payload=preview,
            preview_warning=warning_message,
            role_count=len(preview.get("characters", [])),
            interaction_count=len(preview.get("interaction_units", [])),
            event_count=len(preview.get("events", [])),
            relationship_count=len(preview.get("relationships", [])),
        )
        if warning_message:
            import_logger.warning("导入预览 AI 增强降级 import_file_id=%s warning=%s", import_file_id, warning_message)
        else:
            import_logger.info("导入预览 AI 增强完成 import_file_id=%s", import_file_id)
    except Exception as exc:
        import_logger.exception("导入预览 AI 增强失败 import_file_id=%s error=%s", import_file_id, exc)
        import_file = db.get(ImportFile, import_file_id)
        if import_file:
            _update_import_status(
                db,
                import_file,
                "preview_ready",
                "AI 增强超时，已保留基础预览结果",
                preview_warning=str(exc),
            )
    finally:
        db.close()


def _compact_preview_for_review(preview: dict[str, Any], role_mappings: list[Any]) -> dict[str, Any]:
    return {
        "characters": (preview.get("characters") or [])[:20],
        "role_mappings": [
            {
                "original_name": getattr(item, "original_name", None) or item.get("original_name", ""),
                "resolved_name": getattr(item, "resolved_name", None) or item.get("resolved_name", ""),
                "status": getattr(item, "status", None) or item.get("status", "new"),
                "action": getattr(item, "action", None) or item.get("action", "create"),
            }
            for item in role_mappings[:20]
        ],
        "interaction_units": [
            {
                "source_line_index": item.get("source_line_index", index),
                "speaker": item.get("speaker", ""),
                "receiver": item.get("receiver", ""),
                "content": (item.get("content", "") or "")[:120],
                "intent": item.get("intent", {}),
                "strategy": item.get("strategy", {}),
                "emotion": item.get("emotion", {}),
            }
            for index, item in enumerate((preview.get("interaction_units") or [])[:24], start=1)
        ],
        "relationships": (preview.get("relationships") or [])[:12],
        "events": (preview.get("events") or [])[:12],
        "plot_summary": preview.get("plot_summary", {}) or {},
    }


async def _auto_review_import(preview: dict[str, Any], role_mappings: list[Any], import_file_id: int) -> tuple[dict[str, Any], list[Any], str]:
    review_payload = _compact_preview_for_review(preview, role_mappings)
    try:
        result = await orchestrator.call(
            "import_commit_review",
            {"review_payload": json.dumps(review_payload, ensure_ascii=False)},
            retries=1,
        )
    except Exception as exc:
        import_logger.warning("导入审核代理执行失败 import_file_id=%s error=%s", import_file_id, exc)
        return preview, role_mappings, ""
    if not isinstance(result, dict):
        return preview, role_mappings, ""
    reviewed_preview = dict(preview or {})
    reviewed_role_mappings = list(role_mappings or [])
    reviewed_mapping_lookup = {
        item.get("original_name", ""): item
        for item in (result.get("reviewed_role_mappings") or [])
        if isinstance(item, dict)
    }
    if reviewed_mapping_lookup:
        for item in reviewed_role_mappings:
            original_name = getattr(item, "original_name", None) or item.get("original_name", "")
            if original_name in reviewed_mapping_lookup:
                reviewed = reviewed_mapping_lookup[original_name]
                if hasattr(item, "resolved_name"):
                    item.resolved_name = reviewed.get("resolved_name", item.resolved_name)
                    item.action = reviewed.get("action", item.action)
                    item.status = reviewed.get("status", item.status)
                else:
                    item.update(
                        {
                            "resolved_name": reviewed.get("resolved_name", item.get("resolved_name", original_name)),
                            "action": reviewed.get("action", item.get("action", "create")),
                            "status": reviewed.get("status", item.get("status", "new")),
                        }
                    )
    if result.get("reviewed_relationships"):
        reviewed_preview["relationships"] = result["reviewed_relationships"]
    if result.get("reviewed_events"):
        reviewed_preview["events"] = result["reviewed_events"]
    if result.get("reviewed_plot_summary"):
        reviewed_preview["plot_summary"] = result["reviewed_plot_summary"]
    review_summary = (result.get("summary") or "").strip()
    if review_summary:
        reviewed_preview["review_summary"] = review_summary
    return reviewed_preview, reviewed_role_mappings, review_summary


def _dedupe_names(names: list[str]) -> list[str]:
    result = []
    seen = set()
    for name in names:
        name = (name or "").strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _event_title(event: dict[str, Any]) -> str:
    """事件标题优先用真实内容：摘要 > 主体+动作 > 兜底"""
    summary = (event.get("summary") or "").strip()
    if summary:
        return summary[:40]
    actor = (event.get("actor") or "").strip()
    action = (event.get("action") or "").strip()
    if actor and action:
        return f"{actor}{action}"[:40]
    return action[:40] or "导入事件"


def _build_timeline_event_drafts(preview: dict[str, Any]) -> list[dict[str, Any]]:
    preview_events = preview.get("events") or []
    drafts = []
    if preview_events:
        for index, event in enumerate(preview_events, start=1):
            actors = _dedupe_names([event.get("actor", "")] + list(event.get("participants") or []))
            if not actors:
                continue
            detail_parts = []
            if event.get("summary"):
                detail_parts.append(event["summary"])
            if event.get("action") and event.get("action") not in (event.get("summary") or ""):
                detail_parts.append(f"核心动作：{event['action']}")
            if event.get("time"):
                detail_parts.append(f"时间：{event['time']}")
            if event.get("location"):
                detail_parts.append(f"地点：{event['location']}")
            if len(actors) > 1:
                detail_parts.append(f"涉及：{'、'.join(actors[:6])}")
            drafts.append(
                {
                    "actors": actors,
                    "title": _event_title(event),
                    "description": "；".join(detail_parts)[:500],
                    "event_date": event.get("time", "") or "",
                    "emotion_label": (event.get("emotion_label") or "").strip(),
                    "importance": 4,
                    "source_indexes": [index],
                }
            )
    if drafts:
        return drafts

    # 无 AI 事件时：把交互单元按 4 条聚簇成阶段性事件
    units = preview.get("interaction_units") or []
    for start in range(0, len(units), 4):
        cluster = units[start:start + 4]
        if not cluster:
            continue
        actors = _dedupe_names(
            [item.get("speaker", "") for item in cluster] +
            [item.get("receiver", "") for item in cluster]
        )
        if not actors:
            continue
        detail_parts = []
        for item in cluster:
            speaker = item.get("speaker", "") or "某人"
            receiver = item.get("receiver", "") or "相关人物"
            action = (
                ((item.get("intent") or {}).get("value") or "").strip() or
                ((item.get("strategy") or {}).get("value") or "").strip() or
                "展开互动"
            )
            content = (item.get("content", "") or "").strip()
            detail_parts.append(f"{speaker}针对{receiver}{action}，核心内容为“{content[:60]}”")
        first_content = (cluster[0].get("content", "") or "").strip()
        drafts.append(
            {
                "actors": actors,
                "title": f"{actors[0]}：{first_content[:24]}…" if first_content else f"{actors[0]}与{'、'.join(actors[1:3]) or '他人'}的互动",
                "description": "；".join(detail_parts)[:500],
                "event_date": "",
                "emotion_label": ((cluster[-1].get("emotion") or {}).get("value") or "").strip(),
                "importance": min(5, 3 + (1 if len(cluster) >= 3 else 0)),
                "source_indexes": [int(item.get("source_line_index") or (start + offset + 1)) for offset, item in enumerate(cluster)],
            }
        )
    return drafts


def _create_import_events(db: Session, preview: dict[str, Any], resolved_chars: dict[str, Character], import_file_id: int) -> tuple[int, dict[tuple[str, int], int]]:
    created_events = 0
    source_event_map: dict[tuple[str, int], int] = {}
    created_records: list[tuple[Character, dict[str, Any]]] = []
    for draft in _build_timeline_event_drafts(preview):
        for actor_name in draft.get("actors", []):
            actor = resolved_chars.get(actor_name)
            if not actor:
                continue
            event = CharacterEvent(
                character_id=actor.id,
                title=draft.get("title", "导入事件"),
                description=draft.get("description", ""),
                event_date=draft.get("event_date", ""),
                emotion_label=draft.get("emotion_label", ""),
                importance=int(draft.get("importance", 3) or 3),
            )
            db.add(event)
            db.flush()
            db.refresh(event)
            graph_store.sync_event(event, actor)
            created_records.append((actor, draft))
            created_events += 1
            for source_index in draft.get("source_indexes", []):
                key = (actor.name, int(source_index))
                source_event_map.setdefault(key, event.id)
            _create_change_observation(
                db,
                actor.id,
                "event_timeline",
                "",
                draft.get("title", "导入事件"),
                "导入文本",
                draft.get("description", "")[:180] or "导入文本生成的事件总结",
                0.8,
                "事件时间线",
                "新增",
                example=draft.get("description", "")[:120],
            )
    db.commit()
    import_logger.info("导入事件创建完成 import_file_id=%s created_events=%s", import_file_id, created_events)
    return created_events, source_event_map


# 批量深度分析：每批连续句数 / 并发批数 / 单批超时
ANALYSIS_BATCH_SIZE = 8
ANALYSIS_BATCH_CONCURRENCY = 2
ANALYSIS_BATCH_TIMEOUT = 300.0


def _create_import_relationships(
    db: Session,
    preview: dict[str, Any],
    resolved_chars: dict[str, Character],
) -> tuple[int, dict[tuple[str, str], int]]:
    """
    把 AI 解析出的关系列表直接写入关系表（此前只靠 unit 循环弱推断，导致关系大量丢失）：
    - 新关系：按解析的类型/强度/极性/描述创建，并写入初始 history
    - 已有关系：EMA 演化强度与极性、追加 history、补全类型与描述
    返回 (新建数量, {(source_name, target_name): rel_id})
    """
    created = 0
    rel_id_map: dict[tuple[str, str], int] = {}
    now_iso = datetime.utcnow().isoformat()
    for item in preview.get("relationships") or []:
        source_name = (item.get("source") or "").strip()
        target_name = (item.get("target") or "").strip()
        source_char = resolved_chars.get(source_name)
        target_char = resolved_chars.get(target_name)
        if not source_char or not target_char or source_char.id == target_char.id:
            continue
        rel_type = (item.get("rel_type") or "neutral").strip() or "neutral"
        strength = max(0.0, min(1.0, _safe_float(item.get("strength"), 0.5)))
        sentiment = max(-1.0, min(1.0, _safe_float(item.get("sentiment"), 0.0)))
        description = (item.get("description") or "").strip()[:500]
        rel = find_pair_relationship(db, source_char.id, target_char.id)
        if rel:
            history = list(rel.history or [])
            history.append({"date": now_iso, "strength": rel.strength, "sentiment": rel.sentiment, "source": "import"})
            rel.history = history
            rel.strength = max(0.0, min(1.0, (rel.strength or 0.5) * 0.6 + strength * 0.4))
            rel.sentiment = max(-1.0, min(1.0, (rel.sentiment or 0.0) * 0.6 + sentiment * 0.4))
            if (rel.rel_type or "neutral") in ("neutral", "dynamic", "unknown", "") and rel_type != "neutral":
                rel.rel_type = rel_type
            if description and len(description) > len(rel.description or ""):
                rel.description = description
            rel.updated_at = datetime.utcnow()
            db.flush()
        else:
            rel = Relationship(
                source_id=source_char.id,
                target_id=target_char.id,
                rel_type=rel_type,
                strength=strength,
                sentiment=sentiment,
                description=description or "导入文本识别出的关系",
                history=[{"date": now_iso, "strength": strength, "sentiment": sentiment, "source": "import"}],
            )
            db.add(rel)
            db.flush()
            created += 1
            _create_change_observation(
                db,
                source_char.id,
                "relationship_network",
                "",
                f"{source_char.name} → {target_char.name}（{rel_type}）",
                "导入文本",
                description or "导入文本识别出的关系",
                max(0.6, min(0.95, strength or 0.6)),
                "关系网络",
                "新增",
                example=description[:120],
            )
        graph_store.sync_relationship(rel, source_char, target_char)
        rel_id_map[tuple(sorted((source_char.name, target_char.name)))] = rel.id
    db.commit()
    return created, rel_id_map


# persona_facts 类目 → 记忆类型映射
_FACT_MEMORY_TYPES = {
    "经历": "fact", "身份背景": "fact", "技能": "fact", "健康": "fact", "价值观": "fact",
    "习惯": "pragmatics", "语言风格": "pragmatics", "人际模式": "pragmatics",
    "恐惧": "emotion", "欲望": "emotion", "心理特征": "diagnosis",
}


def _persist_persona_facts(
    db: Session,
    preview: dict[str, Any],
    resolved_chars: dict[str, Character],
    import_file_id: int,
) -> tuple[int, dict[str, list[int]]]:
    """
    人物事实落库：每条事实 → 证据片段 + 长期记忆。
    这是资料型导入（简历/自述/日记）的主要产出通道。
    返回 (落库条数, {角色名: [evidence_id]})。
    """
    created = 0
    evidence_by_char: dict[str, list[int]] = {}
    for fact in preview.get("persona_facts") or []:
        subject = (fact.get("subject") or "").strip()
        char = resolved_chars.get(subject)
        if not char:
            continue
        content = (fact.get("content") or "").strip()
        if not content:
            continue
        category = (fact.get("category") or "心理特征").strip()
        evidence = _create_evidence_span(
            db,
            character_id=char.id,
            source_type="import",
            source_id=import_file_id,
            import_file_id=import_file_id,
            supports_type="persona_fact",
            quote=(fact.get("quote") or content)[:500],
            interpretation=f"{category}：{content}",
            confidence=_safe_float(fact.get("confidence"), 0.6),
            metadata={"category": category, "time_hint": fact.get("time_hint") or ""},
        )
        _create_memory_item(
            db,
            character_id=char.id,
            memory_type=_FACT_MEMORY_TYPES.get(category, "fact"),
            content=f"[{category}] {content}",
            confidence=_safe_float(fact.get("confidence"), 0.6),
            source="导入事实",
            evidence_ids=[evidence.id],
        )
        evidence_by_char.setdefault(subject, []).append(evidence.id)
        created += 1
    db.commit()
    if created:
        import_logger.info("人物事实落库完成 import_file_id=%s facts=%s", import_file_id, created)
    return created, evidence_by_char


# 关系深析：每次导入最多分析的关系对数 / 并发
RELATIONSHIP_DEEP_LIMIT = 10
RELATIONSHIP_DEEP_CONCURRENCY = 2


async def _run_relationship_deep_analyses(
    db: Session,
    preview: dict[str, Any],
    resolved_chars: dict[str, Character],
    rel_id_map: dict[tuple[str, str], int],
) -> int:
    """
    关系深度分析（自动，无需手动按钮）：
    对每对有关系记录的人物输出权力结构/互动模式/认知差/张力/演化叙事，
    写入 Relationship.analysis_json，trajectory 同时充实 description。
    """
    if not rel_id_map:
        return 0
    all_units = preview.get("interaction_units") or []
    semaphore = asyncio.Semaphore(RELATIONSHIP_DEEP_CONCURRENCY)
    analyzed = 0

    async def _analyze_pair(pair: tuple[str, str], rel_id: int) -> dict | None:
        name_a, name_b = pair
        char_a, char_b = resolved_chars.get(name_a), resolved_chars.get(name_b)
        if not char_a or not char_b:
            return None
        samples = []
        for unit in all_units:
            speaker = (unit.get("speaker") or "").strip()
            receiver = (unit.get("receiver") or "").strip()
            if {speaker, receiver} == {name_a, name_b}:
                samples.append(f"{speaker} → {receiver}：「{(unit.get('content') or '').strip()[:100]}」")
        # 事实型证据补充（无对话的资料导入也能分析关系）
        for fact in (preview.get("persona_facts") or [])[:40]:
            if (fact.get("subject") or "").strip() in pair and (fact.get("category") or "") == "人际模式":
                samples.append(f"[事实] {fact.get('subject')}：{(fact.get('content') or '')[:80]}")
        if len(samples) > 12:
            step = len(samples) / 12
            samples = [samples[int(i * step)] for i in range(12)]
        rel = db.get(Relationship, rel_id)
        pair_profiles = json.dumps(
            [_build_snapshot_payload(char_a), _build_snapshot_payload(char_b)], ensure_ascii=False,
        )
        existing = json.dumps({
            "rel_type": rel.rel_type, "strength": rel.strength,
            "sentiment": rel.sentiment, "description": (rel.description or "")[:200],
        }, ensure_ascii=False) if rel else ""
        try:
            async with semaphore:
                result = await orchestrator.analyze_relationship_deep(
                    pair_profiles, "\n".join(samples), existing,
                )
            return {"rel_id": rel_id, "result": result}
        except Exception as exc:
            import_logger.warning("关系深析失败 pair=%s error=%s", pair, exc)
            return None

    pairs = list(rel_id_map.items())[:RELATIONSHIP_DEEP_LIMIT]
    outcomes = await asyncio.gather(*(_analyze_pair(pair, rel_id) for pair, rel_id in pairs))
    for outcome in outcomes:
        if not outcome or not isinstance(outcome.get("result"), dict):
            continue
        result = outcome["result"]
        rel = db.get(Relationship, outcome["rel_id"])
        if not rel:
            continue
        rel.analysis_json = {
            "power_dynamic": (result.get("power_dynamic") or "")[:120],
            "interaction_pattern": (result.get("interaction_pattern") or "")[:120],
            "perception_gap": (result.get("perception_gap") or "")[:160],
            "tensions": [str(t)[:80] for t in (result.get("tensions") or [])[:5]],
            "trajectory": (result.get("trajectory") or "")[:300],
            "evidence_notes": (result.get("evidence_notes") or "")[:160],
            "updated_at": datetime.utcnow().isoformat(),
        }
        trajectory = (result.get("trajectory") or "").strip()
        if trajectory and len(trajectory) > len(rel.description or ""):
            rel.description = trajectory[:500]
        rel.updated_at = datetime.utcnow()
        analyzed += 1
    db.commit()
    if analyzed:
        import_logger.info("关系深析完成 analyzed=%s", analyzed)
    return analyzed


_ANALYSIS_ITEM_FIELDS = ("inner_monologue", "emotion_attribution", "strategy_explanation", "behavior_tendency", "analysis_tags")


async def _rebuild_import_analyses(
    preview: dict[str, Any],
    resolved_chars: dict[str, Character],
    concurrency: int = ANALYSIS_BATCH_CONCURRENCY,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """
    批量深度分析（每句全覆盖，无预算上限）：
    - 连续 ANALYSIS_BATCH_SIZE 句为一批，一次 LLM 调用输出整批分析
    - 每批携带全部涉及角色的完整档案 + 关系 + 剧情提要，整段上下文让分析连贯且具体
    - 单批失败只影响该批（前端可对单句手动补全），不阻塞导入
    """
    all_units = preview.get("interaction_units", []) or []
    target_indexes = [
        index for index, unit in enumerate(all_units, start=1)
        if _should_run_import_analysis(unit) and (unit.get("speaker") or "").strip() in resolved_chars
    ]
    if not target_indexes:
        return {}, []

    # 涉及角色的完整档案块（让分析"结合角色的所有信息"）
    involved_names: set[str] = set()
    for index in target_indexes:
        unit = all_units[index - 1]
        for name in ((unit.get("speaker") or "").strip(), (unit.get("receiver") or "").strip()):
            if name in resolved_chars:
                involved_names.add(name)
    profiles_block = json.dumps(
        [_build_snapshot_payload(resolved_chars[name]) for name in sorted(involved_names)],
        ensure_ascii=False,
    )
    relationships_block = json.dumps(
        [
            {
                "source": item.get("source"), "target": item.get("target"),
                "rel_type": item.get("rel_type"), "strength": item.get("strength"),
                "sentiment": item.get("sentiment"), "description": (item.get("description") or "")[:120],
            }
            for item in (preview.get("relationships") or [])[:20]
        ],
        ensure_ascii=False,
    )
    plot = preview.get("plot_summary") or {}
    summary_block = "；".join(filter(None, [plot.get("main_conflict"), plot.get("relationship_path")]))

    def _dialogue_line(index: int) -> str:
        unit = all_units[index - 1]
        speaker = (unit.get("speaker") or "").strip() or "？"
        receiver = (unit.get("receiver") or "").strip() or "？"
        content = (unit.get("content") or "").strip()[:160]
        return f"{index}. {speaker} → {receiver}：「{content}」"

    batches = [target_indexes[i:i + ANALYSIS_BATCH_SIZE] for i in range(0, len(target_indexes), ANALYSIS_BATCH_SIZE)]
    semaphore = asyncio.Semaphore(max(1, concurrency))
    analyses: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    async def _analyze_batch(batch_indexes: list[int]) -> None:
        # 批首之前的 2 句作为衔接前文（标注不需分析）
        lead_in = ""
        first = batch_indexes[0]
        if first > 1:
            prev_lines = [_dialogue_line(i) for i in range(max(1, first - 2), first)]
            lead_in = "（前文，仅供理解，无需分析）\n" + "\n".join(prev_lines) + "\n\n"
        dialogue_block = lead_in + "\n".join(_dialogue_line(i) for i in batch_indexes)
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    orchestrator.analyze_interaction_batch(
                        profiles_block, relationships_block, summary_block,
                        dialogue_block, len(batch_indexes),
                    ),
                    timeout=ANALYSIS_BATCH_TIMEOUT,
                )
        except asyncio.TimeoutError:
            failures.append({"index": batch_indexes[0], "error": f"批量分析超时（{batch_indexes[0]}-{batch_indexes[-1]} 句）"})
            return
        except Exception as exc:
            failures.append({"index": batch_indexes[0], "error": f"批量分析失败（{batch_indexes[0]}-{batch_indexes[-1]} 句）：{str(exc)[:120]}"})
            return
        returned = result.get("analyses") if isinstance(result, dict) else None
        if not isinstance(returned, list):
            failures.append({"index": batch_indexes[0], "error": "批量分析返回格式异常"})
            return
        batch_set = set(batch_indexes)
        for pos, item in enumerate(returned):
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = None
            # AI 偶尔会用批内局部编号，按位置回退映射
            if idx not in batch_set:
                idx = batch_indexes[pos] if pos < len(batch_indexes) else None
            if idx is None:
                continue
            analyses[idx] = {key: item.get(key, "") for key in _ANALYSIS_ITEM_FIELDS}

    await asyncio.gather(*(_analyze_batch(batch) for batch in batches))
    import_logger.info(
        "批量分析完成 total=%s analyzed=%s failed_batches=%s",
        len(target_indexes), len(analyses), len(failures),
    )
    return analyses, failures


# 数据治理：同一字段保留的 approved 历史记录条数 / 每类记忆保留的活跃条数
OBSERVATION_KEEP_PER_FIELD = 5
MEMORY_KEEP_PER_TYPE = 60
_COMPACTABLE_FIELDS = {"role", "background", "motivation", "weakness", "speaking_style", "personality_tags", "core_traits"}


def _compact_character_data(db: Session, char_ids: list[int]) -> dict[str, int]:
    """
    自动压缩：防止多次导入后 observation / memory 无限堆积。
    - 档案字段的 approved 变更记录：每字段保留最近 N 条，更早的标记 archived（可追溯，不删除）
    - 记忆条目：每类型保留最新 N 条活跃，超出部分按置信度低者优先标记 deprecated
    行为模式 / 事件 / 关系类记录是内容实体，不参与压缩。
    """
    stats = {"observations_archived": 0, "memories_deprecated": 0}
    for char_id in char_ids:
        for field in _COMPACTABLE_FIELDS:
            rows = db.query(CharacterObservation).filter(
                CharacterObservation.character_id == char_id,
                CharacterObservation.field == field,
                CharacterObservation.status == "approved",
            ).order_by(CharacterObservation.created_at.desc(), CharacterObservation.id.desc()).all()
            for row in rows[OBSERVATION_KEEP_PER_FIELD:]:
                row.status = "archived"
                stats["observations_archived"] += 1

        memory_types = [row[0] for row in db.query(MemoryItem.memory_type).filter(
            MemoryItem.character_id == char_id,
            MemoryItem.status == "active",
        ).distinct().all()]
        for memory_type in memory_types:
            rows = db.query(MemoryItem).filter(
                MemoryItem.character_id == char_id,
                MemoryItem.memory_type == memory_type,
                MemoryItem.status == "active",
            ).order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).all()
            overflow = rows[MEMORY_KEEP_PER_TYPE:]
            overflow.sort(key=lambda item: float(item.confidence or 0.0))
            for row in overflow:
                row.status = "deprecated"
                row.updated_at = datetime.utcnow()
                stats["memories_deprecated"] += 1
    if stats["observations_archived"] or stats["memories_deprecated"]:
        db.commit()
        import_logger.info("数据压缩完成 char_ids=%s stats=%s", char_ids, stats)
    return stats


@router.post("/maintenance/compact")
def compact_all_characters(db: Session = Depends(get_db)):
    """手动触发全库数据压缩（导入完成后也会对涉及角色自动执行）"""
    char_ids = [row[0] for row in db.query(Character.id).all()]
    stats = _compact_character_data(db, char_ids)
    return {"ok": True, "characters": len(char_ids), **stats}


def _cleanup_legacy_import_artifacts(db: Session, resolved_chars: dict[str, Character]) -> None:
    char_ids = [char.id for char in resolved_chars.values()]
    if not char_ids:
        return
    legacy_events = db.query(CharacterEvent).filter(
        CharacterEvent.character_id.in_(char_ids),
        CharacterEvent.title.like("导入事件 #%"),
    ).all()
    for event in legacy_events:
        db.delete(event)

    legacy_observations = db.query(CharacterObservation).filter(
        CharacterObservation.character_id.in_(char_ids),
        CharacterObservation.field == "behavior_pattern",
        CharacterObservation.status == "pending",
    ).all()
    for observation in legacy_observations:
        observation.status = "approved"
        observation.reviewed_at = datetime.utcnow()

    db.commit()
    import_logger.info(
        "清理旧导入遗留数据 char_ids=%s legacy_events=%s legacy_observations=%s",
        char_ids,
        len(legacy_events),
        len(legacy_observations),
    )


# 导入提交串行化：并发导入会对同一角色交错融合档案，强制排队执行
_IMPORT_COMMIT_LOCK = asyncio.Lock()


async def _process_import_commit(import_file_id: int, payload: dict[str, Any]) -> None:
    async with _IMPORT_COMMIT_LOCK:
        await _process_import_commit_inner(import_file_id, payload)


async def _process_import_commit_inner(import_file_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    agent_run = None
    try:
        body = ImportCommitRequest.model_validate(payload)
        import_file = db.get(ImportFile, import_file_id)
        if not import_file:
            return
        agent_run = AgentRun(
            workflow_name="import_commit",
            input_hash=f"import:{import_file_id}:{import_file.version}",
            status="running",
            model_used=import_file.model_used or "ai-harness",
            trace_json={
                "filename": import_file.filename,
                "stage": "start",
            },
        )
        db.add(agent_run)
        db.commit()
        preview = dict(body.preview_payload or {})
        role_mappings = list(body.role_mappings or [])

        import_logger.info("导入任务开始 import_file_id=%s filename=%s", import_file.id, body.filename)
        _update_import_status(db, import_file, "reviewing", "AI 审核代理正在自动审核导入结果…")
        preview, role_mappings, review_summary = await _auto_review_import(preview, role_mappings, import_file.id)

        resolved_chars = {}
        parsed_characters = {item.get("name"): item for item in preview.get("characters", []) if item.get("name")}
        for original_name, parsed_char in parsed_characters.items():
            mapping = _resolve_mapping(role_mappings, original_name)
            if mapping["action"] == "skip":
                continue
            char, _created = _ensure_character_from_mapping(db, mapping, parsed_char)
            resolved_chars[original_name] = char
        # 注意：AI 画像生成移到 units/events/relationships 写入之后，
        # 那时才有完整的台词证据，避免"凭名字脑补"的泛泛档案

        conversation = None
        if body.create_readonly_conversation:
            conversation = Conversation(
                title=f"只读导入 · {body.filename}",
                scenario=body.scenario,
                self_name=(body.self_name or "").strip()[:100],
                is_readonly=True,
                source_import_file_id=import_file.id,
            )
            db.add(conversation)
            db.flush()
            db.refresh(conversation)

        _cleanup_legacy_import_artifacts(db, resolved_chars)
        _update_import_status(
            db,
            import_file,
            "processing",
            "后台正在写入角色、事件、关系与分析层，请稍候…",
            review_summary=review_summary,
        )
        profile_change_count = _apply_character_profiles(db, preview, resolved_chars)
        created_events, source_event_map = _create_import_events(db, preview, resolved_chars, import_file.id)
        # AI 解析的关系列表直接入库（类型/强度/极性/描述/history 完整保留）
        created_relationships, rel_id_map = _create_import_relationships(db, preview, resolved_chars)
        # 人物事实落库（资料型导入的主要产出；对话型导入的补充证据）
        created_facts, fact_evidence_by_char = _persist_persona_facts(db, preview, resolved_chars, import_file.id)

        committed_units = 0
        failures = {"characters": [], "events": [], "relationships": [], "analysis": []}
        preview_messages = ((preview.get("pseudo_conversation", {}) or {}).get("messages", []))
        _update_import_status(db, import_file, "processing", "正在对每句对话做深度分析（批量）…")
        analysis_map, analysis_failures = await _rebuild_import_analyses(preview, resolved_chars)
        failures["analysis"].extend(analysis_failures)
        next_message_index = 1

        for index, unit in enumerate(preview.get("interaction_units", []), start=1):
            try:
                speaker_name = unit.get("speaker", "").strip()
                if not speaker_name or speaker_name not in resolved_chars:
                    continue
                speaker_char = resolved_chars[speaker_name]
                receiver_name = unit.get("receiver", "").strip()
                resolved_receiver = resolved_chars.get(receiver_name) if receiver_name in resolved_chars else None
                # 批量分析全覆盖；个别批失败的单元无分析层，不影响单元本身入库（可手动补全）
                analysis = analysis_map.get(index) or {}
                if not isinstance(analysis, dict):
                    analysis = {}
                has_analysis = bool(analysis.get("inner_monologue") or analysis.get("emotion_attribution"))
                message_id = None
                analysis_message_id = None
                message_step = (2 if has_analysis else 1) if conversation else 0
                created_relationship = False
                with db.begin_nested():
                    message_index = next_message_index
                    if conversation:
                        msg = Message(
                            conversation_id=conversation.id,
                            role="user",
                            message_index=message_index,
                            character_id=speaker_char.id,
                            character_name=speaker_char.name,
                            receiver_id=resolved_receiver.id if resolved_receiver else None,
                            receiver_name=resolved_receiver.name if resolved_receiver else receiver_name,
                            content=unit.get("content", ""),
                            intent=(unit.get("intent") or {}).get("value", ""),
                            strategy=(unit.get("strategy") or {}).get("value", ""),
                            emotion=(unit.get("emotion") or {}).get("value", ""),
                            source_type="import",
                            readonly=True,
                        )
                        db.add(msg)
                        db.flush()
                        message_id = msg.id

                        if has_analysis:
                            analysis_msg = Message(
                                conversation_id=conversation.id,
                                role="assistant",
                                message_index=message_index + 1,
                                character_name="AI分析",
                                receiver_id=resolved_receiver.id if resolved_receiver else None,
                                receiver_name=resolved_receiver.name if resolved_receiver else receiver_name,
                                content=analysis.get("behavior_tendency", "") or analysis.get("inner_monologue", ""),
                                intent=(unit.get("intent") or {}).get("value", ""),
                                strategy=(unit.get("strategy") or {}).get("value", ""),
                                emotion=(unit.get("emotion") or {}).get("value", ""),
                                inner_monologue=analysis.get("inner_monologue"),
                                emotion_label=analysis.get("emotion_attribution"),
                                emotion_score=0.6,
                                subtext=analysis.get("strategy_explanation"),
                                psychological_tag=analysis.get("analysis_tags"),
                                source_type="import_analysis",
                                readonly=True,
                                parent_id=msg.id,
                            )
                            db.add(analysis_msg)
                            db.flush()
                            analysis_message_id = analysis_msg.id

                    relationship_id = None
                    if resolved_receiver and _should_run_import_analysis(unit):
                        pair_key = tuple(sorted((speaker_char.name, resolved_receiver.name)))
                        relationship_id = rel_id_map.get(pair_key)
                        if relationship_id is None:
                            # AI 关系列表未覆盖的说话对，按交互信号弱推断兜底
                            intent_conf = _safe_float((unit.get("intent") or {}).get("confidence"), 0.5)
                            sentiment = _safe_float((unit.get("emotion") or {}).get("confidence"), 0.5) * 2 - 1
                            interaction_type = (unit.get("interaction_type") or {}).get("value", "")
                            rel = find_pair_relationship(db, speaker_char.id, resolved_receiver.id)
                            if not rel:
                                rel = Relationship(
                                    source_id=speaker_char.id,
                                    target_id=resolved_receiver.id,
                                    rel_type=_infer_rel_type(sentiment, interaction_type),
                                    strength=max(0.2, min(1.0, intent_conf)),
                                    sentiment=max(-1.0, min(1.0, sentiment)),
                                    description=(unit.get("psychological_label", "") or "导入对话推断出的互动关系")[:500],
                                    history=[{
                                        "date": datetime.utcnow().isoformat(),
                                        "strength": max(0.2, min(1.0, intent_conf)),
                                        "sentiment": max(-1.0, min(1.0, sentiment)),
                                        "source": "import",
                                    }],
                                )
                                db.add(rel)
                                db.flush()
                                graph_store.sync_relationship(rel, speaker_char, resolved_receiver)
                                created_relationship = True
                                _create_change_observation(
                                    db,
                                    speaker_char.id,
                                    "relationship_network",
                                    "",
                                    f"{speaker_char.name} → {resolved_receiver.name}（{rel.rel_type}）",
                                    "导入文本",
                                    unit.get("psychological_label", "") or "导入对话推断出的互动关系",
                                    max(0.6, min(0.95, intent_conf)),
                                    "关系网络",
                                    "新增",
                                    example=(unit.get("content", "") or "")[:120],
                                )
                            rel_id_map[pair_key] = rel.id
                            relationship_id = rel.id

                    source_line_index = int(unit.get("source_line_index", index) or index)
                    event_id = source_event_map.get((speaker_char.name, source_line_index))

                    iu = InteractionUnit(
                        import_file_id=import_file.id,
                        source_line_index=source_line_index,
                        source_text_snippet=unit.get("content", "")[:500],
                        speaker=speaker_char.name,
                        receiver=resolved_receiver.name if resolved_receiver else receiver_name,
                        receiver_confidence=_safe_float(unit.get("receiver_confidence"), 0.0),
                        receiver_state=unit.get("receiver_state", "inferred"),
                        content=unit.get("content", ""),
                        intent=(unit.get("intent") or {}).get("value", ""),
                        intent_confidence=_safe_float((unit.get("intent") or {}).get("confidence"), 0.0),
                        intent_state=(unit.get("intent") or {}).get("state", "inferred"),
                        strategy=(unit.get("strategy") or {}).get("value", ""),
                        strategy_confidence=_safe_float((unit.get("strategy") or {}).get("confidence"), 0.0),
                        strategy_state=(unit.get("strategy") or {}).get("state", "inferred"),
                        emotion=(unit.get("emotion") or {}).get("value", ""),
                        emotion_confidence=_safe_float((unit.get("emotion") or {}).get("confidence"), 0.0),
                        emotion_state=(unit.get("emotion") or {}).get("state", "inferred"),
                        interaction_type=(unit.get("interaction_type") or {}).get("value", ""),
                        interaction_confidence=_safe_float((unit.get("interaction_type") or {}).get("confidence"), 0.0),
                        interaction_state=(unit.get("interaction_type") or {}).get("state", "inferred"),
                        psychological_label=unit.get("psychological_label", ""),
                        context_window=(preview_messages[max(0, index - 1):index] or [{}])[0].get("context_window", []),
                        analysis=analysis,
                        event_payload=preview.get("events", []),
                        relationship_payload=preview.get("relationships", []),
                        conversation_message_id=message_id or analysis_message_id,
                        character_event_id=event_id,
                        relationship_id=relationship_id,
                    )
                    db.add(iu)
                    db.flush()
                    quote = unit.get("content", "") or unit.get("psychological_label", "")
                    evidence = _create_evidence_span(
                        db,
                        character_id=speaker_char.id,
                        source_type="import",
                        source_id=import_file.id,
                        conversation_id=conversation.id if conversation else None,
                        message_id=message_id,
                        import_file_id=import_file.id,
                        interaction_unit_id=iu.id,
                        character_event_id=event_id,
                        relationship_id=relationship_id,
                        supports_type="interaction",
                        supports_id=iu.id,
                        quote=quote,
                        interpretation=unit.get("psychological_label", "") or analysis.get("strategy_explanation", ""),
                        confidence=max(
                            _safe_float(unit.get("receiver_confidence"), 0.0),
                            _safe_float((unit.get("intent") or {}).get("confidence"), 0.0),
                            _safe_float((unit.get("strategy") or {}).get("confidence"), 0.0),
                            _safe_float((unit.get("emotion") or {}).get("confidence"), 0.0),
                        ),
                        metadata={
                            "source_line_index": source_line_index,
                            "receiver": receiver_name,
                            "analysis": analysis,
                            "analysis_mode": _unit_analysis_mode(unit),
                        },
                    )
                    fact_memory = _build_import_fact_memory(unit)
                    if fact_memory:
                        _create_memory_item(
                            db,
                            character_id=speaker_char.id,
                            memory_type="fact",
                            content=fact_memory,
                            confidence=max(0.55, evidence.confidence),
                            source="导入文本",
                            evidence_ids=[evidence.id],
                        )
                    for memory_type, field_name in [
                        ("pragmatics", "strategy"),
                        ("emotion", "emotion"),
                    ]:
                        payload_value = unit.get(field_name) or {}
                        value = (payload_value.get("value") or "").strip()
                        if _is_useful_import_memory(value):
                            _create_memory_item(
                                db,
                                character_id=speaker_char.id,
                                memory_type=memory_type,
                                content=value,
                                confidence=_safe_float(payload_value.get("confidence"), evidence.confidence),
                                source="导入文本",
                                evidence_ids=[evidence.id],
                            )
                committed_units += 1
                if created_relationship:
                    created_relationships += 1
                next_message_index += message_step
            except Exception as exc:
                failures["analysis"].append({"index": index, "error": str(exc)})
                import_logger.exception("导入交互写入失败 import_file_id=%s index=%s", import_file.id, index)

        db.commit()

        # 全部台词/事实/事件/关系落库后，自动深度分析管线（无需任何手动按钮）：
        # ① 人物综合画像（扩展八维度 + 弧光转折） ② 关系深析（权力/模式/认知差/演化） ③ 特质假设轮
        _update_import_status(db, import_file, "processing", "正在基于全部证据生成立体人物档案…")
        profile_status_map: dict[str, str] = {}
        try:
            enriched_count, profile_status_map = await _enrich_import_profiles(db, preview, resolved_chars)
            profile_change_count += enriched_count
        except Exception as exc:
            import_logger.warning("导入画像批量生成失败 import_file_id=%s error=%s", import_file.id, exc)

        _update_import_status(db, import_file, "processing", "正在做关系深度分析（权力结构/互动模式/认知差）…")
        deep_relationship_count = 0
        try:
            deep_relationship_count = await _run_relationship_deep_analyses(db, preview, resolved_chars, rel_id_map)
        except Exception as exc:
            import_logger.warning("关系深析阶段失败 import_file_id=%s error=%s", import_file.id, exc)

        _update_import_status(db, import_file, "processing", "正在演化特质假设（验证/反驳/新猜想）…")
        hypothesis_stats = {"new": 0, "confirmed": 0, "supported": 0, "contradicted": 0, "rejected": 0}
        try:
            for original_name, char in list(resolved_chars.items())[:8]:
                lines, event_samples, _rels, _hints = _collect_character_evidence(preview, original_name)
                evidence_texts = lines + event_samples
                if not evidence_texts:
                    continue
                round_stats = await run_hypothesis_round(
                    db, char, evidence_texts,
                    evidence_ids=fact_evidence_by_char.get(original_name, []),
                )
                for key in hypothesis_stats:
                    hypothesis_stats[key] += round_stats.get(key, 0)
        except Exception as exc:
            import_logger.warning("假设轮阶段失败 import_file_id=%s error=%s", import_file.id, exc)

        import_file.summary = (preview.get("plot_summary", {}) or {}).get("main_conflict", import_file.summary)
        if agent_run:
            agent_run.status = "completed"
            agent_run.trace_json = {
                **(agent_run.trace_json or {}),
                "stage": "completed",
                "committed_units": committed_units,
                "created_events": created_events,
                "created_relationships": created_relationships,
                "profile_changes": profile_change_count,
                "failures": failures,
            }
            agent_run.updated_at = datetime.utcnow()
        _update_import_status(
            db,
            import_file,
            "committed",
            "导入完成",
            result={
                "conversation_id": conversation.id if conversation else None,
                "created_characters": [char.name for char in resolved_chars.values()],
                "interaction_units": committed_units,
                "events": created_events,
                "relationships": created_relationships,
                "persona_facts": created_facts,
                "deep_relationships": deep_relationship_count,
                "hypotheses": hypothesis_stats,
                "profile_changes": profile_change_count,
                "profile_status": profile_status_map,
                "failures": failures,
                "plot_summary": preview.get("plot_summary", {}),
            },
            role_count=len(resolved_chars),
            interaction_count=committed_units,
            event_count=created_events,
            relationship_count=created_relationships,
            profile_change_count=profile_change_count,
            failures=failures,
            plot_summary=preview.get("plot_summary", {}),
            pseudo_conversation=preview.get("pseudo_conversation", {}),
            character_profiles=preview.get("character_profiles", {}),
            completed_at=datetime.utcnow().isoformat(),
        )
        # 自动数据治理：压缩本次涉及角色的陈旧变更记录与超额记忆
        try:
            _compact_character_data(db, [char.id for char in resolved_chars.values()])
        except Exception as exc:
            import_logger.warning("导入后数据压缩失败 import_file_id=%s error=%s", import_file.id, exc)
        import_logger.info(
            "导入任务完成 import_file_id=%s chars=%s units=%s events=%s rels=%s",
            import_file.id,
            len(resolved_chars),
            committed_units,
            created_events,
            created_relationships,
        )
    except Exception as exc:
        import_logger.exception("导入任务失败 import_file_id=%s error=%s", import_file_id, exc)
        db.rollback()
        if agent_run:
            try:
                agent_run.status = "failed"
                agent_run.trace_json = {**(agent_run.trace_json or {}), "stage": "failed", "error": str(exc)}
                agent_run.updated_at = datetime.utcnow()
                db.add(agent_run)
                db.commit()
            except Exception:
                db.rollback()
        import_file = db.get(ImportFile, import_file_id)
        if import_file:
            _update_import_status(
                db,
                import_file,
                "failed",
                f"导入失败：{exc}",
                failures={"task": [{"error": str(exc)}]},
                completed_at=datetime.utcnow().isoformat(),
            )
    finally:
        db.close()


# ─── Characters CRUD ──────────────────────────────────────────────────────────

@router.get("/", response_model=list[CharacterOut])
def list_characters(db: Session = Depends(get_db)):
    return db.query(Character).order_by(Character.name).all()


@router.post("/", response_model=CharacterOut)
async def create_character(body: CharacterCreate, db: Session = Depends(get_db)):
    payload = body.model_dump()
    core_traits = payload.pop("core_traits", None) or {}
    char = Character(**payload)
    char.core_traits = {
        key: round(max(0.0, min(1.0, float(value))), 2)
        for key, value in core_traits.items()
        if key in BIG_FIVE_KEYS and isinstance(value, (int, float))
    }
    db.add(char)
    db.commit()
    db.refresh(char)
    graph_store.sync_character(char)
    # 自动生成 AI 心理档案（统一走档案应用入口：空缺补全、与手填冲突进待审核）
    try:
        profile = await orchestrator.generate_character_profile(
            char.name, char.role, char.background
        )
        if isinstance(profile, dict):
            changed = _apply_profile_candidate(
                db, char, profile,
                source="角色创建",
                evidence_note="AI 根据初始角色信息生成的候选画像；已保留用户手填内容。",
                base_confidence=0.7,
                merge_mode=False,
            )
            db.commit()
            db.refresh(char)
            if changed:
                supporting_evidence = [
                    item.id for item in db.query(EvidenceSpan).filter(
                        EvidenceSpan.character_id == char.id,
                    ).order_by(EvidenceSpan.created_at.desc()).limit(20).all()
                ]
                _create_personality_snapshot(db, char, source="角色创建", supporting_evidence=supporting_evidence)
                db.commit()
                db.refresh(char)
                graph_store.sync_character(char)
    except Exception:
        db.rollback()  # AI 分析失败不影响创建
    return char


@router.get("/{char_id}", response_model=CharacterOut)
def get_character(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    return char


@router.get("/{char_id}/profile-view")
def get_character_profile_view(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    relationships = db.query(Relationship).filter(
        (Relationship.source_id == char_id) | (Relationship.target_id == char_id)
    ).all()
    events = db.query(CharacterEvent).filter_by(character_id=char_id).order_by(
        CharacterEvent.event_date.desc(),
        CharacterEvent.created_at.desc(),
    ).all()
    observations = db.query(CharacterObservation).filter_by(character_id=char_id).order_by(
        CharacterObservation.created_at.desc()
    ).all()
    result = _build_profile_view(char, relationships, events, observations)
    # 完整度只算真实观察（手填/导入落库的），派生项不计入，避免虚高
    behavior_count = sum(len(items) for items in (result.get("behavior_patterns") or {}).values())
    result["completeness"] = profile_completeness(
        char,
        behavior_pattern_count=behavior_count,
        relationship_count=len(relationships),
        event_count=len(events),
    )
    # 方向2：行为模式从人际模式 + 互动 strategy 派生补充（只读展示），让各种来源的角色都不再空白
    strategy_units = [{"strategy": u.strategy, "content": u.content} for u in _character_interaction_units(db, char)]
    derived_groups = _derive_behavior_patterns(char.profile_json or {}, strategy_units)
    existing_labels = {
        _norm_label(item.get("label"))
        for items in (result.get("behavior_patterns") or {}).values()
        for item in items
    }
    for category, items in derived_groups.items():
        bucket = result["behavior_patterns"].setdefault(category, [])
        for item in items:
            if _norm_label(item.get("label")) not in existing_labels:
                bucket.append(item)
                existing_labels.add(_norm_label(item.get("label")))
    # 扩展人物模型（八维度）与进行中的特质假设
    result["extended_profile"] = char.profile_json or {}
    active_hypotheses = db.query(TraitHypothesis).filter(
        TraitHypothesis.character_id == char_id,
        TraitHypothesis.status == "active",
    ).order_by(TraitHypothesis.confidence.desc()).limit(12).all()
    result["hypotheses"] = [
        {
            "id": h.id,
            "hypothesis": h.hypothesis,
            "dimension": h.dimension,
            "confidence": round(h.confidence, 2),
            "supporting_count": len(h.supporting_evidence_ids or []),
            "contradicting_count": len(h.contradicting_evidence_ids or []),
        }
        for h in active_hypotheses
    ]
    evidence_count = db.query(EvidenceSpan).filter(EvidenceSpan.character_id == char_id).count()
    memories = db.query(MemoryItem).filter(
        MemoryItem.character_id == char_id,
        MemoryItem.status == "active",
    ).order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).limit(8).all()
    latest_snapshot = db.query(PersonalitySnapshot).filter(
        PersonalitySnapshot.character_id == char_id
    ).order_by(PersonalitySnapshot.version.desc()).first()
    latest_review_snapshot = db.query(PersonalitySnapshot).filter(
        PersonalitySnapshot.character_id == char_id,
        PersonalitySnapshot.source == "长上下文复盘",
    ).order_by(PersonalitySnapshot.created_at.desc()).first()
    result["memory_summary"] = {
        "evidence_count": evidence_count,
        "memory_count": db.query(MemoryItem).filter(MemoryItem.character_id == char_id, MemoryItem.status == "active").count(),
        "latest_snapshot_version": latest_snapshot.version if latest_snapshot else None,
        "latest_review_snapshot": {
            "id": latest_review_snapshot.id,
            "version": latest_review_snapshot.version,
            "created_at": latest_review_snapshot.created_at.isoformat() if latest_review_snapshot.created_at else "",
            "critic_result": latest_review_snapshot.critic_result or {},
        } if latest_review_snapshot else None,
        "recent_memories": [
            {
                "id": memory.id,
                "memory_type": memory.memory_type,
                "content": memory.content,
                "confidence": memory.confidence,
                "evidence_ids": memory.evidence_ids or [],
            }
            for memory in memories
        ],
    }
    return result


@router.get("/{char_id}/ai-update-log")
def get_character_ai_update_log(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    observations = db.query(CharacterObservation).filter_by(character_id=char_id).order_by(
        CharacterObservation.created_at.desc()
    ).all()
    return _build_ai_update_log(observations)


@router.get("/{char_id}/evidence", response_model=list[EvidenceSpanOut])
def list_character_evidence(char_id: int, limit: int = 80, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    return db.query(EvidenceSpan).filter(
        EvidenceSpan.character_id == char_id
    ).order_by(EvidenceSpan.created_at.desc()).limit(min(max(limit, 1), 200)).all()


@router.get("/{char_id}/memories", response_model=list[MemoryItemOut])
def list_character_memories(char_id: int, memory_type: str = "", db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    query = db.query(MemoryItem).filter(
        MemoryItem.character_id == char_id,
        MemoryItem.status == "active",
    )
    if memory_type:
        query = query.filter(MemoryItem.memory_type == memory_type)
    return query.order_by(MemoryItem.updated_at.desc(), MemoryItem.created_at.desc()).all()


@router.get("/{char_id}/snapshots", response_model=list[PersonalitySnapshotOut])
def list_personality_snapshots(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    return db.query(PersonalitySnapshot).filter(
        PersonalitySnapshot.character_id == char_id
    ).order_by(PersonalitySnapshot.version.desc()).all()


@router.get("/{char_id}/hypotheses", response_model=list[TraitHypothesisOut])
def list_trait_hypotheses(char_id: int, status: str = "", db: Session = Depends(get_db)):
    """角色的特质假设：active=系统正在琢磨的猜想；confirmed=已转正；rejected=已排除"""
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    query = db.query(TraitHypothesis).filter(TraitHypothesis.character_id == char_id)
    if status:
        query = query.filter(TraitHypothesis.status == status)
    return query.order_by(TraitHypothesis.confidence.desc(), TraitHypothesis.updated_at.desc()).limit(50).all()


@router.post("/{char_id}/snapshots/{snapshot_id}/restore", response_model=CharacterOut)
def restore_personality_snapshot(char_id: int, snapshot_id: int, db: Session = Depends(get_db)):
    """把角色档案回滚到指定快照（融合出错时的自救入口）"""
    char = db.get(Character, char_id)
    snapshot = db.get(PersonalitySnapshot, snapshot_id)
    if not char or not snapshot or snapshot.character_id != char_id:
        raise HTTPException(404, "快照不存在")
    payload = snapshot.profile_json or {}
    # 长上下文复盘快照的档案在 current_profile 子键下
    if "current_profile" in payload and isinstance(payload.get("current_profile"), dict):
        payload = payload["current_profile"]
    basic_info = payload.get("basic_info") or {}
    personality_model = payload.get("personality_model") or {}
    if not basic_info and not personality_model:
        raise HTTPException(400, "该快照不包含可恢复的档案数据")

    restore_map = {
        "role": basic_info.get("role"),
        "background": basic_info.get("background"),
        "motivation": payload.get("core_motivation"),
        "weakness": payload.get("core_weakness"),
        "speaking_style": payload.get("speaking_style"),
    }
    for field, value in restore_map.items():
        value = str(value or "").strip()
        old_value = str(getattr(char, field, "") or "").strip()
        if value and value != old_value:
            setattr(char, field, value)
            _create_change_observation(
                db, char.id, field, old_value, value,
                "快照回滚", f"恢复到快照 v{snapshot.version}（{snapshot.source or '未知来源'}）",
                1.0, _resolve_profile_module(field), "回滚",
            )
    if basic_info.get("age") is not None:
        char.age = basic_info.get("age")
    tags = [str(t).strip() for t in (personality_model.get("tags") or []) if str(t).strip()]
    if tags:
        char.personality_tags = tags[:12]
    traits = personality_model.get("core_traits") or {}
    if isinstance(traits, dict) and traits:
        char.core_traits = {
            key: round(max(0.0, min(1.0, float(value))), 2)
            for key, value in traits.items()
            if key in BIG_FIVE_KEYS and isinstance(value, (int, float))
        }
    char.version += 1
    char.updated_at = datetime.utcnow()
    _create_personality_snapshot(
        db, char, source="快照回滚",
        critic_result={"status": "restored", "reason": f"用户回滚到快照 v{snapshot.version}"},
    )
    db.commit()
    db.refresh(char)
    graph_store.sync_character(char)
    return char


@router.get("/{char_id}/diagnoses", response_model=list[StructuredDiagnosisOut])
def list_character_diagnoses(char_id: int, limit: int = 80, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    return db.query(StructuredDiagnosis).filter(
        (StructuredDiagnosis.speaker_id == char_id) | (StructuredDiagnosis.listener_id == char_id)
    ).order_by(StructuredDiagnosis.created_at.desc()).limit(min(max(limit, 1), 200)).all()


@router.post("/{char_id}/long-context-review", response_model=CharacterReviewOut)
async def run_long_context_review(
    char_id: int,
    body: CharacterReviewRequest | None = None,
    db: Session = Depends(get_db),
):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    body = body or CharacterReviewRequest()
    corpus = _build_review_corpus(db, char, body)
    agent_run = AgentRun(
        workflow_name="long_context_review",
        input_hash=f"character:{char_id}:window:{body.window_days or 'all'}:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        status="running",
        model_used="ai-harness",
        trace_json={
            "character_id": char_id,
            "scope": corpus.get("scope", {}),
            "steps": ["long_context_review", "long_context_review_critic", "snapshot", "observations", "memory_consolidation"],
        },
    )
    db.add(agent_run)
    db.commit()
    db.refresh(agent_run)

    observation_ids: list[int] = []
    memory_ids: list[int] = []
    snapshot_id = None
    try:
        review = await orchestrator.long_context_review(corpus)
        critic = await orchestrator.critique_long_context_review(review, _review_corpus_summary(corpus))
        updates = review.get("profile_updates") or []
        memories = review.get("consolidated_memories") or []
        approved_update_indexes = _approved_indexes(critic.get("approved_update_indexes"), len(updates))
        approved_memory_indexes = _approved_indexes(critic.get("approved_memory_indexes"), len(memories))
        final_status = critic.get("final_status") or "downgraded"
        snapshot_recommendation = critic.get("snapshot_recommendation") or "defer"

        supporting_evidence = _evidence_ids_from_review([
            item for index, item in enumerate(updates) if index in approved_update_indexes
        ] + [
            item for index, item in enumerate(memories) if index in approved_memory_indexes
        ])
        conflicting_evidence = _evidence_ids_from_review(review.get("contradictions") or [])
        latest = db.query(PersonalitySnapshot).filter(
            PersonalitySnapshot.character_id == char.id
        ).order_by(PersonalitySnapshot.version.desc()).first()
        snapshot = PersonalitySnapshot(
            character_id=char.id,
            version=(latest.version if latest else 0) + 1,
            profile_json={
                "current_profile": _build_snapshot_payload(char),
                "candidate_profile": review.get("candidate_profile") or {},
                "review_summary": review.get("summary") or "",
                "drift_analysis": review.get("drift_analysis") or {},
                "relationship_notes": review.get("relationship_notes") or [],
                "review_scope": review.get("review_scope") or corpus.get("scope", {}),
            },
            supporting_evidence=supporting_evidence,
            conflicting_evidence=conflicting_evidence,
            critic_result={
                **(critic or {}),
                "final_status": final_status,
                "snapshot_recommendation": snapshot_recommendation,
            },
            source="长上下文复盘",
        )
        db.add(snapshot)
        db.flush()
        snapshot_id = snapshot.id

        if body.create_observations and final_status in {"approved", "downgraded"}:
            for index, update in enumerate(updates):
                if index not in approved_update_indexes:
                    continue
                field = (update.get("field") or "").strip()
                if not field or not hasattr(char, field):
                    continue
                obs = _create_change_observation(
                    db,
                    char.id,
                    field,
                    update.get("old_value", getattr(char, field, "")),
                    update.get("new_value", ""),
                    "长上下文复盘",
                    update.get("reason", "") or review.get("summary", ""),
                    _safe_float(update.get("confidence"), review.get("confidence") or 0.0),
                    _resolve_profile_module(field),
                    update.get("change_type") or _infer_change_type(update.get("old_value", getattr(char, field, "")), update.get("new_value", "")),
                    status="pending",
                    example=f"证据ID：{update.get('evidence_ids') or []}；反证ID：{update.get('conflicting_evidence_ids') or []}",
                )
                if obs:
                    observation_ids.append(obs.id)

        if body.consolidate_memories and final_status in {"approved", "downgraded"}:
            for index, memory in enumerate(memories):
                if index not in approved_memory_indexes:
                    continue
                item = _create_memory_item(
                    db,
                    character_id=char.id,
                    memory_type=memory.get("memory_type") or "diagnosis",
                    content=memory.get("content") or "",
                    confidence=_safe_float(memory.get("confidence"), review.get("confidence") or 0.0),
                    source="长上下文复盘",
                    evidence_ids=[int(eid) for eid in (memory.get("evidence_ids") or []) if str(eid).isdigit()],
                )
                if item:
                    memory_ids.append(item.id)

        agent_run.status = "completed"
        agent_run.trace_json = {
            **(agent_run.trace_json or {}),
            "final_status": final_status,
            "snapshot_recommendation": snapshot_recommendation,
            "snapshot_id": snapshot_id,
            "observation_ids": observation_ids,
            "memory_ids": memory_ids,
            "critic": critic,
        }
        agent_run.updated_at = datetime.utcnow()
        db.commit()
        return CharacterReviewOut(
            ok=True,
            character_id=char.id,
            agent_run_id=agent_run.id,
            snapshot_id=snapshot_id,
            observation_ids=observation_ids,
            memory_ids=memory_ids,
            review=review,
            critic=critic,
        )
    except Exception as exc:
        db.rollback()
        agent_run.status = "failed"
        agent_run.trace_json = {**(agent_run.trace_json or {}), "error": str(exc)}
        agent_run.updated_at = datetime.utcnow()
        db.add(agent_run)
        db.commit()
        raise HTTPException(502, f"长上下文复盘失败：{exc}") from exc


@router.put("/{char_id}", response_model=CharacterOut)
def update_character(char_id: int, body: CharacterUpdate, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    for k, v in body.model_dump(exclude_none=True).items():
        old_value = getattr(char, k, None)
        # core_traits 允许前端只提交改动过的维度：做字典合并而非整体替换，
        # 避免部分提交把其余维度抹掉
        if k == "core_traits" and isinstance(v, dict):
            v = {**(char.core_traits or {}), **{
                key: round(max(0.0, min(1.0, float(val))), 2)
                for key, val in v.items()
                if key in BIG_FIVE_KEYS and isinstance(val, (int, float))
            }}
        if _stringify_value(old_value) == _stringify_value(v):
            continue
        setattr(char, k, v)
        # 手动编辑同样留痕（来源=手动编辑，不进 AI 更新记录页，但保证档案变更可追溯）
        if k in {"role", "background", "motivation", "weakness", "speaking_style", "personality_tags", "core_traits", "age", "name", "aliases"}:
            _create_change_observation(
                db, char.id, k, old_value, v,
                "手动编辑", "用户在编辑表单中修改", 1.0,
                _resolve_profile_module(k),
                _infer_change_type(old_value, v, prefer_override=True),
            )
    char.version += 1
    char.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(char)
    graph_store.sync_character(char)
    return char


@router.post("/{char_id}/merge", response_model=CharacterOut)
def merge_character(char_id: int, body: CharacterMergeRequest, db: Session = Depends(get_db)):
    """把另一个角色完整并入当前角色（补救'同一人分裂成多个角色'）"""
    target = db.get(Character, char_id)
    source = db.get(Character, body.source_id)
    if not target or not source:
        raise HTTPException(404, "角色不存在")
    if target.id == source.id:
        raise HTTPException(400, "不能将角色与自身合并")
    source_name = source.name
    try:
        stats = merge_characters(db, target, source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _create_change_observation(
        db, target.id, "background",
        "", f"已合并角色「{source_name}」的全部数据（事件 {stats['events']}、记忆 {stats['memories']}、证据 {stats['evidence']}）",
        "角色合并", f"用户确认「{source_name}」与「{target.name}」为同一人物", 1.0,
        "基础信息", "合并",
    )
    _create_personality_snapshot(db, target, source="角色合并")
    db.commit()
    db.refresh(target)
    graph_store.sync_character(target)
    return target


@router.delete("/{char_id}")
def delete_character(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    # 清理无 ORM 级联的松散引用，避免孤儿外键
    db.query(Message).filter(Message.character_id == char_id).update(
        {"character_id": None}, synchronize_session=False)
    db.query(Message).filter(Message.receiver_id == char_id).update(
        {"receiver_id": None}, synchronize_session=False)
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.speaker_id == char_id).update(
        {"speaker_id": None}, synchronize_session=False)
    db.query(StructuredDiagnosis).filter(StructuredDiagnosis.listener_id == char_id).update(
        {"listener_id": None}, synchronize_session=False)
    db.query(RetrievalTrace).filter(RetrievalTrace.speaker_id == char_id).update(
        {"speaker_id": None}, synchronize_session=False)
    db.query(RetrievalTrace).filter(RetrievalTrace.listener_id == char_id).update(
        {"listener_id": None}, synchronize_session=False)
    db.query(TraitHypothesis).filter(TraitHypothesis.character_id == char_id).delete(synchronize_session=False)
    db.delete(char)
    db.commit()
    return {"ok": True}


@router.post("/imports/preview")
async def preview_import(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        content = await file.read()
        content_text = await extract_text_from_file(file.filename or "unknown.txt", content)
        latest_same_file = db.query(ImportFile).filter(
            ImportFile.filename == (file.filename or "unknown.txt")
        ).order_by(ImportFile.created_at.desc()).first()
        next_version = (latest_same_file.version if latest_same_file else 0) + 1
        existing_characters = [
            {"id": char.id, "name": char.name, "role": char.role or "", "aliases": list(char.aliases or [])}
            for char in db.query(Character).all()
        ]
        preview = await build_import_preview(file.filename or "unknown.txt", content_text, existing_characters, enable_ai=False)
        preview_status = "preview_ready" if preview.get("detected_type") == "structured" else "preview_processing"
        import_file = ImportFile(
            filename=file.filename or "unknown.txt",
            file_type=preview.get("detected_type", Path(file.filename or "").suffix.lower().lstrip(".")),
            content_type=file.content_type or "",
            status=preview_status,
            version=next_version,
            model_used="ai-harness",
            summary=(preview.get("plot_summary", {}) or {}).get("main_conflict", ""),
            metadata_json={
                "import_version": {
                    "file_id": None,
                    "version": next_version,
                    "model_used": "ai-harness",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                "role_count": len(preview.get("characters", [])),
                "interaction_count": len(preview.get("interaction_units", [])),
                "event_count": len(preview.get("events", [])),
                "relationship_count": len(preview.get("relationships", [])),
                "preview_payload": preview,
            },
        )
        db.add(import_file)
        db.commit()
        db.refresh(import_file)
        preview["import_file_id"] = import_file.id
        preview["import_version"] = {
            "file_id": import_file.id,
            "version": import_file.version,
            "model_used": import_file.model_used,
            "timestamp": import_file.created_at.isoformat() if import_file.created_at else datetime.utcnow().isoformat(),
        }
        preview["preview_status"] = preview_status
        if preview_status == "preview_processing":
            preview["warning_message"] = "AI 预览增强正在后台处理中，请稍候自动刷新。"
            _update_import_status(
                db,
                import_file,
                "preview_processing",
                "AI 预览增强正在后台处理中…",
                preview_payload=preview,
            )
            background_tasks.add_task(
                _enhance_import_preview,
                import_file.id,
                file.filename or "unknown.txt",
                content_text,
            )
        else:
            _update_import_status(
                db,
                import_file,
                "preview_ready",
                "结构化预览已就绪",
                preview_payload=preview,
            )
        return preview
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"导入预览失败：{exc}") from exc


@router.post("/imports/commit")
async def commit_import(body: ImportCommitRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    preview = body.preview_payload or {}
    import_file = db.get(ImportFile, body.import_file_id) if body.import_file_id else None
    if import_file and import_file.status == "preview_processing":
        raise HTTPException(409, "AI 预览增强尚未完成，请稍候再导入。")
    if not import_file:
        latest_same_file = db.query(ImportFile).filter(
            ImportFile.filename == body.filename
        ).order_by(ImportFile.created_at.desc()).first()
        import_file = ImportFile(
            filename=body.filename,
            file_type=body.file_type,
            content_type="",
            status="committed",
            version=((latest_same_file.version if latest_same_file else 0) + 1),
            model_used="ai-harness",
            summary=(preview.get("plot_summary", {}) or {}).get("main_conflict", ""),
            metadata_json={},
        )
        db.add(import_file)
        db.commit()
        db.refresh(import_file)
    _update_import_status(
        db,
        import_file,
        "queued",
        "导入任务已进入后台队列，正在准备自动审核与入库…",
        import_version={
            "file_id": import_file.id,
            "version": import_file.version,
            "model_used": import_file.model_used,
            "timestamp": datetime.utcnow().isoformat(),
        },
        request_options={
            "scenario": body.scenario,
            "create_readonly_conversation": body.create_readonly_conversation,
            "auto_archive": body.auto_archive,
        },
    )
    import_logger.info("导入任务已排队 import_file_id=%s filename=%s", import_file.id, body.filename)
    background_tasks.add_task(_process_import_commit, import_file.id, body.model_dump(mode="json"))
    return {
        "ok": True,
        "async_started": True,
        "import_file_id": import_file.id,
        "status": "queued",
        "message": "导入任务已提交，后台正在自动审核并入库。",
    }


@router.get("/imports/{import_file_id}/status")
def get_import_status(import_file_id: int, db: Session = Depends(get_db)):
    import_file = db.get(ImportFile, import_file_id)
    if not import_file:
        raise HTTPException(404, "导入任务不存在")
    metadata = import_file.metadata_json or {}
    return {
        "import_file_id": import_file.id,
        "filename": import_file.filename,
        "status": import_file.status,
        "summary": import_file.summary,
        "progress": metadata.get("progress", {}),
        "preview_payload": metadata.get("preview_payload", {}),
        "preview_warning": metadata.get("preview_warning", ""),
        "review_summary": metadata.get("review_summary", ""),
        "result": metadata.get("result", {}),
        "event_count": metadata.get("event_count", 0),
        "relationship_count": metadata.get("relationship_count", 0),
        "failures": metadata.get("failures", {}),
        "updated_at": import_file.updated_at.isoformat() if import_file.updated_at else "",
    }


@router.get("/exports/full")
def export_all_data(db: Session = Depends(get_db)):
    payload = {
        "characters": [CharacterOut.model_validate(char).model_dump(mode="json") for char in db.query(Character).all()],
        "events": [EventOut.model_validate(event).model_dump(mode="json") for event in db.query(CharacterEvent).all()],
        "relationships": [RelationshipOut.model_validate(rel).model_dump(mode="json") for rel in db.query(Relationship).all()],
        "observations": [ObservationOut.model_validate(obs).model_dump(mode="json") for obs in db.query(CharacterObservation).all()],
        "conversations": [
            {
                "id": conv.id,
                "title": conv.title,
                "scenario": conv.scenario,
                "is_readonly": getattr(conv, "is_readonly", False),
                "source_import_file_id": getattr(conv, "source_import_file_id", None),
                "active_branch_id": getattr(conv, "active_branch_id", None),
                "active_branch_point_id": getattr(conv, "active_branch_point_id", None),
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
            }
            for conv in db.query(Conversation).order_by(Conversation.created_at).all()
        ],
        "messages": [
            MessageOut.model_validate(message).model_dump(mode="json")
            for message in db.query(Message).order_by(Message.created_at).all()
        ],
        "imports": [
            {
                "file": {
                    "id": item.id,
                    "filename": item.filename,
                    "file_type": item.file_type,
                    "status": item.status,
                    "version": item.version,
                    "model_used": item.model_used,
                    "summary": item.summary,
                    "metadata_json": item.metadata_json or {},
                },
                "interaction_units": [
                    {
                        "id": unit.id,
                        "source_line_index": unit.source_line_index,
                        "source_text_snippet": unit.source_text_snippet,
                        "speaker": unit.speaker,
                        "receiver": unit.receiver,
                        "receiver_confidence": unit.receiver_confidence,
                        "receiver_state": unit.receiver_state,
                        "content": unit.content,
                        "intent": {"value": unit.intent, "confidence": unit.intent_confidence, "state": unit.intent_state},
                        "strategy": {"value": unit.strategy, "confidence": unit.strategy_confidence, "state": unit.strategy_state},
                        "emotion": {"value": unit.emotion, "confidence": unit.emotion_confidence, "state": unit.emotion_state},
                        "interaction_type": {"value": unit.interaction_type, "confidence": unit.interaction_confidence, "state": unit.interaction_state},
                        "psychological_label": unit.psychological_label,
                        "context_window": unit.context_window or [],
                        "analysis": unit.analysis or {},
                        "character_event_id": unit.character_event_id,
                        "relationship_id": unit.relationship_id,
                    }
                    for unit in item.interaction_units
                ],
            }
            for item in db.query(ImportFile).order_by(ImportFile.created_at.desc()).all()
        ],
        "evidence_spans": [
            EvidenceSpanOut.model_validate(evidence).model_dump(mode="json")
            for evidence in db.query(EvidenceSpan).order_by(EvidenceSpan.created_at).all()
        ],
        "memory_items": [
            MemoryItemOut.model_validate(memory).model_dump(mode="json")
            for memory in db.query(MemoryItem).order_by(MemoryItem.created_at).all()
        ],
        "personality_snapshots": [
            PersonalitySnapshotOut.model_validate(snapshot).model_dump(mode="json")
            for snapshot in db.query(PersonalitySnapshot).order_by(PersonalitySnapshot.created_at).all()
        ],
        "structured_diagnoses": [
            StructuredDiagnosisOut.model_validate(report).model_dump(mode="json")
            for report in db.query(StructuredDiagnosis).order_by(StructuredDiagnosis.created_at).all()
        ],
        "agent_runs": [
            {
                "id": run.id,
                "workflow_name": run.workflow_name,
                "input_hash": run.input_hash,
                "status": run.status,
                "model_used": run.model_used,
                "trace_json": run.trace_json or {},
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            }
            for run in db.query(AgentRun).order_by(AgentRun.created_at).all()
        ],
        "retrieval_traces": [
            {
                "id": trace.id,
                "conversation_id": trace.conversation_id,
                "speaker_id": trace.speaker_id,
                "listener_id": trace.listener_id,
                "query_text": trace.query_text,
                "strategy": trace.strategy or {},
                "evidence_pack": trace.evidence_pack or {},
                "created_at": trace.created_at.isoformat() if trace.created_at else None,
            }
            for trace in db.query(RetrievalTrace).order_by(RetrievalTrace.created_at).all()
        ],
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename=btb-export-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"},
    )


# ─── Graph Store ──────────────────────────────────────────────────────────────

@router.get("/graph/health")
def graph_health():
    return graph_store.health()


@router.post("/graph/start")
def start_graph_store():
    return graph_store.start_bundled()


@router.post("/graph/sync-all")
def sync_graph_store(db: Session = Depends(get_db)):
    health = graph_store.health()
    if not health.get("available"):
        raise HTTPException(503, {"message": "Neo4j 当前不可用，请先启动图谱服务。", "health": health})
    graph_store.ensure_schema()
    counts = {
        "characters": 0,
        "relationships": 0,
        "events": 0,
        "evidence": 0,
        "memories": 0,
    }
    for char in db.query(Character).all():
        if graph_store.sync_character(char):
            counts["characters"] += 1
    for rel in db.query(Relationship).all():
        if graph_store.sync_relationship(rel, rel.source, rel.target):
            counts["relationships"] += 1
    for event in db.query(CharacterEvent).all():
        if graph_store.sync_event(event, event.character):
            counts["events"] += 1
    for evidence in db.query(EvidenceSpan).all():
        if graph_store.sync_evidence(evidence):
            counts["evidence"] += 1
    for memory in db.query(MemoryItem).all():
        if graph_store.sync_memory(memory):
            counts["memories"] += 1
    return {"ok": True, "health": graph_store.health(), "counts": counts}


@router.get("/graph/context")
def get_graph_context(speaker_id: int | None = None, listener_id: int | None = None):
    health = graph_store.health()
    if not health.get("available"):
        raise HTTPException(503, {"message": "Neo4j 当前不可用，请先启动图谱服务。", "health": health})
    return graph_store.get_graph_context(speaker_id, listener_id)


# ─── AI Suggestions ──────────────────────────────────────────────────────────

@router.post("/{char_id}/suggest-update")
async def suggest_update(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404)
    profile = {
        "name": char.name, "role": char.role,
        "personality_tags": char.personality_tags,
        "weakness": char.weakness, "motivation": char.motivation,
    }
    # 取最近对话文本（简化：用 events 代替）
    events = db.query(CharacterEvent).filter_by(character_id=char_id).order_by(CharacterEvent.created_at.desc()).limit(5).all()
    dialogue = "\n".join(e.description for e in events if e.description) or "暂无对话记录"
    suggestions = await orchestrator.suggest_character_update(profile, dialogue)
    obs_list = []
    for s in suggestions:
        field = s.get("field", "")
        obs = CharacterObservation(
            character_id=char_id,
            field=field,
            old_value=str(s.get("old_value", "")),
            new_value=str(s.get("new_value", "")),
            reason=_build_observation_reason(
                source="对话",
                evidence=s.get("reason", "") or "基于最近对话生成的更新建议",
                confidence=0.72,
                change_type=_infer_change_type(s.get("old_value", ""), s.get("new_value", "")),
                module=_resolve_profile_module(field),
            ),
            metadata_json=_build_observation_metadata(
                source="对话",
                evidence=s.get("reason", "") or "基于最近对话生成的更新建议",
                confidence=0.72,
                change_type=_infer_change_type(s.get("old_value", ""), s.get("new_value", "")),
                module=_resolve_profile_module(field),
            ),
        )
        db.add(obs)
        db.flush()
        evidence = _create_evidence_span(
            db,
            character_id=char_id,
            source_type="chat_suggestion",
            source_id=obs.id,
            observation_id=obs.id,
            supports_type=field or "profile_update",
            supports_id=obs.id,
            quote=s.get("reason", "") or dialogue[:300],
            interpretation=f"AI 建议更新：{field}",
            confidence=0.72,
            metadata={"field": field, "recent_dialogue": dialogue[:1000]},
        )
        _create_memory_item(
            db,
            character_id=char_id,
            memory_type="diagnosis" if field in {"personality_tags", "core_traits"} else "fact",
            content=str(s.get("new_value", "")),
            confidence=0.72,
            source="AI建议更新",
            evidence_ids=[evidence.id],
        )
        obs_list.append(obs)
    db.commit()
    for o in obs_list:
        db.refresh(o)
    return obs_list


@router.get("/{char_id}/observations", response_model=list[ObservationOut])
def list_observations(char_id: int, db: Session = Depends(get_db)):
    return db.query(CharacterObservation).filter_by(character_id=char_id).order_by(CharacterObservation.created_at.desc()).all()


@router.post("/{char_id}/observations/{obs_id}/review")
def review_observation(char_id: int, obs_id: int, body: ObservationReview, db: Session = Depends(get_db)):
    obs = db.get(CharacterObservation, obs_id)
    if not obs or obs.character_id != char_id:
        raise HTTPException(404)
    obs.status = body.status
    obs.reviewed_at = datetime.utcnow()
    if body.status == "approved":
        char = db.get(Character, char_id)
        if char and hasattr(char, obs.field):
            setattr(char, obs.field, _coerce_observation_value(obs.field, obs.new_value))
            char.version += 1
            existing_evidence = db.query(EvidenceSpan).filter(
                EvidenceSpan.observation_id == obs.id,
            ).first()
            if not existing_evidence:
                existing_evidence = _create_evidence_span(
                    db,
                    character_id=char_id,
                    source_type="observation_review",
                    source_id=obs.id,
                    observation_id=obs.id,
                    supports_type=obs.field or "profile_update",
                    supports_id=obs.id,
                    quote=obs.reason or obs.new_value,
                    interpretation=f"审核通过的档案更新：{obs.field}",
                    confidence=0.8,
                    metadata={"status": body.status},
                )
            _create_memory_item(
                db,
                character_id=char_id,
                memory_type="diagnosis" if obs.field in {"personality_tags", "core_traits"} else "fact",
                content=obs.new_value or "",
                confidence=max(0.8, float(existing_evidence.confidence or 0.0)),
                source="人工审核",
                evidence_ids=[existing_evidence.id],
            )
            _create_personality_snapshot(
                db,
                char,
                source="人工审核",
                supporting_evidence=[existing_evidence.id],
                critic_result={"status": "human_approved", "reason": "用户批准 AI 建议。"},
            )
            graph_store.sync_character(char)
    db.commit()
    return {"ok": True, "status": body.status}


@router.post("/{char_id}/behavior-patterns", response_model=ObservationOut)
def create_behavior_pattern(char_id: int, body: BehaviorPatternPayload, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    obs = CharacterObservation(
        character_id=char_id,
        field="behavior_pattern",
        old_value="",
        new_value=body.new_value.strip(),
        reason=_format_behavior_pattern_reason(body.source, body.confidence, body.category, body.trigger, body.example),
        metadata_json=_build_observation_metadata(
            source=body.source or "手动编辑",
            evidence=body.example or body.trigger or "行为模式识别结果",
            confidence=body.confidence,
            change_type="新增",
            module="行为模式",
            category=body.category or "互动策略",
            trigger=body.trigger,
            example=body.example,
        ),
        status="approved",
        reviewed_at=datetime.utcnow(),
    )
    db.add(obs)
    db.flush()
    evidence = _create_evidence_span(
        db,
        character_id=char_id,
        source_type="manual",
        source_id=obs.id,
        observation_id=obs.id,
        supports_type="behavior_pattern",
        supports_id=obs.id,
        quote=body.example or body.trigger or body.new_value,
        interpretation=f"{body.category}：{body.new_value}",
        confidence=body.confidence,
        metadata={"category": body.category, "trigger": body.trigger},
    )
    _create_memory_item(
        db,
        character_id=char_id,
        memory_type="pragmatics",
        content=body.new_value,
        confidence=body.confidence,
        source=body.source,
        evidence_ids=[evidence.id],
    )
    db.commit()
    db.refresh(obs)
    return obs


@router.put("/{char_id}/behavior-patterns/{obs_id}", response_model=ObservationOut)
def update_behavior_pattern(char_id: int, obs_id: int, body: BehaviorPatternPayload, db: Session = Depends(get_db)):
    obs = db.get(CharacterObservation, obs_id)
    if not obs or obs.character_id != char_id or obs.field != "behavior_pattern":
        raise HTTPException(404, "行为模式不存在")
    obs.new_value = body.new_value.strip()
    obs.reason = _format_behavior_pattern_reason(body.source, body.confidence, body.category, body.trigger, body.example)
    obs.metadata_json = _build_observation_metadata(
        source=body.source or "手动编辑",
        evidence=body.example or body.trigger or "行为模式识别结果",
        confidence=body.confidence,
        change_type="更新",
        module="行为模式",
        category=body.category or "互动策略",
        trigger=body.trigger,
        example=body.example,
    )
    obs.status = "approved"
    obs.reviewed_at = datetime.utcnow()
    evidence = _create_evidence_span(
        db,
        character_id=char_id,
        source_type="manual",
        source_id=obs.id,
        observation_id=obs.id,
        supports_type="behavior_pattern",
        supports_id=obs.id,
        quote=body.example or body.trigger or body.new_value,
        interpretation=f"手动更新行为模式：{body.new_value}",
        confidence=body.confidence,
        metadata={"category": body.category, "trigger": body.trigger},
    )
    _create_memory_item(
        db,
        character_id=char_id,
        memory_type="pragmatics",
        content=body.new_value,
        confidence=body.confidence,
        source=body.source,
        evidence_ids=[evidence.id],
    )
    db.commit()
    db.refresh(obs)
    return obs


@router.delete("/{char_id}/behavior-patterns/{obs_id}")
def delete_behavior_pattern(char_id: int, obs_id: int, db: Session = Depends(get_db)):
    obs = db.get(CharacterObservation, obs_id)
    if not obs or obs.character_id != char_id or obs.field != "behavior_pattern":
        raise HTTPException(404, "行为模式不存在")
    db.query(MemoryItem).filter(
        MemoryItem.character_id == char_id,
        MemoryItem.memory_type == "pragmatics",
        MemoryItem.content == (obs.new_value or ""),
        MemoryItem.status == "active",
    ).update({"status": "deprecated", "updated_at": datetime.utcnow()})
    db.delete(obs)
    db.commit()
    return {"ok": True}


# ─── Events ───────────────────────────────────────────────────────────────────

@router.get("/{char_id}/events", response_model=list[EventOut])
def list_events(char_id: int, db: Session = Depends(get_db)):
    return db.query(CharacterEvent).filter_by(character_id=char_id).order_by(
        CharacterEvent.event_date.desc(),
        CharacterEvent.created_at.desc(),
    ).all()


@router.post("/{char_id}/events", response_model=EventOut)
def create_event(char_id: int, body: EventCreate, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    event = CharacterEvent(**body.model_dump())
    event.character_id = char_id
    db.add(event)
    db.commit()
    db.refresh(event)
    graph_store.sync_event(event, char)
    return event


@router.delete("/{char_id}/events/{event_id}")
def delete_event(char_id: int, event_id: int, db: Session = Depends(get_db)):
    ev = db.get(CharacterEvent, event_id)
    if not ev:
        raise HTTPException(404)
    db.delete(ev)
    db.commit()
    return {"ok": True}


# ─── Relationships ────────────────────────────────────────────────────────────

@router.get("/relationships/all", response_model=list[RelationshipOut])
def list_all_relationships(db: Session = Depends(get_db)):
    return db.query(Relationship).all()


@router.post("/relationships/", response_model=RelationshipOut)
def create_relationship(body: RelationshipCreate, db: Session = Depends(get_db)):
    if body.source_id == body.target_id:
        raise HTTPException(400, "不能创建指向自己的关系")
    # 两个人物之间只允许一条关系（方向无关）
    existing = find_pair_relationship(db, body.source_id, body.target_id)
    if existing:
        raise HTTPException(400, "这两个角色之间已存在关系，请直接编辑")
    rel = Relationship(**body.model_dump(), history=[])
    db.add(rel)
    db.commit()
    db.refresh(rel)
    graph_store.sync_relationship(rel, rel.source, rel.target)
    return rel


@router.put("/relationships/{rel_id}", response_model=RelationshipOut)
def update_relationship(rel_id: int, body: RelationshipUpdate, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    # 保存历史快照
    snapshot = {
        "date": datetime.utcnow().isoformat(),
        "strength": rel.strength,
        "sentiment": rel.sentiment,
    }
    history = rel.history or []
    history.append(snapshot)
    rel.history = history
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(rel, k, v)
    rel.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rel)
    graph_store.sync_relationship(rel, rel.source, rel.target)
    return rel


@router.delete("/relationships/{rel_id}")
def delete_relationship(rel_id: int, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    db.delete(rel)
    db.commit()
    return {"ok": True}


@router.get("/relationships/{rel_id}/analyze")
async def analyze_relationship(rel_id: int, db: Session = Depends(get_db)):
    rel = db.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404)
    char_a = f"{rel.source.name}（{rel.source.role}）"
    char_b = f"{rel.target.name}（{rel.target.role}）"
    result = await orchestrator.analyze_relationship(char_a, char_b, rel.history or [])
    return result
