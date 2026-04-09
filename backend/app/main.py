from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .models.sql_models import Base
from .api.deps import engine
from .api import characters, chat

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
        },
        "messages": {
            "message_index": "ALTER TABLE messages ADD COLUMN message_index INTEGER DEFAULT 0",
            "receiver_id": "ALTER TABLE messages ADD COLUMN receiver_id INTEGER",
            "receiver_name": "ALTER TABLE messages ADD COLUMN receiver_name VARCHAR(100)",
            "intent": "ALTER TABLE messages ADD COLUMN intent VARCHAR(200)",
            "strategy": "ALTER TABLE messages ADD COLUMN strategy VARCHAR(200)",
            "emotion": "ALTER TABLE messages ADD COLUMN emotion VARCHAR(200)",
            "source_type": "ALTER TABLE messages ADD COLUMN source_type VARCHAR(20) DEFAULT 'chat'",
            "readonly": "ALTER TABLE messages ADD COLUMN readonly BOOLEAN DEFAULT 0",
        },
        "import_files": {
            "version": "ALTER TABLE import_files ADD COLUMN version INTEGER DEFAULT 1",
            "model_used": "ALTER TABLE import_files ADD COLUMN model_used VARCHAR(100) DEFAULT 'ai-harness'",
        },
        "interaction_units": {
            "psychological_label": "ALTER TABLE interaction_units ADD COLUMN psychological_label VARCHAR(200) DEFAULT ''",
            "context_window": "ALTER TABLE interaction_units ADD COLUMN context_window JSON",
        },
    }
    with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            existing = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    conn.execute(text(ddl))


# 初始化数据库表
_configure_logging()
Base.metadata.create_all(bind=engine)
_ensure_sqlite_columns()

app = FastAPI(
    title="BtB - Deep Dialogue Intelligence",
    description="AI Harness 驱动的对话深度分析系统",
    version="1.0.0",
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
