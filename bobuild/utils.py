import os
from typing import TypeVar
from typing import cast

from bobuild.log import logger

T = TypeVar("T")

_default = object()


def get_var(name: str, default: T | object = _default) -> str | T:
    if default is _default:
        return os.environ[name]

    if name not in os.environ:
        logger.warning("{} not set in environment", name)
    return os.environ.get(name, cast(T, default))
