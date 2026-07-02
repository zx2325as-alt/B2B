from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

# 绝对路径：无论从哪个目录启动，都使用 backend/btb.db，避免出现第二个空库
DB_PATH = Path(__file__).resolve().parents[2] / "btb.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """WAL 提升并发读写；busy_timeout 缓解多线程锁冲突。
    注意：不开启 foreign_keys 强制约束——历史模型存在大量无 ON DELETE 规则的松散外键，
    级联清理由删除端点显式完成（见 chat.py / characters.py 的 delete 实现）。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    # 不计成本/全 opus 后，后台任务（复核/对抗/诊断/目标进度/摘要）并发写增多，
    # 单写者持锁期可能超 5s；提到 15s 让写等待而非直接报 database is locked。
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
