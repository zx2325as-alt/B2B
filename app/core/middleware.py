import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.utils.logger import logger

class ProcessTimeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Add Header
        response.headers["X-Process-Time"] = str(process_time)
        
        # Log slow requests (>500ms)
        if process_time > 0.5:
             logger.warning(f"Slow Request: {request.url.path} took {process_time:.4f}s")
             
        return response
