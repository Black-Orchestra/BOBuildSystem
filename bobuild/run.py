import argparse
import asyncio
import contextlib
import datetime
import re
from collections import deque
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

_repo_dir = Path(__file__).parent.parent

log_line_buffer: deque[str] = deque(maxlen=200)


class LogEventHandler(AIOEventHandler):
    def __init__(
            self,
            stop_event: asyncio.Event,
            log_file: Path,
            loop: asyncio.AbstractEventLoop | None = None,
            extra_exit_strings: list[str] | None = None,
            extra_error_strings: list[str] | None = None,
            buffer_lines: bool = False,
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
        self._buffer_lines = buffer_lines

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
        global log_line_buffer

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
                            # Not a fatal error.
                            if ("importtext" in line_lower
                                    and "property import failed" in line_lower):
                                self._warnings.append(line)
                            else:
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

                if self._buffer_lines:
                    log_line_buffer.append(line)

                if "Log file closed" in line:
                    log_end = True
                if self._extra_exit_strings and not log_end:
                    for extra in self._extra_exit_strings:
                        if extra in line:
                            log_end = True
                            break

            if log_end:
                logger.info("detected log end")
                # TODO: This is unreliable, and should also be unnecessary
                #   with -nopause command line arg!
                # self._stop_event.set()

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
        buffer_lines: bool = False,
) -> None:
    while True:
        if stream.at_eof():
            break
        line = (await stream.readline()).decode("utf-8", errors="replace").rstrip()
        if line:
            callback(line)
            if buffer_lines:
                global log_line_buffer
                log_line_buffer.append(line)


async def read_stream_task_se(
        stream: asyncio.StreamReader,
        callback: Callable[[str], None],
        stop_event: asyncio.Event | None = None,
        buffer_lines: bool = False,
) -> None:
    while True:
        if stream.at_eof():
            break
        line = (await stream.readline()).decode("utf-8", errors="replace").rstrip()
        if line:
            callback(line)
            if buffer_lines:
                global log_line_buffer
                log_line_buffer.append(line)
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
        buffer_lines: bool = False,
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
        buffer_lines: bool = False,
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
        buffer_lines: bool = False,
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

        await asyncio.gather(
            read_stream_task_se(
                proc.stdout, partial(line_cb, all_out, f"{pn} stdout"), stop_event, buffer_lines
            ),
            read_stream_task_se(
                proc.stderr, partial(line_cb, all_err, f"{pn} stderr"), stop_event, buffer_lines
            ),
        )

        ec = await proc.wait()
        logger.info("program {} exited with code: {}", pn, ec)
    except (KeyboardInterrupt, Exception, asyncio.CancelledError) as e:
        logger.error("error: {}: {}", type(e).__name__, e)
        if proc:
            await kill_process_tree(proc.pid)
        raise

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
            if await asyncio.wait_for(stop_event.wait(), 5.0):
                break


async def run_vneditor(
        rs2_documents_dir: Path,
        vneditor_path: Path,
        command: str,
        *args: str,
        raise_on_error: bool = False,
        extra_exit_strings: list[str] | None = None,
        extra_error_strings: list[str] | None = None,
        buffer_lines: bool = False,
) -> tuple[list[str], list[str]]:
    stop_event = asyncio.Event()
    logs_dir = rs2_documents_dir / "ROGame/Logs"
    log = logs_dir / "Launch.log"

    # Rename old log file to make sure logs are read from the right file.
    try:
        now = datetime.datetime.now()
        ts = now.strftime("%Y.%m.%d-%H.%M.%S")
        new_file = logs_dir / f"Launch-backup-{ts}.log"
        logger.info("renaming '{}' -> '{}'", log, new_file)
        log.rename(new_file)
    except Exception as e:
        logger.error("failed to rename old log file: '{}': {}: {}",
                     log, type(e).__name__, e)

    watch: AIOWatchdog | None = None
    toucher_task: asyncio.Task | None = None

    try:
        handler = LogEventHandler(
            stop_event=stop_event,
            log_file=log,
            extra_exit_strings=extra_exit_strings,
            extra_error_strings=extra_error_strings,
            buffer_lines=buffer_lines,
        )
        watch = AIOWatchdog(
            path=logs_dir,
            recursive=False,
            event_handler=handler,
        )
        watch.start()

        toucher_task = asyncio.create_task(log_toucher_task(log, stop_event))

        ec, _, stderr = await run_process(
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
            buffer_lines=buffer_lines,
        )

        logger.info("VNEditor exited with code: {}", ec)
        stop_event.set()

    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as e:
        logger.exception(e)
        raise
    finally:
        if toucher_task:
            toucher_task.cancel()
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(toucher_task, timeout=1.0)
            del toucher_task  # TODO: is this necessary?

        if watch:
            watch.stop()

    logger.info("Launch.log warnings: {}", len(handler.warnings))
    logger.info("Launch.log errors: {}", len(handler.errors))

    errs = handler.errors
    if stderr is not None and stderr:
        errs += stderr

    for error in errs:
        logger.error("Launch.log error: {}", error)

    if errs:
        count = 100
        errs_str = "\n".join(handler.errors[:count])
        raise RuntimeError(
            "VNEditor.exe failed: "
            f"Errors ({len(handler.errors)} total, "
            f"only {count} shown):\n{errs_str}"
        )

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
        buffer_lines=True,
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
        raise_on_error=False,  # Check actual status from logs!
        buffer_lines=True,
    )


async def patch_shader_cache(
        script_package_path: Path,
        shader_cache_path: str,
        object_to_patch_path: str,
):
    patcher = Path(_repo_dir).resolve() / "bin/UE3ShaderCachePatcherCLI.exe"
    if not patcher.exists():
        raise RuntimeError(f"UE3ShaderCachePatcherCLI.exe does not exist in '{patcher}'")

    await run_process(
        patcher,
        "-f", str(script_package_path.resolve()),
        "-s", shader_cache_path,
        "-p", object_to_patch_path,
        cwd=patcher.parent,
        raise_on_error=True,
    )


async def ensure_vneditor_modpackages_config(
        rs2_config: RS2Config,
        *_,
        mod_packages: list[str] | None = None,
        **__,
):
    mod_packages = mod_packages or []

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


async def ensure_roengine_config(rs2_config: RS2Config, *_, **__):
    """Assumes config files exist already."""
    docs_dir = rs2_config.rs2_documents_dir

    config_file = docs_dir / "ROGame/Config/ROEngine.ini"
    cfg = MultiConfigParser()
    cfg.read(config_file)

    suppressions = cfg["Core.System"].getlist("Suppress") or []
    if "DevCompile" in suppressions:
        suppressions.remove("DevCompile")
    if "DevConfig" in suppressions:
        suppressions.remove("DevConfig")
    if "DevCooking" in suppressions:
        suppressions.remove("DevCooking")
    if "DevLoad" in suppressions:
        suppressions.remove("DevLoad")
    if "DevShaders" in suppressions:
        suppressions.remove("DevShaders")
    # if "DevShadersDetailed" in suppressions:
    #     suppressions.remove("DevShadersDetailed")

    cfg["Core.System"]["Suppress"] = "\n".join(suppressions)
    cfg["LogFiles"]["PurgeLogsDays"] = "365"

    with config_file.open("w") as f:
        logger.info("writing config file: '{}'", config_file)
        cfg.write(f, space_around_delimiters=False)


async def test_find_sublevels(rs2_config: RS2Config, *_, **__) -> None:
    any_map = next(rs2_config.unpublished_dir.rglob("*.roe"))
    any_map or next(rs2_config.published_dir.glob("*.roe"))
    await find_sublevels(any_map)


async def find_sublevels(
        level_package_path: Path,
) -> list[str]:
    package_tool = Path(_repo_dir).resolve() / "bin/UE3PackageTool.exe"
    if not package_tool.exists():
        raise RuntimeError(f"UE3PackageTool.exe does not exist in '{package_tool}'")

    _, out, _ = await run_process(
        package_tool,
        "find-sublevels",
        "-f", str(level_package_path.absolute()),
        cwd=package_tool.parent,
        raise_on_error=True,
        return_output=True,
    )

    return [x.strip('"') for x in out.split("\n")]


async def main() -> None:
    ap = argparse.ArgumentParser()
    rs2_cfg = RS2Config()

    action_choices = {
        "configure_sdk": ensure_vneditor_modpackages_config,
        "configure_roengine": ensure_roengine_config,
        "test_find_sublevels": test_find_sublevels,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action](rs2_cfg, mod_packages=["WW2"])  # type: ignore[operator]
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
