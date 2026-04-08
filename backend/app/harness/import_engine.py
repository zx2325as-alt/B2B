from __future__ import annotations

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


async def build_import_preview(filename: str, content_text: str, existing_characters: list[dict]) -> dict[str, Any]:
    detected_type = detect_import_type(filename, content_text)
    if detected_type == "structured":
        parsed = parse_structured_content(filename, content_text)
    elif detected_type == "dialogue":
        parsed = parse_dialogue_lines(content_text)
        llm_result = await orchestrator.parse_import_content(detected_type, content_text[:12000])
        parsed = merge_ai_parse_result(parsed, llm_result)
    else:
        parsed = await orchestrator.parse_import_content(detected_type, content_text[:12000])

    role_mappings = build_role_mappings(parsed.get("characters", []), existing_characters)
    parsed["role_mappings"] = role_mappings
    parsed["detected_type"] = detected_type
    parsed["source_text_snippet"] = content_text[:500]
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
    for key in ("characters", "interaction_units", "events", "relationships", "plot_summary"):
        if ai_result.get(key):
            merged[key] = ai_result[key]
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
