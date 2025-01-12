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
        logger.info("{} not set in environment, using default: '{}'", name, default)
    return os.environ.get(name, cast(T, default))


def redact(x: str, args: list[str]) -> list[str]:
    return [
        arg
        if arg != x
        else "*" * len(arg)
        for arg in args
    ]


def is_dev_env() -> bool:
    return get_var("BO_DEV_ENV", "0") == "1"
