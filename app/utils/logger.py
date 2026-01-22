import sys
import logging
from app.core.config import settings

# Try to import loguru, fallback to standard logging
try:
    from loguru import logger
    
    def setup_logger():
        logger.remove()
        logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="DEBUG" if settings.DEBUG else "INFO",
        )
        log_file = settings.DATA_DIR / "logs" / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            rotation="10 MB",
            level="INFO"
        )
        
except ImportError:
    # Standard logging fallback
    class LoggerWrapper:
        def debug(self, msg): logging.debug(msg)
        def info(self, msg): logging.info(msg)
        def warning(self, msg): logging.warning(msg)
        def error(self, msg): logging.error(msg)
        def critical(self, msg): logging.critical(msg)
    
    logger = LoggerWrapper()
    
    def setup_logger():
        level = logging.DEBUG if settings.DEBUG else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr),
                # Add file handler if needed, skipping for simple fallback
            ]
        )

setup_logger()
