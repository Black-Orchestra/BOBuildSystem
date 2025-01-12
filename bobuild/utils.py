import asyncio
import os
import platform
import shutil
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from typing import Coroutine
from typing import TypeVar
from typing import cast

from bobuild.log import logger

T = TypeVar("T")

_default = object()


def asyncio_run(coro: Coroutine[Any, Any, T]) -> T:
    if platform.system() == "Windows":
        # noinspection PyUnresolvedReferences
        import winloop  # type: ignore[import-not-found]
        winloop.install()
        return asyncio.run(coro)
    else:
        # noinspection PyUnresolvedReferences
        import uvloop  # type: ignore[import-not-found]
        return uvloop.run(coro)


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


def copy_file(src: Path, dst: Path):
    logger.info("copy: '{}' -> '{}'", src, dst)
    shutil.copyfile(src, dst)


def copy_tree(
        src_dir: Path,
        dst_dir: Path,
        src_glob: str | None = None,
):
    src_files: list[Path]
    if src_glob is not None:
        src_files = [x for x in src_dir.glob(src_glob) if x.is_file()]
    else:
        src_files = [x for x in src_dir.glob("*") if x.is_file()]

    # TODO: this needs improved handling for recursive dirs!
    fs: list[Future] = []
    with ThreadPoolExecutor() as executor:
        for file in src_files:
            dst = dst_dir / file.name
            executor.submit(copy_file, file, dst)

    for future in fs:
        ex = future.exception()
        if ex:
            logger.error("future: {}: error: {}", future, ex)
