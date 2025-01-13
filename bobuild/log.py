import inspect
import logging
import os
from pathlib import Path
from typing import TypeVar
from typing import cast

from loguru import logger

# TODO: use logrotate on Linux if we run this as a service?

# logger.remove()

T = TypeVar("T")

_default = object()


# NOTE: Duplicated here to avoid circular import.
def _get_var(name: str, default: T | object = _default) -> str | T:
    if default is _default:
        return os.environ[name]

    if name not in os.environ:
        logger.info("{} not set in environment, using default: '{}'", name, default)
    return os.environ.get(name, cast(T, default))


_log_dir = Path(_get_var("BO_LOG_DIR", ".")).resolve()
_log_dir.mkdir(parents=True, exist_ok=True)

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
