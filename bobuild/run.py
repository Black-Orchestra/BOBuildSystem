import argparse
import asyncio
import contextlib
import re
from functools import partial
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
from bobuild.multiconfig import MultiConfigParser
from bobuild.utils import asyncio_run
from bobuild.utils import kill_process_tree

LOG_RE = re.compile(r"^\[[\d.]+]\s(\w+):(.*)$")


class LogEventHandler(AIOEventHandler):
    def __init__(
            self,
            stop_event: asyncio.Event,
            log_file: Path,
            loop: asyncio.AbstractEventLoop | None = None,
            extra_exit_strings: list[str] | None = None,
            extra_error_strings: list[str] | None = None,
    ):
        super().__init__(loop=loop)

        self._stop_event = stop_event
        self._log_file = log_file
        self._log_filename = log_file.name
        self._fh: IO | None = None
        self._pos = 0
        self._warnings: list[str] = []
        self._errors: list[str] = []
        self._extra_exit_strings = extra_exit_strings or []
        self._extra_error_strings = extra_error_strings or []

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
                    line_lower = line.lower()
                    if "error reading attributes for" in line_lower:
                        # This is always a fake error!
                        pass
                    elif "encryptedappticketresponse: biofailure" in line_lower:
                        # This is always a fake error!
                        pass
                    elif match.group(1).lower() == "error":
                        if match.group(2):
                            self._errors.append(line)
                    elif match.group(1).lower() == "warning":
                        if match.group(2):
                            self._warnings.append(line)
                    else:
                        for err_str in self._extra_error_strings:
                            if err_str in line:
                                self._errors.append(line)

                # if os.getenv("GITHUB_ACTIONS"):
                #     line = unicodedata.normalize("NFKD", line)
                logger.info("{}: log line: {}", path.name, line.rstrip())

                if "Log file closed" in line:
                    log_end = True
                if self._extra_exit_strings and not log_end:
                    for extra in self._extra_exit_strings:
                        if extra in line:
                            log_end = True
                            break

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


async def read_stream_task(
        stream: asyncio.StreamReader,
        callback: Callable[[str], None],
) -> None:
    while True:
        if stream.at_eof():
            break
        line = (await stream.readline()).decode("utf-8", errors="replace").rstrip()
        if line:
            callback(line)


async def read_stream_task_se(
        stream: asyncio.StreamReader,
        callback: Callable[[str], None],
        stop_event: asyncio.Event | None = None,
) -> None:
    while True:
        if stream.at_eof():
            break
        line = (await stream.readline()).decode("utf-8", errors="replace").rstrip()
        if line:
            callback(line)
        if stop_event and stop_event.is_set():
            break


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

    all_out: list[str] = []
    all_err: list[str] = []

    if isinstance(program, Path):
        pn = program.name
    else:
        pn = program

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            str(program),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        if not proc.stdout:
            raise RuntimeError(f"process has no stdout: {proc}")
        if not proc.stderr:
            raise RuntimeError(f"process has no stderr: {proc}")

        def line_cb(_lines: list[str], _name: str, _line: str):
            logger.info("{}: {}", _name, _line)
            if return_output:
                _lines.append(_line)

        await asyncio.gather(*(
            read_stream_task_se(proc.stdout, partial(line_cb, all_out, f"{pn} stdout"), stop_event),
            read_stream_task_se(proc.stderr, partial(line_cb, all_err, f"{pn} stderr"), stop_event),
        ))

        ec = await proc.wait()
        logger.info("program {} exited with code: {}", pn, ec)
    except (KeyboardInterrupt, Exception, asyncio.CancelledError) as e:
        logger.error("error: {}: {}", type(e).__name__, e)
        if proc:
            await kill_process_tree(proc.pid)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"program {program} exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def log_toucher_task(
        path: Path,
        stop_event: asyncio.Event,
) -> None:
    """Workaround to make VNEditor.exe flush the log since
    -forcelogflush does not work always for some reason.
    """
    while not stop_event.is_set():
        path.touch(exist_ok=True)
        with contextlib.suppress(asyncio.TimeoutError):
            x = await asyncio.wait_for(stop_event.wait(), 1.0)
            if x:
                break


async def run_vneditor(
        rs2_documents_dir: Path,
        vneditor_path: Path,
        command: str,
        *args: str,
        raise_on_error: bool = False,
        extra_exit_strings: list[str] | None = None,
        extra_error_strings: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    stop_event = asyncio.Event()
    logs_dir = rs2_documents_dir / "ROGame/Logs"
    log = logs_dir / "Launch.log"
    handler = LogEventHandler(
        stop_event=stop_event,
        log_file=log,
        extra_exit_strings=extra_exit_strings,
        extra_error_strings=extra_error_strings,
    )
    watch = AIOWatchdog(
        path=logs_dir,
        recursive=False,
        event_handler=handler,
    )
    watch.start()

    toucher_task = asyncio.create_task(log_toucher_task(log, stop_event))

    ec, _, _ = await run_process(
        vneditor_path,
        command,
        *args,
        "-log",
        "-forcelogflush",
        "-unattended",
        "-useunpublished",
        "-auto",
        "-nopause",
        raise_on_error=raise_on_error,
        stop_event=stop_event,
    )

    logger.info("VNEditor exited with code: {}", ec)

    while not stop_event.is_set():
        await asyncio.sleep(0.1)

    toucher_task.cancel()
    with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
        await asyncio.wait_for(toucher_task, timeout=1.0)

    watch.stop()

    logger.info("Launch.log warnings: {}", len(handler.warnings))
    logger.info("Launch.log errors: {}", len(handler.errors))
    for error in handler.errors:
        logger.error("Launch.log error: {}", error)
    if handler.errors:
        errs_str = "\n".join(handler.errors)
        raise RuntimeError("VNEditor.exe failed: {}", errs_str)

    return handler.warnings, handler.errors


async def vneditor_make(
        rs2_documents_dir: Path,
        vneditor_path: Path,
) -> tuple[list[str], list[str]]:
    return await run_vneditor(
        rs2_documents_dir,
        vneditor_path,
        "make",
        "-stripsource",
        extra_exit_strings=["appRequestExit"],
        extra_error_strings=["STEAM is required to play the game"],
        raise_on_error=True,
    )


async def vneditor_brew(
        rs2_documents_dir: Path,
        vneditor_path: Path,
        content: list[str],
) -> tuple[list[str], list[str]]:
    """NOTE: Steam client is required to be running
    in the background for brewcontent commandlet!
    TODO: can we patch this out of the exe?
    """
    return await run_vneditor(
        rs2_documents_dir,
        vneditor_path,
        "brewcontent",
        *content,
        extra_exit_strings=["appRequestExit"],
        extra_error_strings=["STEAM is required to play the game"],
        raise_on_error=True,
    )


async def patch_shader_cache(
        script_package_path: Path,
        shader_cache_path: str,
        object_to_patch_path: str,
):
    repo_dir = Path(__file__).parent.parent
    patcher = Path(repo_dir).resolve() / "bin/UE3ShaderCachePatcherCLI.exe"
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


async def ensure_vneditor_modpackages_config(
        rs2_config: RS2Config,
        mod_packages: list[str],
):
    docs_dir = rs2_config.rs2_documents_dir

    # Dry-run to make sure config files exist.
    await run_vneditor(
        rs2_documents_dir=docs_dir,
        vneditor_path=rs2_config.vneditor_exe,
        command="help",
        extra_exit_strings=["appRequestExit"],
    )

    config_file = docs_dir / "ROGame/Config/ROEditor.ini"
    cfg = MultiConfigParser()
    cfg.read(config_file)

    cfg_mod_packages = cfg["ModPackages"].getlist("ModPackages") or []
    for mod_package in mod_packages:
        if mod_package not in cfg_mod_packages:
            cfg_mod_packages.append(mod_package)
    cfg["ModPackages"]["ModPackages"] = "\n".join(cfg_mod_packages)

    with config_file.open("w") as f:
        logger.info("writing config file: '{}'", config_file)
        cfg.write(f, space_around_delimiters=False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    rs2_cfg = RS2Config()

    action_choices = {
        "configure_sdk": ensure_vneditor_modpackages_config,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action](rs2_cfg, mod_packages=["WW2"])
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
