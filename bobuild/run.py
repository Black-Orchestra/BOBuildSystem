import asyncio
import re
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import IO
from typing import Iterable
from typing import Literal
from typing import TypeVar
from typing import overload
from typing import override

import watchdog.events
from hachiko import AIOEventHandler
from hachiko import AIOWatchdog

from bobuild.config import RS2Config
from bobuild.log import logger
from bobuild.utils import asyncio_run

LOG_RE = re.compile(r"^\[[\d.]+]\s(\w+):(.*)$")


class LogEventHandler(AIOEventHandler):
    def __init__(
            self,
            stop_event: asyncio.Event,
            log_file: Path,
            loop: asyncio.AbstractEventLoop | None = None,
    ):
        super().__init__(loop=loop)

        self._stop_event = stop_event
        self._log_file = log_file
        self._log_filename = log_file.name
        self._fh: IO | None = None
        self._pos = 0
        self._warnings: list[str] = []
        self._errors: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return self._warnings

    @property
    def errors(self) -> list[str]:
        return self._errors

    @override
    async def on_any_event(self, event: watchdog.events.FileSystemEvent):
        if Path(str(event.src_path)).name == self._log_filename:
            # print(f"fs event: {event.event_type}, {event.src_path}")
            logger.info("FS event: {}, {}", event.event_type, event.src_path)
            self._fh = open(self._log_file, errors="replace", encoding="utf-8")

    @override
    async def on_modified(self, event: watchdog.events.FileSystemEvent):
        path = Path(str(event.src_path))
        if path.name == self._log_filename:
            if not self._fh:
                raise RuntimeError("no log file handle")

            size = self._log_file.stat().st_size
            if size == 0:
                logger.info("log file cleared")
                self._pos = 0
                return

            self._fh.seek(self._pos)

            log_end = False
            while line := self._fh.readline():
                self._pos = self._fh.tell()

                if match := LOG_RE.match(line):
                    if match.group(1).lower() == "error":
                        if match.group(2):
                            self._errors.append(line)
                    elif "##ERROR##" in match.group(2):
                        self._errors.append(line)
                    elif match.group(1).lower() == "warning":
                        if match.group(2):
                            self._warnings.append(line)

                # if os.getenv("GITHUB_ACTIONS"):
                #     line = unicodedata.normalize("NFKD", line)
                logger.info("{}: log line: {}", path.name, line.rstrip())

                if "Log file closed" in line:
                    log_end = True

            if log_end:
                logger.info("setting stop event")
                self._stop_event.set()

    def __del__(self):
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass


T = TypeVar("T")


async def wait_for(
        coro: Coroutine[Any, Any, T],
        default: T,
        timeout: float = 10,
) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return default


@overload
async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[True] = ...,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
        stop_event: asyncio.Event | None = None,
) -> tuple[int, str, str]:
    ...


@overload
async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[False] = ...,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
        stop_event: asyncio.Event | None = None,
) -> tuple[int, None, None]:
    ...


async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: bool = False,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
        stop_event: asyncio.Event | None = None,
) -> tuple[int, None | str, None | str]:
    if redact is not None:
        logger.info("running program {}: {}, cwd={}", program, redact(args), cwd)
    else:
        logger.info("running program {}: {}, cwd={}", program, args, cwd)

    proc = await asyncio.create_subprocess_exec(
        str(program),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    all_out = []
    all_err = []

    if isinstance(program, Path):
        pn = program.name
    else:
        pn = program

    if not proc.stdout:
        raise RuntimeError(f"process has no stdout: {proc}")
    if not proc.stderr:
        raise RuntimeError(f"process has no stderr: {proc}")

    timeout = 0.1
    while True:
        if proc.stdout.at_eof() and proc.stderr.at_eof():
            break

        out = (await wait_for(proc.stdout.readline(), b"", timeout=timeout)
               ).decode("utf-8", errors="replace").rstrip()
        if out:
            logger.info("{} stdout: {}", pn, out)
            if return_output:
                all_out.append(out)
        err = (await wait_for(proc.stderr.readline(), b"", timeout=timeout)
               ).decode("utf-8", errors="replace").rstrip()
        if err:
            logger.info("{} stderr: {}", pn, err)
            if return_output:
                all_err.append(err)

        if stop_event and stop_event.is_set():
            break

    ec = await proc.wait()
    logger.info("program {} exited with code: {}", pn, ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"program {program} exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def run_vneditor(
        rs2_documents_dir: Path,
        vneditor_path: Path,
        command: str,
        *args: str,
) -> None:
    stop_event = asyncio.Event()
    logs_dir = rs2_documents_dir / "ROGame/Logs"
    log = logs_dir / "Launch.log"
    handler = LogEventHandler(stop_event, log)
    watch = AIOWatchdog(
        path=logs_dir,
        recursive=False,
        event_handler=handler,
    )
    watch.start()

    ec, _, _ = await run_process(
        vneditor_path,
        command,
        *args,
        "-log",
        "-unattended",
        "-useunpublished",
        "-forcelogflush",
        "-auto",
        "-nopause",
        raise_on_error=False,
        stop_event=stop_event,
    )

    logger.info("VNEditor exited with code: {}", ec)

    while not stop_event.is_set():
        await asyncio.sleep(0.1)

    watch.stop()

    logger.info("Launch.log warnings: {}", len(handler.warnings))
    logger.info("Launch.log errors: {}", len(handler.errors))
    for error in handler.errors:
        logger.error("Launch.log error: {}", error)
    if handler.errors:
        errs_str = "\n".join(handler.errors)
        raise RuntimeError("VNEditor.exe failed: {}", errs_str)


async def vneditor_make(
        rs2_documents_dir: Path,
        vneditor_path: Path,
) -> None:
    await run_vneditor(
        rs2_documents_dir,
        vneditor_path,
        "make",
        "-stripsource",
    )


async def vneditor_brew(
        rs2_documents_dir: Path,
        vneditor_path: Path,
        content: list[str],
) -> None:
    await run_vneditor(
        rs2_documents_dir,
        vneditor_path,
        "brewcontent",
        *content,
    )


async def patch_shader_cache(
        script_package_path: Path,
        shader_cache_path: str,
        object_to_patch_path: str,
):
    repo_dir = Path(__file__).parent.parent
    patcher = Path(repo_dir).resolve() / "UE3ShaderCachePatcherCLI.exe"
    if not patcher.exists():
        raise RuntimeError(f"UE3ShaderCachePatcherCLI.exe does not exist in '{patcher}'")

    await run_process(
        str(patcher.name),
        "-f", str(script_package_path.resolve()),
        "-s", shader_cache_path,
        "-p", object_to_patch_path,
        cwd=patcher.parent,
        raise_on_error=True,
    )


async def main() -> None:
    cfg = RS2Config()

    await vneditor_make(
        cfg.rs2_documents_dir,
        cfg.vneditor_exe,
    )

    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
