import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..models.sql_models import (
    Character, CharacterEvent, Relationship, CharacterObservation,
    Conversation, Message, ImportFile, InteractionUnit
)
from ..schemas import (
    CharacterCreate, CharacterUpdate, CharacterOut,
    EventCreate, EventOut,
    RelationshipCreate, RelationshipUpdate, RelationshipOut,
    ObservationReview, ObservationOut, ImportCommitRequest, BehaviorPatternPayload,
)
from ..harness.orchestrator import orchestrator
from ..harness.import_engine import extract_text_from_file, build_import_preview
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


def _resolve_mapping(role_mappings: list, original_name: str) -> dict:
    for mapping in role_mappings:
        if mapping.original_name == original_name:
            return {
                "name": mapping.resolved_name.strip() or original_name,
                "action": mapping.action,
            }
    return {"name": original_name, "action": "create"}


async def _ensure_character_from_mapping(db: Session, mapping: dict, parsed_character: dict) -> Character:
    resolved_name = mapping["name"]
    existing = db.query(Character).filter(Character.name == resolved_name).first()
    if existing:
        return existing

    char = Character(
        name=resolved_name,
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
    try:
        profile = await orchestrator.generate_character_profile(
            char.name,
            char.role or "",
            char.background or "",
        )
        char.personality_tags = profile.get("personality_tags", []) or char.personality_tags
        char.core_traits = profile.get("core_traits", {}) or {}
        char.weakness = profile.get("weakness", "") or char.weakness
        char.motivation = profile.get("motivation", "") or char.motivation
        char.speaking_style = profile.get("speaking_style", "") or char.speaking_style
        db.flush()
        db.refresh(char)
    except Exception:
        pass
    return char


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
        status=status,
        reviewed_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(observation)
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
        metadata = _parse_observation_reason(observation.reason)
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
        metadata = _parse_observation_reason(observation.reason)
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

        for field in ("role", "background"):
            new_value = basic_info.get(field)
            old_value = getattr(char, field, "")
            if new_value and new_value != old_value:
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
                    _infer_change_type(old_value, new_value, prefer_override=True),
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
            old_value = getattr(char, field, "")
            if new_value and new_value != old_value:
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
                    _infer_change_type(old_value, new_value, prefer_override=True),
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
    db.commit()
    return total_changes


async def _enhance_import_preview(import_file_id: int, filename: str, content_text: str) -> None:
    db = SessionLocal()
    try:
        import_file = db.get(ImportFile, import_file_id)
        if not import_file:
            return
        existing_characters = [
            {"id": char.id, "name": char.name, "role": char.role or ""}
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


def _build_timeline_event_drafts(preview: dict[str, Any]) -> list[dict[str, Any]]:
    preview_events = preview.get("events") or []
    drafts = []
    if preview_events:
        for index, event in enumerate(preview_events[:20], start=1):
            actors = _dedupe_names([event.get("actor", "")] + list(event.get("participants") or []))
            if not actors:
                continue
            detail_parts = []
            if event.get("summary"):
                detail_parts.append(event["summary"])
            if event.get("action"):
                detail_parts.append(f"核心动作：{event['action']}")
            if event.get("time"):
                detail_parts.append(f"时间：{event['time']}")
            if event.get("location"):
                detail_parts.append(f"地点：{event['location']}")
            drafts.append(
                {
                    "actors": actors,
                    "title": f"{'、'.join(actors[:2])}事件记录",
                    "description": "；".join(detail_parts)[:500],
                    "event_date": event.get("time", "") or "",
                    "emotion_label": "",
                    "importance": 4,
                    "source_indexes": [index],
                }
            )
    if drafts:
        return drafts

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
        drafts.append(
            {
                "actors": actors,
                "title": f"{actors[0]}与{'、'.join(actors[1:3]) or '他人'}的阶段性事件",
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


async def _rebuild_import_analyses(preview: dict[str, Any], resolved_chars: dict[str, Character], concurrency: int = 3) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    analyses: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    async def _analyze(index: int, unit: dict[str, Any]) -> None:
        speaker_name = (unit.get("speaker") or "").strip()
        if not speaker_name or speaker_name not in resolved_chars:
            return
        speaker_char = resolved_chars[speaker_name]
        receiver_name = (unit.get("receiver") or "").strip()
        resolved_receiver = resolved_chars.get(receiver_name) if receiver_name in resolved_chars else None
        context_payload = {
            "speaker_profile": {
                "name": speaker_char.name,
                "role": speaker_char.role or "",
                "personality_tags": speaker_char.personality_tags or [],
                "motivation": speaker_char.motivation or "",
                "weakness": speaker_char.weakness or "",
                "speaking_style": speaker_char.speaking_style or "",
            },
            "receiver_profile": {
                "name": resolved_receiver.name if resolved_receiver else receiver_name,
                "role": resolved_receiver.role if resolved_receiver else "",
                "personality_tags": resolved_receiver.personality_tags if resolved_receiver else [],
                "motivation": resolved_receiver.motivation if resolved_receiver else "",
                "weakness": resolved_receiver.weakness if resolved_receiver else "",
                "speaking_style": resolved_receiver.speaking_style if resolved_receiver else "",
            },
            "relationship": {
                "description": "",
                "strength": 0.2,
                "sentiment": 0.0,
            },
        }
        try:
            async with semaphore:
                analyses[index] = await orchestrator.rebuild_import_analysis(unit, context_payload)
        except Exception as exc:
            failures.append({"index": index, "error": str(exc)})

    await asyncio.gather(*[
        _analyze(index, unit)
        for index, unit in enumerate(preview.get("interaction_units", []), start=1)
    ])
    return analyses, failures


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


async def _process_import_commit(import_file_id: int, payload: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        body = ImportCommitRequest.model_validate(payload)
        import_file = db.get(ImportFile, import_file_id)
        if not import_file:
            return
        preview = dict(body.preview_payload or {})
        role_mappings = list(body.role_mappings or [])

        import_logger.info("导入任务开始 import_file_id=%s filename=%s", import_file.id, body.filename)
        _update_import_status(db, import_file, "reviewing", "AI 审核代理正在自动审核导入结果…")
        preview, role_mappings, review_summary = await _auto_review_import(preview, role_mappings, import_file.id)

        resolved_chars = {}
        parsed_characters = {item.get("name"): item for item in preview.get("characters", [])}
        for original_name, parsed_char in parsed_characters.items():
            mapping = _resolve_mapping(role_mappings, original_name)
            if mapping["action"] == "skip":
                continue
            resolved_chars[original_name] = await _ensure_character_from_mapping(db, mapping, parsed_char)

        conversation = None
        if body.create_readonly_conversation:
            conversation = Conversation(
                title=f"只读导入 · {body.filename}",
                scenario=body.scenario,
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

        committed_units = 0
        created_relationships = 0
        failures = {"characters": [], "events": [], "relationships": [], "analysis": []}
        preview_messages = ((preview.get("pseudo_conversation", {}) or {}).get("messages", []))
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
                analysis = analysis_map.get(index)
                if not isinstance(analysis, dict):
                    continue
                message_id = None
                analysis_message_id = None
                message_step = 2 if conversation else 0
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
                    if resolved_receiver:
                        intent_conf = _safe_float((unit.get("intent") or {}).get("confidence"), 0.5)
                        sentiment = _safe_float((unit.get("emotion") or {}).get("confidence"), 0.5) * 2 - 1
                        interaction_type = (unit.get("interaction_type") or {}).get("value", "")
                        rel = db.query(Relationship).filter(
                            Relationship.source_id == speaker_char.id,
                            Relationship.target_id == resolved_receiver.id,
                        ).first()
                        if not rel:
                            rel = Relationship(
                                source_id=speaker_char.id,
                                target_id=resolved_receiver.id,
                                rel_type=_infer_rel_type(sentiment, interaction_type),
                                strength=max(0.2, min(1.0, intent_conf)),
                                sentiment=max(-1.0, min(1.0, sentiment)),
                                description=analysis.get("strategy_explanation", "")[:500],
                                history=[],
                            )
                            db.add(rel)
                            db.flush()
                            created_relationship = True
                            _create_change_observation(
                                db,
                                speaker_char.id,
                                "relationship_network",
                                "",
                                f"{speaker_char.name} → {resolved_receiver.name}（{rel.rel_type}）",
                                "导入文本",
                                unit.get("psychological_label", "") or analysis.get("strategy_explanation", "")[:160] or "导入文本识别出的关系变化",
                                max(0.6, min(0.95, intent_conf)),
                                "关系网络",
                                "新增",
                                example=(unit.get("content", "") or "")[:120],
                            )
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
                committed_units += 1
                if created_relationship:
                    created_relationships += 1
                next_message_index += message_step
            except Exception as exc:
                failures["analysis"].append({"index": index, "error": str(exc)})
                import_logger.exception("导入交互写入失败 import_file_id=%s index=%s", import_file.id, index)

        db.commit()

        import_file.summary = (preview.get("plot_summary", {}) or {}).get("main_conflict", import_file.summary)
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
                "profile_changes": profile_change_count,
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
    char = Character(**body.model_dump())
    char.core_traits = {}
    db.add(char)
    db.commit()
    db.refresh(char)
    # 自动生成 AI 心理档案
    try:
        profile = await orchestrator.generate_character_profile(
            char.name, char.role, char.background
        )
        char.personality_tags = profile.get("personality_tags", [])
        char.core_traits = profile.get("core_traits", {})
        char.weakness = profile.get("weakness", "")
        char.motivation = profile.get("motivation", "")
        char.speaking_style = profile.get("speaking_style", "")
        db.commit()
        db.refresh(char)
    except Exception:
        pass  # AI 分析失败不影响创建
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
    return _build_profile_view(char, relationships, events, observations)


@router.get("/{char_id}/ai-update-log")
def get_character_ai_update_log(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    observations = db.query(CharacterObservation).filter_by(character_id=char_id).order_by(
        CharacterObservation.created_at.desc()
    ).all()
    return _build_ai_update_log(observations)


@router.put("/{char_id}", response_model=CharacterOut)
def update_character(char_id: int, body: CharacterUpdate, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(char, k, v)
    char.version += 1
    char.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(char)
    return char


@router.delete("/{char_id}")
def delete_character(char_id: int, db: Session = Depends(get_db)):
    char = db.get(Character, char_id)
    if not char:
        raise HTTPException(404, "角色不存在")
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
            {"id": char.id, "name": char.name, "role": char.role or ""}
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
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f"attachment; filename=btb-export-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"},
    )


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
        )
        db.add(obs)
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
        status="approved",
        reviewed_at=datetime.utcnow(),
    )
    db.add(obs)
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
    obs.status = "approved"
    obs.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(obs)
    return obs


@router.delete("/{char_id}/behavior-patterns/{obs_id}")
def delete_behavior_pattern(char_id: int, obs_id: int, db: Session = Depends(get_db)):
    obs = db.get(CharacterObservation, obs_id)
    if not obs or obs.character_id != char_id or obs.field != "behavior_pattern":
        raise HTTPException(404, "行为模式不存在")
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
    event = CharacterEvent(**body.model_dump())
    event.character_id = char_id
    db.add(event)
    db.commit()
    db.refresh(event)
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
    # 检查是否已存在
    existing = db.query(Relationship).filter_by(
        source_id=body.source_id, target_id=body.target_id
    ).first()
    if existing:
        raise HTTPException(400, "关系已存在")
    rel = Relationship(**body.model_dump(), history=[])
    db.add(rel)
    db.commit()
    db.refresh(rel)
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
