from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .orchestrator import orchestrator

try:
    from docx import Document
except Exception:
    Document = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


DIALOGUE_PATTERNS = [
    re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z0-9_·\-\s]{1,30})[:：]\s*(.+?)\s*$"),
    re.compile(r"^\s*\[([\u4e00-\u9fa5A-Za-z0-9_·\-\s]{1,30})\]\s*(.+?)\s*$"),
]

NARRATIVE_SPEAKER_PATTERN = re.compile(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·\-]{1,11})(?:说|问|回答|回应|表示|想到|看着|盯着|告诉|喊道)")


def detect_import_type(filename: str, content_text: str) -> str:
    suffix = Path(filename).suffix.lower()
    has_dialogue_marker = any(
        any(dialogue_pattern.match(line.strip()) for dialogue_pattern in DIALOGUE_PATTERNS)
        for line in content_text.splitlines() if line.strip()
    )
    if suffix in {".json", ".csv"}:
        return "structured"
    if suffix in {".md", ".txt", ".pdf", ".docx"}:
        if has_dialogue_marker:
            return "dialogue"
        return "narrative"
    if has_dialogue_marker:
        return "dialogue"
    return "narrative"


async def extract_text_from_file(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".json", ".csv"}:
        return content.decode("utf-8", errors="ignore")
    if suffix == ".docx":
        if Document is None:
            raise ValueError("当前环境缺少 python-docx，无法解析 DOCX")
        doc = Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    if suffix == ".pdf":
        if PdfReader is None:
            raise ValueError("当前环境缺少 pypdf，无法解析 PDF")
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"暂不支持的文件类型：{suffix}")


def parse_structured_content(filename: str, content_text: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        data = json.loads(content_text)
        return {
            "characters": data.get("characters", []),
            "interaction_units": data.get("interaction_units", []),
            "events": data.get("events", []),
            "relationships": data.get("relationships", []),
            "plot_summary": data.get("plot_summary", {}),
        }

    rows = list(csv.DictReader(io.StringIO(content_text)))
    characters = {}
    interaction_units = []
    events = []
    for idx, row in enumerate(rows, start=1):
        speaker = (row.get("speaker") or row.get("角色") or row.get("name") or "").strip()
        content = (row.get("content") or row.get("文本") or row.get("message") or "").strip()
        if speaker:
            characters.setdefault(
                speaker,
                {
                    "name": speaker,
                    "role": row.get("role", "") or "",
                    "background": "",
                    "personality_tags": [],
                    "status": "new",
                    "confidence": 0.9,
                },
            )
        if speaker and content:
            interaction_units.append(
                {
                    "speaker": speaker,
                    "receiver": (row.get("receiver") or "").strip(),
                    "receiver_confidence": 0.6 if row.get("receiver") else 0.0,
                    "receiver_state": "confirmed" if row.get("receiver") else "ambiguous",
                    "content": content,
                    "intent": {"value": (row.get("intent") or "").strip(), "confidence": 0.7, "state": "inferred"},
                    "strategy": {"value": (row.get("strategy") or "").strip(), "confidence": 0.7, "state": "inferred"},
                    "emotion": {"value": (row.get("emotion") or "").strip(), "confidence": 0.7, "state": "inferred"},
                    "interaction_type": {"value": (row.get("interaction_type") or "dialogue").strip(), "confidence": 0.8, "state": "inferred"},
                    "source_line_index": idx,
                }
            )
            events.append(
                {
                    "actor": speaker,
                    "action": "发言",
                    "time": row.get("time", "") or "",
                    "location": row.get("location", "") or "",
                    "participants": [speaker] + ([row["receiver"]] if row.get("receiver") else []),
                    "summary": content[:120],
                }
            )
    return {
        "characters": list(characters.values()),
        "interaction_units": interaction_units,
        "events": events,
        "relationships": [],
        "plot_summary": {},
    }


def parse_dialogue_lines(content_text: str) -> dict[str, Any]:
    units = []
    characters = {}
    lines = [line.strip() for line in content_text.splitlines() if line.strip()]
    previous_speaker = ""
    for idx, line in enumerate(lines, start=1):
        matched = None
        for pattern in DIALOGUE_PATTERNS:
            matched = pattern.match(line)
            if matched:
                break
        if not matched:
            continue
        speaker = matched.group(1).strip()
        content = matched.group(2).strip()
        if not speaker or not content:
            continue
        characters.setdefault(
            speaker,
            {
                "name": speaker,
                "role": "",
                "background": "",
                "personality_tags": [],
                "status": "new",
                "confidence": 0.9,
            },
        )
        receiver = previous_speaker if previous_speaker and previous_speaker != speaker else ""
        units.append(
            {
                "speaker": speaker,
                "receiver": receiver,
                "receiver_confidence": 0.72 if receiver else 0.0,
                "receiver_state": "inferred" if receiver else "ambiguous",
                "content": content,
                "intent": {"value": "", "confidence": 0.0, "state": "ambiguous"},
                "strategy": {"value": "", "confidence": 0.0, "state": "ambiguous"},
                "emotion": {"value": "", "confidence": 0.0, "state": "ambiguous"},
                "interaction_type": {"value": "dialogue", "confidence": 0.95, "state": "confirmed"},
                "source_line_index": idx,
            }
        )
        previous_speaker = speaker
    return {
        "characters": list(characters.values()),
        "interaction_units": units,
        "events": [],
        "relationships": [],
        "plot_summary": {},
    }


def parse_narrative_content(content_text: str) -> dict[str, Any]:
    paragraphs = [line.strip() for line in content_text.splitlines() if line.strip()]
    characters = {}
    events = []
    relationship_path = ""
    main_conflict = ""
    turning_points = []

    for idx, paragraph in enumerate(paragraphs[:20], start=1):
        paragraph_names = []
        for matched in NARRATIVE_SPEAKER_PATTERN.finditer(paragraph):
            name = matched.group(1).strip()
            if len(name) > 12:
                continue
            paragraph_names.append(name)
            characters.setdefault(
                name,
                {
                    "name": name,
                    "role": "",
                    "background": "",
                    "personality_tags": [],
                    "status": "inferred",
                    "confidence": 0.55,
                },
            )
        if paragraph and not main_conflict:
            main_conflict = paragraph[:120]
        if paragraph:
            events.append(
                {
                    "actor": paragraph_names[0] if paragraph_names else "叙述者",
                    "action": "叙述",
                    "time": "",
                    "location": "",
                    "participants": paragraph_names,
                    "summary": paragraph[:120],
                }
            )
        if idx in {1, max(1, min(len(paragraphs), 3)), max(1, min(len(paragraphs), 6))} and paragraph:
            turning_points.append(paragraph[:60])

    if len(characters) >= 2:
        names = list(characters.keys())[:2]
        relationship_path = f"{names[0]} 与 {names[1]} 围绕文本事件持续互动"
    elif len(characters) == 1:
        name = next(iter(characters))
        relationship_path = f"{name} 是当前文本中的核心行动者"

    return {
        "characters": list(characters.values()),
        "interaction_units": [],
        "events": events,
        "relationships": [],
        "plot_summary": {
            "main_conflict": main_conflict,
            "relationship_path": relationship_path,
            "turning_points": turning_points[:3],
        },
    }


async def safe_ai_import_parse(file_type: str, content_text: str) -> tuple[dict[str, Any], str]:
    base_result = parse_dialogue_lines(content_text) if file_type == "dialogue" else parse_narrative_content(content_text)
    candidate_payloads = build_import_ai_candidate_payloads(file_type, content_text, base_result)
    last_error = ""
    for payload in candidate_payloads:
        try:
            result = await asyncio.wait_for(
                orchestrator.parse_import_content(file_type, payload),
                timeout=60.0,
            )
            if isinstance(result, dict) and any(result.get(key) for key in ("characters", "interaction_units", "events", "relationships", "plot_summary")):
                return result, ""
            last_error = "AI 解析结果格式异常"
        except Exception as exc:
            last_error = str(exc).strip() or exc.__class__.__name__
    if last_error:
        return {}, f"AI 解析暂时不可用，已切换为基础规则解析。原因：{last_error[:120]}"
    return {}, "AI 解析暂时不可用，已切换为基础规则解析。"


def normalize_import_result(parsed: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(parsed or {})
    normalized["characters"] = normalized.get("characters") if isinstance(normalized.get("characters"), list) else []
    normalized["interaction_units"] = normalized.get("interaction_units") if isinstance(normalized.get("interaction_units"), list) else []
    normalized["events"] = normalized.get("events") if isinstance(normalized.get("events"), list) else []
    normalized["relationships"] = normalized.get("relationships") if isinstance(normalized.get("relationships"), list) else []
    normalized["plot_summary"] = normalized.get("plot_summary") if isinstance(normalized.get("plot_summary"), dict) else {}
    return normalized


def build_import_ai_candidate_payloads(file_type: str, content_text: str, base_result: dict[str, Any]) -> list[str]:
    candidate_payloads = []
    text_snippet = "\n".join(line.strip() for line in content_text.splitlines() if line.strip())[:2200]
    compact_structure = {
        "file_type": file_type,
        "characters": [
            {
                "name": item.get("name", ""),
                "role": item.get("role", ""),
                "status": item.get("status", ""),
            }
            for item in base_result.get("characters", [])[:20]
        ],
        "interaction_units": [
            {
                "source_line_index": item.get("source_line_index", index),
                "speaker": item.get("speaker", ""),
                "receiver": item.get("receiver", ""),
                "content": (item.get("content", "") or "")[:120],
            }
            for index, item in enumerate(base_result.get("interaction_units", [])[:30], start=1)
        ],
        "events": [
            {
                "actor": item.get("actor", ""),
                "action": item.get("action", ""),
                "participants": item.get("participants", []),
                "summary": (item.get("summary", "") or "")[:120],
            }
            for item in base_result.get("events", [])[:20]
        ],
        "text_snippet": text_snippet,
    }
    primary_payload = json.dumps(compact_structure, ensure_ascii=False)
    if primary_payload:
        candidate_payloads.append(primary_payload[:6000])
    dialogue_excerpt = []
    for index, item in enumerate(base_result.get("interaction_units", [])[:18], start=1):
        dialogue_excerpt.append(
            f"{index}. {item.get('speaker', '')} -> {item.get('receiver', '待推断')} : {(item.get('content', '') or '')[:80]}"
        )
    event_excerpt = []
    for index, item in enumerate(base_result.get("events", [])[:12], start=1):
        event_excerpt.append(
            f"{index}. {item.get('actor', '')} / {item.get('action', '')} / {(item.get('summary', '') or '')[:80]}"
        )
    secondary_payload = "\n".join(
        block for block in [
            f"文件类型: {file_type}",
            f"文本摘要:\n{text_snippet[:1500]}",
            "规则解析角色:\n" + "\n".join(
                f"- {item.get('name', '')}｜{item.get('role', '')}｜{item.get('status', '')}"
                for item in base_result.get("characters", [])[:20]
            ),
            "规则解析交互:\n" + "\n".join(dialogue_excerpt),
            "规则解析事件:\n" + "\n".join(event_excerpt),
        ]
        if block.strip()
    )
    if secondary_payload and secondary_payload not in candidate_payloads:
        candidate_payloads.append(secondary_payload[:4000])
    if text_snippet and text_snippet not in candidate_payloads:
        candidate_payloads.append(text_snippet[:2500])
    return candidate_payloads


def build_psychological_label(unit: dict[str, Any]) -> str:
    speaker = unit.get("speaker") or "未知发言者"
    receiver = unit.get("receiver") or "待推断"
    intent_value = ((unit.get("intent") or {}).get("value") or "").strip()
    strategy_value = ((unit.get("strategy") or {}).get("value") or "").strip()
    emotion_value = ((unit.get("emotion") or {}).get("value") or "").strip()
    operation = strategy_value or intent_value or emotion_value or "心理操作待定"
    return f"[{speaker} → {receiver} : {operation}]"


def infer_relationships_from_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relationship_map: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in units:
        speaker = (unit.get("speaker") or "").strip()
        receiver = (unit.get("receiver") or "").strip()
        if not speaker or not receiver or speaker == receiver:
            continue
        key = (speaker, receiver)
        item = relationship_map.setdefault(
            key,
            {
                "source": speaker,
                "target": receiver,
                "rel_type": "neutral",
                "strength": 0.25,
                "sentiment": 0.0,
                "description": "",
                "_count": 0,
            },
        )
        item["_count"] += 1
        intent_conf = float((unit.get("intent") or {}).get("confidence") or 0.35)
        receiver_conf = float(unit.get("receiver_confidence") or 0.35)
        item["strength"] = max(item["strength"], min(1.0, (intent_conf + receiver_conf) / 2))
        emotion_value = ((unit.get("emotion") or {}).get("value") or "").strip()
        if emotion_value in {"信任", "亲近", "依恋", "安心"}:
            item["sentiment"] = max(item["sentiment"], 0.45)
            item["rel_type"] = "friend"
        elif emotion_value in {"愤怒", "警惕", "防御", "怀疑"}:
            item["sentiment"] = min(item["sentiment"], -0.45)
            item["rel_type"] = "rival"
        item["description"] = build_psychological_label(unit)
    relationships = []
    for value in relationship_map.values():
        value.pop("_count", None)
        relationships.append(value)
    return relationships


def build_pseudo_conversation(units: list[dict[str, Any]]) -> dict[str, Any]:
    messages = []
    context_links = []
    interaction_flow = []
    history = []
    for index, unit in enumerate(units, start=1):
        context_window = [
            {
                "message_index": item["message_index"],
                "speaker": item["speaker"],
                "receiver": item["receiver"],
                "content": item["content"],
            }
            for item in history[-5:]
        ]
        message_item = {
            "message_index": index,
            "speaker": unit.get("speaker", ""),
            "receiver": unit.get("receiver", ""),
            "content": unit.get("content", ""),
            "receiver_confidence": unit.get("receiver_confidence", 0.0),
            "intent": unit.get("intent", {}),
            "strategy": unit.get("strategy", {}),
            "emotion": unit.get("emotion", {}),
            "psychological_label": unit.get("psychological_label", ""),
            "context_window": context_window,
        }
        messages.append(message_item)
        history.append(message_item)
        context_links.append(
            {
                "message_index": index,
                "previous_indexes": [item["message_index"] for item in context_window],
            }
        )
        interaction_flow.append(
            {
                "message_index": index,
                "speaker": unit.get("speaker", ""),
                "receiver": unit.get("receiver", ""),
                "interaction_type": (unit.get("interaction_type") or {}).get("value", ""),
            }
        )
    return {
        "messages": messages,
        "context_links": context_links,
        "interaction_flow": interaction_flow,
    }


def extract_character_modeling(parsed: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for character in parsed.get("characters", []):
        name = (character.get("name") or "").strip()
        if not name:
            continue
        related_units = [unit for unit in parsed.get("interaction_units", []) if unit.get("speaker") == name]
        strategy_values = [((unit.get("strategy") or {}).get("value") or "").strip() for unit in related_units]
        intent_values = [((unit.get("intent") or {}).get("value") or "").strip() for unit in related_units]
        traits = list(dict.fromkeys([tag for tag in (character.get("personality_tags") or []) if tag]))
        patterns = list(dict.fromkeys([value for value in strategy_values if value]))[:5]
        weak_traits = list(dict.fromkeys([value for value in intent_values if value]))[:3]
        summary[name] = {
            "traits": traits,
            "weak_traits": weak_traits,
            "behavior_patterns": patterns,
        }
    return summary


async def build_import_preview(filename: str, content_text: str, existing_characters: list[dict]) -> dict[str, Any]:
    detected_type = detect_import_type(filename, content_text)
    warning_message = ""
    if detected_type == "structured":
        parsed = parse_structured_content(filename, content_text)
    elif detected_type == "dialogue":
        parsed = parse_dialogue_lines(content_text)
        llm_result, warning_message = await safe_ai_import_parse(detected_type, content_text)
        parsed = merge_ai_parse_result(parsed, llm_result)
    else:
        parsed = parse_narrative_content(content_text)
        llm_result, warning_message = await safe_ai_import_parse(detected_type, content_text)
        parsed = merge_ai_parse_result(parsed, llm_result)

    parsed = normalize_import_result(parsed)
    for index, unit in enumerate(parsed.get("interaction_units", []), start=1):
        unit["source_line_index"] = unit.get("source_line_index") or index
        unit["psychological_label"] = build_psychological_label(unit)
    if not parsed.get("relationships"):
        parsed["relationships"] = infer_relationships_from_units(parsed.get("interaction_units", []))
    parsed["pseudo_conversation"] = build_pseudo_conversation(parsed.get("interaction_units", []))
    parsed["character_modeling"] = extract_character_modeling(parsed)
    role_mappings = build_role_mappings(parsed.get("characters", []), existing_characters)
    parsed["role_mappings"] = role_mappings
    parsed["detected_type"] = detected_type
    parsed["source_text_snippet"] = content_text[:500]
    parsed["warning_message"] = warning_message
    parsed["low_confidence_units"] = [
        unit for unit in parsed.get("interaction_units", [])
        if unit.get("receiver_confidence", 0) < 0.6
        or unit.get("intent", {}).get("confidence", 0) < 0.6
        or unit.get("strategy", {}).get("confidence", 0) < 0.6
        or unit.get("emotion", {}).get("confidence", 0) < 0.6
    ]
    return parsed


def merge_ai_parse_result(base_result: dict[str, Any], ai_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ai_result, dict):
        return base_result
    merged = dict(base_result)
    if ai_result.get("characters"):
        merged["characters"] = ai_result["characters"] if len(ai_result["characters"]) >= len(base_result.get("characters", [])) else _merge_characters(base_result.get("characters", []), ai_result["characters"])
    if ai_result.get("interaction_units"):
        merged["interaction_units"] = _merge_interaction_units(base_result.get("interaction_units", []), ai_result["interaction_units"])
    for key in ("events", "relationships", "plot_summary"):
        if ai_result.get(key):
            merged[key] = ai_result[key]
    return merged


def _merge_characters(base_characters: list[dict[str, Any]], ai_characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [dict(item) for item in base_characters]
    character_index = {(item.get("name") or "").strip(): idx for idx, item in enumerate(merged)}
    for ai_item in ai_characters:
        name = (ai_item.get("name") or "").strip()
        if not name:
            continue
        if name in character_index:
            idx = character_index[name]
            merged[idx].update({k: v for k, v in ai_item.items() if v not in ("", None, [], {})})
        else:
            character_index[name] = len(merged)
            merged.append(ai_item)
    return merged


def _merge_interaction_units(base_units: list[dict[str, Any]], ai_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not base_units:
        return ai_units
    merged = [dict(item) for item in base_units]
    index_by_source = {
        int(item.get("source_line_index") or idx + 1): idx
        for idx, item in enumerate(merged)
    }
    index_by_signature = {
        ((item.get("speaker") or "").strip(), (item.get("content") or "").strip()[:80]): idx
        for idx, item in enumerate(merged)
    }
    for ai_item in ai_units:
        source_line_index = int(ai_item.get("source_line_index") or 0)
        signature = ((ai_item.get("speaker") or "").strip(), (ai_item.get("content") or "").strip()[:80])
        target_idx = index_by_source.get(source_line_index)
        if target_idx is None:
            target_idx = index_by_signature.get(signature)
        if target_idx is None:
            merged.append(ai_item)
            continue
        target = merged[target_idx]
        for field in ("receiver", "receiver_confidence", "receiver_state", "content", "source_line_index"):
            value = ai_item.get(field)
            if value not in ("", None):
                target[field] = value
        for field in ("intent", "strategy", "emotion", "interaction_type"):
            value = ai_item.get(field)
            if isinstance(value, dict) and any(v not in ("", None, 0, 0.0, [], {}) for v in value.values()):
                target[field] = value
    return merged


def build_role_mappings(parsed_characters: list[dict], existing_characters: list[dict]) -> list[dict]:
    mappings = []
    for character in parsed_characters:
        name = (character.get("name") or "").strip()
        if not name:
            continue
        candidates = []
        for existing in existing_characters:
            score = 0
            if existing["name"] == name:
                score += 10
            elif existing["name"] in name or name in existing["name"]:
                score += 5
            role = existing.get("role") or ""
            if role and role == character.get("role"):
                score += 2
            if score > 0:
                candidates.append({"id": existing["id"], "name": existing["name"], "score": score})
        candidates.sort(key=lambda item: item["score"], reverse=True)
        status = "new"
        action = "create"
        resolved_name = name
        if candidates and candidates[0]["score"] >= 10:
            status = "confirmed"
            action = "link"
            resolved_name = candidates[0]["name"]
        elif candidates:
            status = "ambiguous"
            action = "link"
        mappings.append(
            {
                "original_name": name,
                "resolved_name": resolved_name,
                "status": status,
                "candidate_ids": [item["id"] for item in candidates[:5]],
                "action": action,
                "candidates": candidates[:5],
            }
        )
    return mappings
