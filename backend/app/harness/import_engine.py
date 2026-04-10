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


def chunk_text(content_text: str, chunk_size: int = 2400, overlap: int = 240) -> list[str]:
    text = content_text or ""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end]
        if end < len(text):
            split_pos = max(chunk.rfind("\n"), chunk.rfind("。"), chunk.rfind("！"), chunk.rfind("？"))
            if split_pos > int(chunk_size * 0.55):
                end = start + split_pos + 1
                chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


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


def parse_dialogue_chunks(content_text: str) -> dict[str, Any]:
    chunks = chunk_text(content_text, chunk_size=3200, overlap=180)
    merged_units = []
    characters = {}
    seen_signatures = set()
    source_index = 1
    previous_speaker = ""
    for chunk in chunks:
        parsed = parse_dialogue_lines(chunk)
        for item in parsed.get("characters", []):
            name = item.get("name", "")
            if name and name not in characters:
                characters[name] = item
        for unit in parsed.get("interaction_units", []):
            signature = ((unit.get("speaker") or "").strip(), (unit.get("content") or "").strip())
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            normalized = dict(unit)
            receiver = (normalized.get("receiver") or "").strip()
            speaker = (normalized.get("speaker") or "").strip()
            if not receiver and previous_speaker and previous_speaker != speaker:
                normalized["receiver"] = previous_speaker
                normalized["receiver_confidence"] = max(float(normalized.get("receiver_confidence") or 0.0), 0.65)
                normalized["receiver_state"] = "inferred"
            normalized["source_line_index"] = source_index
            merged_units.append(normalized)
            previous_speaker = speaker or previous_speaker
            source_index += 1
    return {
        "characters": list(characters.values()),
        "interaction_units": merged_units,
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


def parse_narrative_chunks(content_text: str) -> dict[str, Any]:
    chunks = chunk_text(content_text, chunk_size=2600, overlap=220)
    characters = {}
    events = []
    turning_points = []
    main_conflict = ""
    for idx, chunk in enumerate(chunks[:12], start=1):
        parsed = parse_narrative_content(chunk)
        for item in parsed.get("characters", []):
            name = item.get("name", "")
            if name and name not in characters:
                characters[name] = item
        for event in parsed.get("events", []):
            summary = (event.get("summary") or "").strip()
            if summary and summary not in {e.get("summary") for e in events}:
                events.append(event)
        plot_summary = parsed.get("plot_summary", {}) or {}
        if plot_summary.get("main_conflict") and not main_conflict:
            main_conflict = plot_summary.get("main_conflict", "")
        for point in plot_summary.get("turning_points", []) or []:
            if point and point not in turning_points:
                turning_points.append(point)
    names = list(characters.keys())
    relationship_path = ""
    if len(names) >= 2:
        relationship_path = f"{names[0]} 与 {names[1]} 在多段叙事中持续互动"
    elif len(names) == 1:
        relationship_path = f"{names[0]} 是当前叙事中的核心行动者"
    return {
        "characters": list(characters.values()),
        "interaction_units": [],
        "events": events[:30],
        "relationships": [],
        "plot_summary": {
            "main_conflict": main_conflict,
            "relationship_path": relationship_path,
            "turning_points": turning_points[:5],
        },
    }


async def safe_ai_import_parse(file_type: str, content_text: str) -> tuple[dict[str, Any], str]:
    base_result = parse_dialogue_lines(content_text) if file_type == "dialogue" else parse_narrative_content(content_text)
    candidate_payloads = build_import_ai_candidate_payloads(file_type, content_text, base_result)
    last_error = ""
    content_length = len((content_text or "").strip())
    timeout_seconds = 270.0
    if content_length > 12000:
        timeout_seconds = 110.0
    elif content_length > 6000:
        timeout_seconds = 90.0
    for payload in candidate_payloads:
        try:
            result = await asyncio.wait_for(
                orchestrator.parse_import_content(file_type, payload),
                timeout=timeout_seconds,
            )
            if isinstance(result, dict) and any(result.get(key) for key in ("characters", "interaction_units", "events", "relationships", "plot_summary")):
                return result, ""
            last_error = "AI 解析结果格式异常"
        except asyncio.TimeoutError:
            return {}, f"AI 解析响应超时（等待上限 {int(timeout_seconds)} 秒），已停止本次 AI 增强并切换为基础规则解析。"
        except Exception as exc:
            last_error = str(exc).strip() or exc.__class__.__name__
            normalized_error = last_error.lower()
            if "timeouterror" in normalized_error or "timed out" in normalized_error or "timeout" in normalized_error:
                return {}, f"AI 解析响应超时（等待上限 {int(timeout_seconds)} 秒），已停止本次 AI 增强并切换为基础规则解析。"
            if (
                "402" in normalized_error
                or "payment required" in normalized_error
                or "insufficient balance" in normalized_error
            ):
                return {}, "DeepSeek 余额不足，已自动跳过 AI 增强，当前展示基础规则解析结果。"
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
    normalized["character_profiles"] = normalized.get("character_profiles") if isinstance(normalized.get("character_profiles"), (list, dict)) else {}
    return normalized


def build_text_windows(content_text: str, window_size: int = 1200) -> list[str]:
    text = "\n".join(line.strip() for line in (content_text or "").splitlines() if line.strip())
    if not text:
        return []
    if len(text) <= window_size:
        return [text]
    middle_start = max(0, len(text) // 2 - window_size // 2)
    windows = [
        text[:window_size],
        text[middle_start:middle_start + window_size],
        text[-window_size:],
    ]
    result = []
    seen = set()
    for item in windows:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def build_import_ai_candidate_payloads(file_type: str, content_text: str, base_result: dict[str, Any]) -> list[str]:
    candidate_payloads = []
    text_windows = build_text_windows(content_text, window_size=1200)
    text_snippet = "\n\n---片段分隔---\n\n".join(text_windows)[:4200]
    base_characters = base_result.get("characters", [])[:6]
    base_units = base_result.get("interaction_units", [])[:18]
    base_events = base_result.get("events", [])[:8]
    compact_structure = {
        "file_type": file_type,
        "analysis_scope": "请优先输出完整且闭合的紧凑 JSON；若信息很多，保留最核心角色、事件和关系，不要把结果写得过长。",
        "characters": [
            {
                "name": item.get("name", ""),
                "role": item.get("role", ""),
                "status": item.get("status", ""),
            }
            for item in base_characters
        ],
        "interaction_units": [
            {
                "source_line_index": item.get("source_line_index", index),
                "speaker": item.get("speaker", ""),
                "receiver": item.get("receiver", ""),
                "content": (item.get("content", "") or "")[:120],
            }
            for index, item in enumerate(base_units, start=1)
        ],
        "events": [
            {
                "actor": item.get("actor", ""),
                "action": item.get("action", ""),
                "participants": item.get("participants", []),
                "summary": (item.get("summary", "") or "")[:120],
            }
            for item in base_events
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
                for item in base_characters
            ),
            "规则解析交互:\n" + "\n".join(dialogue_excerpt),
            "规则解析事件:\n" + "\n".join(event_excerpt),
        ]
        if block.strip()
    )
    should_add_fallback_payloads = (
        len(base_characters) <= 1
        or len(base_units) <= 4
        or (not base_events and file_type == "narrative")
    )
    if should_add_fallback_payloads and secondary_payload and secondary_payload not in candidate_payloads:
        candidate_payloads.append(secondary_payload[:6500])
    if should_add_fallback_payloads and text_snippet and text_snippet not in candidate_payloads:
        candidate_payloads.append(text_snippet[:4200])
    return candidate_payloads


def build_psychological_label(unit: dict[str, Any]) -> str:
    speaker = unit.get("speaker") or "未知发言者"
    receiver = unit.get("receiver") or "待推断"
    intent = unit.get("intent") or {}
    strategy = unit.get("strategy") or {}
    emotion = unit.get("emotion") or {}
    confidence_values = [
        float(intent.get("confidence") or 0.0),
        float(strategy.get("confidence") or 0.0),
        float(emotion.get("confidence") or 0.0),
    ]
    strong_confidences = [value for value in confidence_values if value > 0]
    if strong_confidences and (sum(strong_confidences) / len(strong_confidences)) < 0.6:
        return ""
    parts = []
    if (intent.get("value") or "").strip():
        parts.append(f"意图:{intent['value'].strip()}")
    if (strategy.get("value") or "").strip():
        parts.append(f"策略:{strategy['value'].strip()}")
    if (emotion.get("value") or "").strip():
        parts.append(f"情绪:{emotion['value'].strip()}")
    if not parts:
        return ""
    return f"[{speaker} → {receiver} : {' / '.join(parts[:3])}]"


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
        patterns = []
        for value in dict.fromkeys([value for value in strategy_values if value]):
            related_examples = [
                (unit.get("content") or "").strip()
                for unit in related_units
                if ((unit.get("strategy") or {}).get("value") or "").strip() == value
            ]
            joined_text = " ".join(filter(None, [value, *related_examples[:2]]))
            category = classify_behavior_pattern_category(joined_text)
            patterns.append(
                {
                    "name": value,
                    "category": category,
                    "confidence": round(min(0.98, 0.62 + len(related_examples) * 0.08), 2),
                    "trigger": "被挑战时" if any("?" in example or "？" in example for example in related_examples) else "互动过程中",
                    "example": (related_examples[0] if related_examples else "")[:80],
                    "count": len(related_examples),
                }
            )
        patterns = patterns[:5]
        weak_traits = list(dict.fromkeys([value for value in intent_values if value]))[:3]
        summary[name] = {
            "traits": traits,
            "weak_traits": weak_traits,
            "behavior_patterns": patterns,
            "behavior_pattern_groups": build_behavior_pattern_groups(patterns),
        }
    return summary


def classify_behavior_pattern_category(content: str) -> str:
    text = (content or "").strip()
    if any(keyword in text for keyword in ("贬低", "挑衅", "威胁", "压制", "讽刺", "逼迫", "攻击", "施压", "羞辱")):
        return "攻击型行为"
    if any(keyword in text for keyword in ("回避", "防御", "沉默", "退让", "解释", "自保", "逃避", "转移", "封闭")):
        return "防御型行为"
    return "互动策略"


def build_behavior_pattern_groups(patterns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "攻击型行为": [],
        "防御型行为": [],
        "互动策略": [],
    }
    for pattern in patterns or []:
        category = (pattern.get("category") or "").strip() or classify_behavior_pattern_category(
            " ".join(
                filter(
                    None,
                    [
                        pattern.get("name", ""),
                        pattern.get("trigger", ""),
                        pattern.get("example", ""),
                    ],
                )
            )
        )
        groups.setdefault(category, [])
        groups[category].append(
            {
                "label": (pattern.get("name") or "").strip(),
                "confidence": round(float(pattern.get("confidence") or 0.0), 2),
                "trigger": (pattern.get("trigger") or "").strip() or None,
                "example": (pattern.get("example") or "").strip() or None,
                "source": "AI导入解析",
            }
        )
    return groups


def _top_values(values: list[str], limit: int = 3) -> list[str]:
    ordered = []
    seen = set()
    for value in values:
        normalized = (value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered[:limit]


def _blank_trait() -> dict[str, Any]:
    return {"name": None, "intensity": None, "evidence_count": 0}


def _blank_pattern() -> dict[str, Any]:
    return {"category": None, "pattern": None, "trigger": None, "goal": None, "frequency": 0, "confidence": 0.0}


def _blank_motivation() -> dict[str, Any]:
    return {"motivation": None, "priority": 0, "evidence": []}


def _blank_weakness() -> dict[str, Any]:
    return {"weakness": None, "type": None, "evidence": []}


def _blank_relationship() -> dict[str, Any]:
    return {"target": None, "type": None, "intensity": 0.0, "emotional_polarity": 0.0, "key_events": [], "evidence_count": 0}


def _blank_event(index: int) -> dict[str, Any]:
    return {"event_id": f"event_{index}", "type": None, "summary": None, "participants": [], "impact": None, "emotional_weight": 0.0}


def infer_speech_style(related_units: list[dict[str, Any]]) -> dict[str, Any]:
    contents = [(unit.get("content") or "").strip() for unit in related_units if (unit.get("content") or "").strip()]
    tone = []
    structure = []
    features = []
    examples = [content[:60] for content in contents[:3]]
    if contents:
        avg_length = sum(len(content) for content in contents) / max(1, len(contents))
        if avg_length <= 12:
            structure.append("短句")
        elif avg_length >= 30:
            structure.append("长句")
        else:
            structure.append("直接回应")
        joined = "".join(contents)
        if sum("?" in content or "？" in content for content in contents) >= max(1, len(contents) // 3):
            features.append("反问")
        if any(keyword in joined for keyword in ("闭嘴", "废物", "蠢", "别装", "少来", "没资格")):
            tone.append("攻击性")
            features.append("轻蔑表达")
        if any(keyword in joined for keyword in ("呵", "哦", "行啊", "真行", "当然")):
            tone.append("讽刺")
        if any(keyword in joined for keyword in ("也许", "可能", "要不", "是不是")):
            tone.append("试探")
        if not tone:
            tone.append("克制" if avg_length <= 18 else "直接")
    return {
        "tone": _top_values(tone, limit=3),
        "structure": _top_values(structure, limit=3),
        "features": _top_values(features, limit=4),
        "examples": examples,
    }


def _normalize_profile_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def normalize_strict_character_profile(profile: dict[str, Any], fallback_name: str = "") -> dict[str, Any]:
    basic_info = profile.get("basic_info") if isinstance(profile.get("basic_info"), dict) else {}
    personality_model = profile.get("personality_model") if isinstance(profile.get("personality_model"), dict) else {}
    speech_style = profile.get("speech_style") if isinstance(profile.get("speech_style"), dict) else {}
    normalized = {
        "character_name": (profile.get("character_name") or fallback_name or "").strip(),
        "source": (profile.get("source") or "imported_text"),
        "confidence_overall": round(float(profile.get("confidence_overall") or 0.0), 2),
        "basic_info": {
            "identity": basic_info.get("identity", None),
            "background": basic_info.get("background", None),
            "tags": basic_info.get("tags") if isinstance(basic_info.get("tags"), list) else [],
            "certainty": round(float(basic_info.get("certainty") or 0.0), 2),
        },
        "personality_model": {
            "traits": [],
            "emotional_patterns": [],
        },
        "behavior_patterns": [],
        "core_motivation": [],
        "core_weakness": [],
        "speech_style": {
            "tone": speech_style.get("tone") if isinstance(speech_style.get("tone"), list) else [],
            "structure": speech_style.get("structure") if isinstance(speech_style.get("structure"), list) else [],
            "features": speech_style.get("features") if isinstance(speech_style.get("features"), list) else [],
            "examples": speech_style.get("examples") if isinstance(speech_style.get("examples"), list) else [],
        },
        "relationships": [],
        "event_timeline": [],
    }
    for item in personality_model.get("traits") if isinstance(personality_model.get("traits"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["personality_model"]["traits"].append(
            {
                "name": item.get("name", None),
                "intensity": None if item.get("intensity") is None else round(float(item.get("intensity") or 0.0), 2),
                "evidence_count": int(item.get("evidence_count") or 0),
            }
        )
    while len(normalized["personality_model"]["traits"]) < 2:
        normalized["personality_model"]["traits"].append(_blank_trait())
    for item in personality_model.get("emotional_patterns") if isinstance(personality_model.get("emotional_patterns"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["personality_model"]["emotional_patterns"].append(
            {
                "pattern": item.get("pattern", None),
                "trigger": item.get("trigger", None),
                "response": item.get("response", None),
            }
        )
    for item in profile.get("behavior_patterns") if isinstance(profile.get("behavior_patterns"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["behavior_patterns"].append(
            {
                "category": item.get("category", None),
                "pattern": item.get("pattern", None),
                "trigger": item.get("trigger", None),
                "goal": item.get("goal", None),
                "frequency": int(item.get("frequency") or 0),
                "confidence": round(float(item.get("confidence") or 0.0), 2),
            }
        )
    if not normalized["behavior_patterns"]:
        normalized["behavior_patterns"] = [_blank_pattern()]
    for item in profile.get("core_motivation") if isinstance(profile.get("core_motivation"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["core_motivation"].append(
            {
                "motivation": item.get("motivation", None),
                "priority": int(item.get("priority") or 0),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            }
        )
    if not normalized["core_motivation"]:
        normalized["core_motivation"] = [_blank_motivation()]
    for item in profile.get("core_weakness") if isinstance(profile.get("core_weakness"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["core_weakness"].append(
            {
                "weakness": item.get("weakness", None),
                "type": item.get("type", None),
                "evidence": item.get("evidence") if isinstance(item.get("evidence"), list) else [],
            }
        )
    if not normalized["core_weakness"]:
        normalized["core_weakness"] = [_blank_weakness()]
    for item in profile.get("relationships") if isinstance(profile.get("relationships"), list) else []:
        if not isinstance(item, dict):
            continue
        normalized["relationships"].append(
            {
                "target": item.get("target", None),
                "type": item.get("type", None),
                "intensity": round(float(item.get("intensity") or 0.0), 2),
                "emotional_polarity": round(float(item.get("emotional_polarity") or 0.0), 2),
                "key_events": item.get("key_events") if isinstance(item.get("key_events"), list) else [],
                "evidence_count": int(item.get("evidence_count") or 0),
            }
        )
    if not normalized["relationships"]:
        normalized["relationships"] = [_blank_relationship()]
    for index, item in enumerate(profile.get("event_timeline") if isinstance(profile.get("event_timeline"), list) else [], start=1):
        if not isinstance(item, dict):
            continue
        normalized["event_timeline"].append(
            {
                "event_id": item.get("event_id") or f"event_{index}",
                "type": item.get("type", None),
                "summary": item.get("summary", None),
                "participants": item.get("participants") if isinstance(item.get("participants"), list) else [],
                "impact": item.get("impact", None),
                "emotional_weight": round(float(item.get("emotional_weight") or 0.0), 2),
            }
        )
    while len(normalized["event_timeline"]) < 5:
        normalized["event_timeline"].append(_blank_event(len(normalized["event_timeline"]) + 1))
    return normalized


def build_character_profiles(parsed: dict[str, Any]) -> dict[str, Any]:
    profiles = {}
    character_lookup = {
        (item.get("name") or "").strip(): item
        for item in parsed.get("characters", [])
        if (item.get("name") or "").strip()
    }
    ai_profiles = {
        (item.get("character_name") or "").strip(): item
        for item in _normalize_profile_list(parsed.get("character_profiles"))
        if (item.get("character_name") or "").strip()
    }
    relationship_lookup: dict[str, list[dict[str, Any]]] = {}
    for relation in parsed.get("relationships", []) or []:
        source = (relation.get("source") or "").strip()
        target = (relation.get("target") or "").strip()
        if not source or not target:
            continue
        relationship_lookup.setdefault(source, []).append(relation)
    event_lookup: dict[str, list[dict[str, Any]]] = {}
    for event in parsed.get("events", []) or []:
        participants = _top_values([event.get("actor", "")] + list(event.get("participants") or []), limit=8)
        for participant in participants:
            event_lookup.setdefault(participant, []).append(event)
    modeling = parsed.get("character_modeling") or {}
    for name, character in character_lookup.items():
        if name in ai_profiles:
            profiles[name] = normalize_strict_character_profile(ai_profiles[name], fallback_name=name)
            continue
        model = modeling.get(name) or {}
        related_units = [unit for unit in parsed.get("interaction_units", []) if (unit.get("speaker") or "").strip() == name]
        speech_style = infer_speech_style(related_units)
        traits = []
        trait_candidates = _top_values(list(character.get("personality_tags") or []) + list(model.get("traits") or []), limit=4)
        for index, value in enumerate(trait_candidates[:2], start=1):
            evidence_count = max(2, sum(1 for unit in related_units if value and value in (((unit.get("intent") or {}).get("value") or "") + ((unit.get("strategy") or {}).get("value") or "") + (unit.get("content") or ""))))
            traits.append({"name": value, "intensity": round(max(0.55, min(0.95, 0.45 + evidence_count * 0.08)), 2), "evidence_count": evidence_count})
        while len(traits) < 2:
            traits.append(_blank_trait())
        emotional_patterns = []
        emotion_values = _top_values([((unit.get("emotion") or {}).get("value") or "") for unit in related_units], limit=3)
        for value in emotion_values:
            examples = [unit for unit in related_units if ((unit.get("emotion") or {}).get("value") or "").strip() == value]
            emotional_patterns.append(
                {
                    "pattern": f"表层呈现{value}",
                    "trigger": (examples[0].get("content", "")[:40] if examples else None),
                    "response": (((examples[0].get("strategy") or {}).get("value") or "") if examples else None) or None,
                }
            )
        behavior_patterns = []
        for item in model.get("behavior_patterns", []) or []:
            if not isinstance(item, dict):
                continue
            frequency = int(item.get("count") or 0)
            if frequency < 2:
                continue
            pattern_name = (item.get("name") or "").strip()
            behavior_patterns.append(
                {
                    "category": item.get("category") or classify_behavior_pattern_category(pattern_name),
                    "pattern": pattern_name or None,
                    "trigger": (item.get("trigger") or "").strip() or None,
                    "goal": (((item.get("name") or "").strip()) or None),
                    "frequency": frequency,
                    "confidence": round(float(item.get("confidence") or 0.0), 2),
                }
            )
        if not behavior_patterns:
            behavior_patterns = [_blank_pattern()]
        core_motivation = []
        motivation_candidates = _top_values([((unit.get("intent") or {}).get("value") or "") for unit in related_units], limit=2)
        for index, value in enumerate(motivation_candidates, start=1):
            evidence = [(unit.get("content") or "").strip()[:60] for unit in related_units if ((unit.get("intent") or {}).get("value") or "").strip() == value][:2]
            if len(evidence) >= 2:
                core_motivation.append({"motivation": value, "priority": index, "evidence": evidence})
        if not core_motivation:
            core_motivation = [_blank_motivation()]
        core_weakness = []
        weakness_candidates = _top_values(list(model.get("weak_traits") or []), limit=2)
        for value in weakness_candidates:
            evidence = [(unit.get("content") or "").strip()[:60] for unit in related_units if value and value in (((unit.get("emotion") or {}).get("value") or "") + (unit.get("content") or ""))][:2]
            if len(evidence) >= 2:
                core_weakness.append({"weakness": value, "type": "emotional", "evidence": evidence})
        if not core_weakness:
            core_weakness = [_blank_weakness()]
        relationships = []
        for relation in relationship_lookup.get(name, []):
            relationships.append(
                {
                    "target": (relation.get("target") or "").strip() or None,
                    "type": (relation.get("rel_type") or "neutral").strip() or "neutral",
                    "intensity": round(float(relation.get("strength") or 0.0), 2),
                    "emotional_polarity": round(float(relation.get("sentiment") or 0.0), 2),
                    "key_events": _top_values([(relation.get("description") or "").strip()], limit=2),
                    "evidence_count": max(1, len(_top_values([(relation.get("description") or "").strip()], limit=2))),
                }
            )
        if not relationships:
            relationships = [_blank_relationship()]
        event_timeline = []
        for index, event in enumerate(event_lookup.get(name, [])[:8], start=1):
            event_type = "relationship" if len(event.get("participants") or []) >= 2 else "action"
            event_timeline.append(
                {
                    "event_id": f"{name}-{index}",
                    "type": event_type,
                    "summary": (event.get("summary") or "").strip() or None,
                    "participants": _top_values(list(event.get("participants") or []) + [event.get("actor", "")], limit=6),
                    "impact": (event.get("action") or "").strip() or None,
                    "emotional_weight": 0.85 if event_type == "relationship" else 0.65,
                }
            )
        while len(event_timeline) < 5:
            event_timeline.append(_blank_event(len(event_timeline) + 1))
        profiles[name] = normalize_strict_character_profile(
            {
                "character_name": name,
                "source": "imported_text",
                "confidence_overall": round(max([float(character.get("confidence") or 0.0)] + [float(item.get("confidence") or 0.0) for item in model.get("behavior_patterns", []) if isinstance(item, dict)] + [0.58]), 2),
                "basic_info": {
                    "identity": (character.get("role") or "").strip() or None,
                    "background": (character.get("background") or "").strip() or None,
                    "tags": _top_values(list(character.get("personality_tags") or []), limit=6),
                    "certainty": round(float(character.get("confidence") or 0.0), 2),
                },
                "personality_model": {
                    "traits": traits,
                    "emotional_patterns": emotional_patterns,
                },
                "behavior_patterns": behavior_patterns,
                "core_motivation": core_motivation,
                "core_weakness": core_weakness,
                "speech_style": speech_style,
                "relationships": relationships,
                "event_timeline": event_timeline,
            },
            fallback_name=name,
        )
    return profiles


def finalize_import_preview(
    parsed: dict[str, Any],
    existing_characters: list[dict],
    content_text: str,
    detected_type: str,
    warning_message: str = "",
    include_character_profiles: bool = True,
) -> dict[str, Any]:
    parsed = normalize_import_result(parsed)
    for index, unit in enumerate(parsed.get("interaction_units", []), start=1):
        unit["source_line_index"] = unit.get("source_line_index") or index
        unit["psychological_label"] = build_psychological_label(unit)
    if not parsed.get("relationships"):
        parsed["relationships"] = infer_relationships_from_units(parsed.get("interaction_units", []))
    parsed["pseudo_conversation"] = build_pseudo_conversation(parsed.get("interaction_units", []))
    parsed["character_modeling"] = extract_character_modeling(parsed)
    parsed["character_profiles"] = build_character_profiles(parsed) if include_character_profiles else {}
    role_mappings = build_role_mappings(parsed.get("characters", []), existing_characters)
    parsed["role_mappings"] = role_mappings
    parsed["detected_type"] = detected_type
    parsed["source_text_snippet"] = content_text[:500]
    parsed["warning_message"] = warning_message
    parsed["profile_generation_mode"] = "lightweight" if not include_character_profiles else "ready"
    parsed["low_confidence_units"] = [
        unit for unit in parsed.get("interaction_units", [])
        if unit.get("receiver_confidence", 0) < 0.6
        or unit.get("intent", {}).get("confidence", 0) < 0.6
        or unit.get("strategy", {}).get("confidence", 0) < 0.6
        or unit.get("emotion", {}).get("confidence", 0) < 0.6
    ]
    return parsed


async def build_import_preview(
    filename: str,
    content_text: str,
    existing_characters: list[dict],
    enable_ai: bool = True,
    include_character_profiles: bool = True,
) -> dict[str, Any]:
    detected_type = detect_import_type(filename, content_text)
    warning_message = ""
    if detected_type == "structured":
        parsed = parse_structured_content(filename, content_text)
    elif detected_type == "dialogue":
        parsed = parse_dialogue_chunks(content_text)
        if enable_ai:
            llm_result, warning_message = await safe_ai_import_parse(detected_type, content_text)
            parsed = merge_ai_parse_result(parsed, llm_result)
    else:
        parsed = parse_narrative_chunks(content_text)
        if enable_ai:
            llm_result, warning_message = await safe_ai_import_parse(detected_type, content_text)
            parsed = merge_ai_parse_result(parsed, llm_result)

    return finalize_import_preview(
        parsed,
        existing_characters,
        content_text,
        detected_type,
        warning_message,
        include_character_profiles=include_character_profiles,
    )


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
