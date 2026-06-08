from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from ..models.sql_models import (
    Character,
    CharacterEvent,
    EvidenceSpan,
    MemoryItem,
    Relationship,
)

logger = logging.getLogger(__name__)
CONF_DIR = Path(__file__).parent.parent / "conf"
CONFIG_FILE = CONF_DIR / "config.yaml"
ROOT_DIR = Path(__file__).resolve().parents[3]


def _load_graph_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    graph = config.get("graph") or {}
    bundled_home = graph.get("bundled_home") or ""
    if bundled_home:
        path = Path(bundled_home)
        if not path.is_absolute():
            graph["bundled_home"] = str((ROOT_DIR / path).resolve())
    return graph


class Neo4jGraphStore:
    def __init__(self) -> None:
        self.config = _load_graph_config()
        self.enabled = bool(self.config.get("enabled", False))
        self.uri = self.config.get("uri", "bolt://127.0.0.1:7687")
        self.username = self.config.get("username", "")
        self.password = self.config.get("password", "")
        self.database = self.config.get("database", "neo4j")
        self.bundled_home = Path(self.config.get("bundled_home", "") or "")
        self._driver = None
        self._graph_database = None
        self._driver_error = ""
        self._unavailable_until = 0.0

    def _load_graph_database(self):
        if self._graph_database is not None:
            return self._graph_database
        if self._driver_error:
            return None
        pandas_sentinel = object()
        original_pandas = sys.modules.get("pandas", pandas_sentinel)
        try:
            if "pandas" not in sys.modules:
                sys.modules["pandas"] = None
            from neo4j import GraphDatabase

            self._graph_database = GraphDatabase
            return self._graph_database
        except Exception as exc:  # pragma: no cover - optional runtime dependency
            self._driver_error = str(exc)
            logger.warning("Neo4j driver 加载失败: %s", exc)
            return None
        finally:
            if original_pandas is pandas_sentinel:
                sys.modules.pop("pandas", None)

    def available(self) -> bool:
        return self.enabled and self._load_graph_database() is not None

    def driver(self):
        if not self.available():
            return None
        if self._driver is None:
            auth = None
            if self.username or self.password:
                auth = (self.username, self.password)
            self._driver = self._load_graph_database().driver(
                self.uri,
                auth=auth,
                connection_timeout=2.0,
                max_connection_pool_size=4,
            )
        return self._driver

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None
        self._unavailable_until = 0.0

    def java_status(self) -> dict[str, Any]:
        java_home = os.environ.get("JAVA_HOME", "")
        java_from_home = Path(java_home) / "bin" / "java.exe" if java_home else None
        java_path = str(java_from_home) if java_from_home and java_from_home.exists() else shutil.which("java")
        if not java_path:
            candidates = sorted(Path("C:/Program Files/Microsoft").glob("jdk-17*/bin/java.exe"), reverse=True)
            if candidates:
                java_path = str(candidates[0])
                java_home = str(candidates[0].parent.parent)
        return {
            "available": bool(java_path),
            "java_path": java_path or "",
            "java_home": java_home,
            "required": "Neo4j 5.x 需要 Java 17+。",
        }

    def health(self) -> dict[str, Any]:
        if not self.available():
            return {
                "enabled": self.enabled,
                "available": False,
                "reason": self._driver_error or "neo4j driver 未安装或 graph.enabled=false",
                "java": self.java_status(),
            }
        try:
            with self.driver().session(database=self.database) as session:
                value = session.run("RETURN 1 AS ok").single()["ok"]
            return {
                "enabled": self.enabled,
                "available": True,
                "uri": self.uri,
                "database": self.database,
                "ok": value == 1,
                "java": self.java_status(),
            }
        except Exception as exc:
            return {
                "enabled": self.enabled,
                "available": False,
                "uri": self.uri,
                "database": self.database,
                "reason": str(exc),
                "java": self.java_status(),
            }

    def start_bundled(self) -> dict[str, Any]:
        if not self.bundled_home.exists():
            return {"ok": False, "message": f"Neo4j 目录不存在：{self.bundled_home}"}
        script = self.bundled_home / "bin" / "neo4j.bat"
        if not script.exists():
            return {"ok": False, "message": f"Neo4j 启动脚本不存在：{script}"}
        health = self.health()
        if health.get("available"):
            return {"ok": True, "message": "Neo4j 已在运行", "health": health}
        java = self.java_status()
        if not java.get("available"):
            return {
                "ok": False,
                "message": "未找到 java.exe，无法启动内置 Neo4j。请安装 Java 17+ 或设置 JAVA_HOME。",
                "java": java,
            }
        subprocess.Popen(
            ["cmd", "/c", str(script), "console"],
            cwd=str(self.bundled_home),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {"ok": True, "message": "已启动内置 Neo4j，通常需要数秒完成监听。"}

    def run_write(self, cypher: str, parameters: dict[str, Any] | None = None) -> bool:
        if not self.available():
            return False
        if time.time() < self._unavailable_until:
            return False
        try:
            with self.driver().session(database=self.database) as session:
                session.execute_write(lambda tx: tx.run(cypher, parameters or {}).consume())
            return True
        except Exception as exc:
            self._unavailable_until = time.time() + 30.0
            logger.warning("Neo4j 写入失败: %s", exc)
            return False

    def run_read(self, cypher: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self.available():
            return []
        if time.time() < self._unavailable_until:
            return []
        try:
            with self.driver().session(database=self.database) as session:
                result = session.execute_read(lambda tx: list(tx.run(cypher, parameters or {})))
            return [dict(record) for record in result]
        except Exception as exc:
            self._unavailable_until = time.time() + 30.0
            logger.warning("Neo4j 查询失败: %s", exc)
            return []

    def ensure_schema(self) -> bool:
        statements = [
            "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT memory_id IF NOT EXISTS FOR (n:Memory) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT relationship_id IF NOT EXISTS FOR (n:RelationshipFact) REQUIRE n.id IS UNIQUE",
        ]
        ok = True
        for statement in statements:
            ok = self.run_write(statement) and ok
        return ok

    def sync_character(self, char: Character | None) -> bool:
        if not char:
            return False
        return self.run_write(
            """
            MERGE (p:Person {id: $id})
            SET p.name = $name,
                p.role = $role,
                p.background = $background,
                p.personality_tags = $personality_tags,
                p.motivation = $motivation,
                p.weakness = $weakness,
                p.speaking_style = $speaking_style,
                p.version = $version
            """,
            {
                "id": char.id,
                "name": char.name,
                "role": char.role or "",
                "background": (char.background or "")[:1000],
                "personality_tags": char.personality_tags or [],
                "motivation": char.motivation or "",
                "weakness": char.weakness or "",
                "speaking_style": char.speaking_style or "",
                "version": char.version,
            },
        )

    def sync_relationship(self, rel: Relationship | None, source: Character | None = None, target: Character | None = None) -> bool:
        if not rel:
            return False
        if source:
            self.sync_character(source)
        if target:
            self.sync_character(target)
        return self.run_write(
            """
            MERGE (s:Person {id: $source_id})
            MERGE (t:Person {id: $target_id})
            MERGE (rf:RelationshipFact {id: $id})
            SET rf.rel_type = $rel_type,
                rf.strength = $strength,
                rf.sentiment = $sentiment,
                rf.description = $description,
                rf.updated_at = $updated_at
            MERGE (s)-[r:RELATES_TO]->(t)
            SET r.relationship_id = $id,
                r.rel_type = $rel_type,
                r.strength = $strength,
                r.sentiment = $sentiment,
                r.description = $description,
                r.updated_at = $updated_at
            MERGE (rf)-[:FROM]->(s)
            MERGE (rf)-[:TO]->(t)
            """,
            {
                "id": rel.id,
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "rel_type": rel.rel_type or "neutral",
                "strength": float(rel.strength or 0.0),
                "sentiment": float(rel.sentiment or 0.0),
                "description": rel.description or "",
                "updated_at": rel.updated_at.isoformat() if rel.updated_at else "",
            },
        )

    def sync_event(self, event: CharacterEvent | None, character: Character | None = None) -> bool:
        if not event:
            return False
        if character:
            self.sync_character(character)
        return self.run_write(
            """
            MERGE (e:Event {id: $id})
            SET e.title = $title,
                e.description = $description,
                e.event_date = $event_date,
                e.emotion_label = $emotion_label,
                e.importance = $importance
            WITH e
            MATCH (p:Person {id: $character_id})
            MERGE (e)-[:INVOLVES]->(p)
            MERGE (p)-[:HAS_EVENT]->(e)
            """,
            {
                "id": event.id,
                "character_id": event.character_id,
                "title": event.title,
                "description": event.description or "",
                "event_date": event.event_date or "",
                "emotion_label": event.emotion_label or "",
                "importance": int(event.importance or 0),
            },
        )

    def sync_evidence(self, evidence: EvidenceSpan | None) -> bool:
        if not evidence:
            return False
        return self.run_write(
            """
            MERGE (ev:Evidence {id: $id})
            SET ev.source_type = $source_type,
                ev.supports_type = $supports_type,
                ev.polarity = $polarity,
                ev.quote = $quote,
                ev.interpretation = $interpretation,
                ev.confidence = $confidence,
                ev.created_at = $created_at
            WITH ev
            OPTIONAL MATCH (p:Person {id: $character_id})
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
              MERGE (p)-[:HAS_EVIDENCE]->(ev)
            )
            """,
            {
                "id": evidence.id,
                "character_id": evidence.character_id,
                "source_type": evidence.source_type or "",
                "supports_type": evidence.supports_type or "",
                "polarity": evidence.polarity or "supports",
                "quote": evidence.quote or "",
                "interpretation": evidence.interpretation or "",
                "confidence": float(evidence.confidence or 0.0),
                "created_at": evidence.created_at.isoformat() if evidence.created_at else "",
            },
        )

    def sync_memory(self, memory: MemoryItem | None) -> bool:
        if not memory:
            return False
        return self.run_write(
            """
            MERGE (m:Memory {id: $id})
            SET m.memory_type = $memory_type,
                m.content = $content,
                m.confidence = $confidence,
                m.source = $source,
                m.status = $status,
                m.updated_at = $updated_at
            WITH m
            MATCH (p:Person {id: $character_id})
            MERGE (p)-[:HAS_MEMORY]->(m)
            WITH m
            UNWIND $evidence_ids AS evidence_id
            MATCH (ev:Evidence {id: evidence_id})
            MERGE (ev)-[:SUPPORTS_MEMORY]->(m)
            """,
            {
                "id": memory.id,
                "character_id": memory.character_id,
                "memory_type": memory.memory_type or "",
                "content": memory.content or "",
                "confidence": float(memory.confidence or 0.0),
                "source": memory.source or "",
                "status": memory.status or "active",
                "updated_at": memory.updated_at.isoformat() if memory.updated_at else "",
                "evidence_ids": memory.evidence_ids or [],
            },
        )

    def get_graph_context(self, speaker_id: int | None, listener_id: int | None, limit: int = 8) -> dict[str, Any]:
        if not speaker_id and not listener_id:
            return {}
        rows = self.run_read(
            """
            MATCH (p:Person)
            WHERE p.id IN $ids
            OPTIONAL MATCH (p)-[rel:RELATES_TO]->(other:Person)
            OPTIONAL MATCH (p)-[:HAS_MEMORY]->(m:Memory)
            OPTIONAL MATCH (p)-[:HAS_EVIDENCE]->(ev:Evidence)
            RETURN p {
              .id, .name, .role, .personality_tags, .motivation, .weakness
            } AS person,
            collect(DISTINCT {
              target_id: other.id,
              target_name: other.name,
              rel_type: rel.rel_type,
              strength: rel.strength,
              sentiment: rel.sentiment,
              description: rel.description
            })[0..$limit] AS relationships,
            collect(DISTINCT {
              id: m.id,
              memory_type: m.memory_type,
              content: m.content,
              confidence: m.confidence
            })[0..$limit] AS memories,
            collect(DISTINCT {
              id: ev.id,
              supports_type: ev.supports_type,
              quote: ev.quote,
              interpretation: ev.interpretation,
              confidence: ev.confidence
            })[0..$limit] AS evidence
            """,
            {"ids": [item for item in [speaker_id, listener_id] if item], "limit": limit},
        )
        return {"people": rows}


graph_store = Neo4jGraphStore()
