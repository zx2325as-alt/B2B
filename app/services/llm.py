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
        # Auto-detect if we should use proxy
        # If connecting to localhost, FORCE disable proxy to avoid loopback issues
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
             self.proxy = None
        else:
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
            "stream": False
        }
        if response_format:
            # Check if model supports response_format (Ollama support is limited)
            # For Ollama, strict JSON mode might need specific flags or just prompt engineering
            # But let's keep it for now as newer Ollama versions support it.
            payload["response_format"] = response_format

        try:
            # Use proxy if configured
            mounts = {
                "http://": httpx.AsyncHTTPTransport(proxy=self.proxy),
                "https://": httpx.AsyncHTTPTransport(proxy=self.proxy),
            } if self.proxy else None

            # Increase pool limits or keep-alive settings if needed, but default is usually fine.
            # Adding retries for stability
            transport = httpx.AsyncHTTPTransport(proxy=self.proxy, retries=3) if self.proxy else httpx.AsyncHTTPTransport(retries=3)

            async with httpx.AsyncClient(timeout=self.timeout, transport=transport) as client:
                logger.info(f"LLM Request: {url} | Model: {self.model} | Proxy: {self.proxy}")
                response = await client.post(url, headers=self.headers, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"LLM API Error: Status {response.status_code}, Body: {response.text}")
                    return ""
                    
                response.raise_for_status()
                try:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                except json.JSONDecodeError:
                    logger.error(f"LLM Invalid JSON Response: {response.text}")
                    return ""
        except httpx.ConnectError as e:
            logger.error(f"LLM Connection Failed: {e}. Check your network, proxy settings, or if Ollama is running.")
            return ""
        except httpx.RemoteProtocolError as e:
             logger.error(f"LLM Protocol Error (Server Disconnected): {e}. This often happens if Ollama crashes, times out, or the model name '{self.model}' is incorrect.")
             return ""
        except Exception as e:
            logger.exception(f"LLM Call Unexpected Error: {e}")
            return ""

llm_service = LLMService()
