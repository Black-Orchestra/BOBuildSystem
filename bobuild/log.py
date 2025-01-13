import inspect
import logging
from pathlib import Path

from loguru import logger

from bobuild.utils import get_var

# TODO: use logrotate on Linux if we run this as a service?

# logger.remove()

_log_dir = Path(get_var("BO_LOG_DIR", ".")).resolve()

logger.add(_log_dir / "bobuild.log", rotation="10 MB", retention=5)
logger.info("initialized logging")


# TODO: multiple loggers for different categories?
#  See: https://github.com/Delgan/loguru/issues/25#issuecomment-450252538

class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())
