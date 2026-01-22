import httpx
import json
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.utils.logger import logger

class LLMService:
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.proxy = settings.HTTP_PROXY if settings.HTTP_PROXY else None
        self.timeout = settings.LLM_TIMEOUT

    async def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        response_format: Optional[Dict] = None
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        try:
            # Use proxy if configured
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=self.proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=self.proxy),
            } if self.proxy else None

            async with httpx.AsyncClient(timeout=self.timeout, mounts=mounts) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"LLM API Error: Status {response.status_code}, Body: {response.text}")
                    return ""
                    
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.ConnectError as e:
            logger.error(f"LLM Connection Failed: {e}. Check your network or proxy settings (HTTP_PROXY).")
            return ""
        except Exception as e:
            logger.exception(f"LLM Call Unexpected Error: {e}")
            return ""

llm_service = LLMService()
