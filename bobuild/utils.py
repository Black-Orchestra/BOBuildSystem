import asyncio
import datetime
import hashlib
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

import psutil

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


# noinspection PyProtectedMember,PyUnresolvedReferences
def file_digest(path: Path) -> "hashlib._Hash":
    with path.open("rb") as f:
        return hashlib.file_digest(f, "md5")


def copy_file(src: Path, dst: Path, check_md5: bool = False):
    if check_md5:
        if dst.exists():
            dst_md5 = file_digest(dst)
            src_md5 = file_digest(src)
            if dst_md5.digest() == src_md5.digest():
                logger.info("MD5 hashes match for: '{}' == '{}', {} == {}, not copying",
                            src, dst, src_md5.hexdigest(), dst_md5.hexdigest())
                return

    logger.info("copy: '{}' -> '{}'", src, dst)
    shutil.copyfile(src, dst)


def copy_tree(
        src_dir: Path,
        dst_dir: Path,
        src_glob: str | None = None,
        src_stems: list[str] | None = None,
        check_md5: bool = False,
):
    src_files: list[Path]
    if src_glob is not None:
        src_files = [x for x in src_dir.glob(src_glob) if x.is_file()]
    else:
        src_files = [x for x in src_dir.glob("*") if x.is_file()]

    if src_stems is not None:
        src_stems_lower = [src_stem.lower() for src_stem in src_stems]
        src_files = [x for x in src_files if x.stem.lower() in src_stems_lower]

    # TODO: this needs improved handling for recursive dirs!
    fs: list[Future] = []
    with ThreadPoolExecutor() as executor:
        for file in src_files:
            dst = dst_dir / file.name
            executor.submit(copy_file, file, dst, check_md5=check_md5)

    for future in fs:
        ex = future.exception()
        if ex:
            logger.error("future: {}: error: {}", future, ex)

    # TODO: get future result and re-raise error?


async def kill_process_tree(pid: int) -> None:
    try:
        proc = psutil.Process(pid)
        logger.info("killing process tree: {}", proc)
        children = proc.children(recursive=True)

        for child in children:
            child.terminate()
        proc.terminate()

        await asyncio.sleep(0.5)

        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    except psutil.Error as e:
        logger.info("cannot kill process tree of: {}: {}: {}",
                    pid, type(e).__name__, e)


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)
