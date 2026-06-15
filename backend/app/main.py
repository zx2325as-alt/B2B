from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

from .models.sql_models import Base
from .api.deps import engine, SessionLocal
from .api import characters, chat
from .harness.graph_store import graph_store
from .services.relationships import merge_duplicate_relationships

def _configure_logging():
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    has_stream = any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    if not has_stream:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    backend_log = logs_dir / "backend.log"
    file_handler = RotatingFileHandler(
        backend_log,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    import_log = logs_dir / "import.log"
    import_handler = RotatingFileHandler(
        import_log,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    import_handler.setFormatter(formatter)
    import_logger = logging.getLogger("import")
    import_logger.setLevel(logging.INFO)
    import_logger.propagate = False
    if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(import_log) for h in import_logger.handlers):
        import_logger.addHandler(import_handler)
        import_logger.addHandler(logging.StreamHandler())
        for h in import_logger.handlers:
            h.setFormatter(formatter)

def _ensure_sqlite_columns():
    table_columns = {
        "conversations": {
            "is_readonly": "ALTER TABLE conversations ADD COLUMN is_readonly BOOLEAN DEFAULT 0",
            "source_import_file_id": "ALTER TABLE conversations ADD COLUMN source_import_file_id INTEGER",
            "active_branch_id": "ALTER TABLE conversations ADD COLUMN active_branch_id VARCHAR(80)",
            "active_branch_point_id": "ALTER TABLE conversations ADD COLUMN active_branch_point_id INTEGER",
            "participants": "ALTER TABLE conversations ADD COLUMN participants JSON",
            "context_summary": "ALTER TABLE conversations ADD COLUMN context_summary TEXT DEFAULT ''",
            "summary_until_index": "ALTER TABLE conversations ADD COLUMN summary_until_index INTEGER DEFAULT 0",
            "scene_brief": "ALTER TABLE conversations ADD COLUMN scene_brief TEXT DEFAULT ''",
            "self_name": "ALTER TABLE conversations ADD COLUMN self_name VARCHAR(100) DEFAULT ''",
        },
        "messages": {
            "message_index": "ALTER TABLE messages ADD COLUMN message_index INTEGER DEFAULT 0",
            "branch_id": "ALTER TABLE messages ADD COLUMN branch_id VARCHAR(80)",
            "receiver_id": "ALTER TABLE messages ADD COLUMN receiver_id INTEGER",
            "receiver_name": "ALTER TABLE messages ADD COLUMN receiver_name VARCHAR(100)",
            "intent": "ALTER TABLE messages ADD COLUMN intent VARCHAR(200)",
            "strategy": "ALTER TABLE messages ADD COLUMN strategy VARCHAR(200)",
            "emotion": "ALTER TABLE messages ADD COLUMN emotion VARCHAR(200)",
            "source_type": "ALTER TABLE messages ADD COLUMN source_type VARCHAR(20) DEFAULT 'chat'",
            "readonly": "ALTER TABLE messages ADD COLUMN readonly BOOLEAN DEFAULT 0",
            "analysis_json": "ALTER TABLE messages ADD COLUMN analysis_json JSON",
        },
        "import_files": {
            "version": "ALTER TABLE import_files ADD COLUMN version INTEGER DEFAULT 1",
            "model_used": "ALTER TABLE import_files ADD COLUMN model_used VARCHAR(100) DEFAULT 'ai-harness'",
        },
        "interaction_units": {
            "psychological_label": "ALTER TABLE interaction_units ADD COLUMN psychological_label VARCHAR(200) DEFAULT ''",
            "context_window": "ALTER TABLE interaction_units ADD COLUMN context_window JSON",
        },
        "character_observations": {
            "metadata_json": "ALTER TABLE character_observations ADD COLUMN metadata_json JSON",
        },
        "characters": {
            "aliases": "ALTER TABLE characters ADD COLUMN aliases JSON",
            "profile_json": "ALTER TABLE characters ADD COLUMN profile_json JSON",
        },
        "relationships": {
            "analysis_json": "ALTER TABLE relationships ADD COLUMN analysis_json JSON",
        },
        "character_events": {
            "psychological_impact": "ALTER TABLE character_events ADD COLUMN psychological_impact TEXT DEFAULT ''",
            "arc_marker": "ALTER TABLE character_events ADD COLUMN arc_marker BOOLEAN DEFAULT 0",
        },
        "memory_items": {
            "embedding": "ALTER TABLE memory_items ADD COLUMN embedding JSON",
        },
        "message_perspectives": {
            "stance": "ALTER TABLE message_perspectives ADD COLUMN stance VARCHAR(20) DEFAULT 'observer'",
            "suggested_reply": "ALTER TABLE message_perspectives ADD COLUMN suggested_reply TEXT DEFAULT ''",
        },
    }
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_messages_conv_branch ON messages (conversation_id, branch_id, message_index)",
        "CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages (parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_char_created ON evidence_spans (character_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_memory_char_status ON memory_items (character_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_observations_char_field ON character_observations (character_id, field)",
        "CREATE INDEX IF NOT EXISTS idx_conv_states_conv ON conversation_states (conversation_id, character_name)",
        "CREATE INDEX IF NOT EXISTS idx_perspectives_msg ON message_perspectives (message_id)",
        "CREATE INDEX IF NOT EXISTS idx_perspectives_viewer ON message_perspectives (viewer_character_id, conversation_id)",
    ]
    with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    conn.execute(text(ddl))
        for ddl in indexes:
            conn.execute(text(ddl))


def _recover_stuck_imports():
    """服务重启会杀掉 BackgroundTasks 中的导入任务，把卡在中间态的任务标记为可重试的失败态"""
    stuck_message = json.dumps(
        {
            "message": "服务重启导致任务中断，请重新提交导入。",
            "updated_at": datetime.utcnow().isoformat(),
        },
        ensure_ascii=False,
    )
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, status, metadata_json FROM import_files "
            "WHERE status IN ('queued', 'reviewing', 'processing', 'preview_processing')"
        )).fetchall()
        for row in rows:
            file_id, status, metadata_raw = row
            try:
                metadata = json.loads(metadata_raw) if metadata_raw else {}
            except Exception:
                metadata = {}
            if status == "preview_processing":
                new_status = "preview_ready"
                metadata["preview_warning"] = "服务重启中断了 AI 预览增强，已保留基础规则解析结果。"
                metadata["progress"] = {"message": metadata["preview_warning"], "updated_at": datetime.utcnow().isoformat()}
            else:
                new_status = "failed"
                metadata["progress"] = json.loads(stuck_message)
            conn.execute(
                text("UPDATE import_files SET status = :status, metadata_json = :metadata WHERE id = :id"),
                {"status": new_status, "metadata": json.dumps(metadata, ensure_ascii=False), "id": file_id},
            )
        if rows:
            logging.getLogger("import").warning("启动恢复：%s 个中间态导入任务已重置", len(rows))


def _run_data_migrations():
    """启动时数据迁移：同一对人物的双向重复关系合并为一条"""
    db = SessionLocal()
    try:
        merge_duplicate_relationships(db)
    except Exception:
        db.rollback()
        logging.getLogger(__name__).exception("关系去重迁移失败")
    finally:
        db.close()


# 初始化数据库表
_configure_logging()
Base.metadata.create_all(bind=engine)
_ensure_sqlite_columns()
_recover_stuck_imports()
_run_data_migrations()
if graph_store.health().get("available"):
    graph_store.ensure_schema()

app = FastAPI(
    title="BtB - Deep Dialogue Intelligence",
    description="AI Harness 驱动的对话深度分析系统",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(characters.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "service": "BtB AI Harness"}
