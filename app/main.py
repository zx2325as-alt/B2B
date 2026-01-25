from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from app.core.config import settings
from app.utils.logger import logger
from app.core.database import engine, Base, SessionLocal
from app.core.cache import cache_service
from app.api.v1.endpoints import router as api_v1_router
from app.api.v1.scenarios import router as scenarios_router
from app.api.v1.characters import router as characters_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.audio import router as audio_router
from app.services.scenario_service import scenario_service
from app.core.middleware import ProcessTimeMiddleware

# 初始化数据库表结构
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    openapi_tags=[
        {"name": "Chat", "description": "核心对话与知识库接口"},
        {"name": "Scenarios", "description": "场景管理接口"},
        {"name": "Characters", "description": "角色与关系管理接口"},
        {"name": "Feedback", "description": "反馈与进化接口"},
    ]
)

app.add_middleware(ProcessTimeMiddleware)

# 注册路由模块
app.include_router(api_v1_router, prefix="/api/v1", tags=["Chat"])
app.include_router(scenarios_router, prefix="/api/v1/scenarios", tags=["Scenarios"])
app.include_router(characters_router, prefix="/api/v1/characters", tags=["Characters"])
app.include_router(audio_router, prefix="/api/v1", tags=["Audio"])
app.include_router(feedback_router, prefix="/api/v1", tags=["Feedback"])

@app.on_event("startup")
async def startup_event():
    logger.info("BtB 系统正在启动...")
    await cache_service.connect()
    
    # Sync Scenarios
    try:
        db = SessionLocal()
        scenario_service.sync_scenarios_from_yaml(db)
        db.close()
        logger.info("Scenarios synced from YAML.")
    except Exception as e:
        logger.error(f"Failed to sync scenarios: {e}")

@app.get("/", include_in_schema=False)
async def root():
    """根路径重定向到 API 文档"""
    return RedirectResponse(url="/docs")

@app.get("/health", summary="健康检查", description="检查服务是否正常运行")
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.BACKEND_PORT, reload=settings.DEBUG)
