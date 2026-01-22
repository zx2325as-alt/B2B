from typing import Any, Optional
import json
import redis.asyncio as redis
from app.utils.logger import logger
from app.core.config import settings

class CacheService:
    """
    Redis Cache Service
    """
    def __init__(self):
        self.enabled = True
        # Default to localhost if not configured, in prod use settings.REDIS_URL
        self.redis_url = settings.REDIS_URL
        self.client = None

    async def connect(self):
        if not self.enabled:
            return
        try:
            self.client = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            await self.client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Cache disabled.")
            self.enabled = False
            self.client = None

    async def get(self, key: str) -> Optional[Any]:
        if not self.enabled or not self.client:
            return None
        try:
            value = await self.client.get(key)
            if value:
                logger.debug(f"Cache HIT: {key}")
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None

    async def set(self, key: str, value: Any, expire: int = 3600):
        if not self.enabled or not self.client:
            return
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await self.client.set(key, value, ex=expire)
            logger.debug(f"Cache SET: {key}")
        except Exception as e:
            logger.error(f"Redis SET error: {e}")

    async def invalidate(self, key: str):
        if not self.enabled or not self.client:
            return
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")

cache_service = CacheService()
