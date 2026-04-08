from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .models.sql_models import Base
from .api.deps import engine
from .api import characters, chat

# 初始化数据库表
Base.metadata.create_all(bind=engine)

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
