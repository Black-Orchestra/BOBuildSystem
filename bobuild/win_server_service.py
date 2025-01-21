"""Rising Storm 2 Windows Server Service.
Handles automatic Black Orchestra developer beta content updates
via Steam Workshop. Hosts a 24/7 developer test server.

Update workflow (when SWS update is available):
1. Notify server via in-game chat & notify discord.
2. Shut down server.
3. Update workshop items (notify discord on status).
4. Move updated items to server Cache.
    - For updated items, DELETE ALL EXISTING BEFORE COPY!
5. Ensure config is correct.
    - Read metadata from SWS manifests.
    - Ensure WebAdmin is enabled (and port is correct).
    - Maybe worth it making WebAdmin config read-only!
6. Start server.
"""

# TODO: use sc.exe to set desired service parameters, etc.
# TODO: we need async rs2wapy to send messages to the server!

import argparse
import asyncio
import contextlib
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import orjson
import psutil
import servicemanager
import vdf
import win32service
import win32serviceutil

from bobuild.config import DiscordConfig
from bobuild.config import RS2Config
from bobuild.config import SteamCmdConfig
from bobuild.log import logger
from bobuild.log import stdout_handler_id
from bobuild.utils import asyncio_run
from bobuild.utils import get_var
from bobuild.workshop import WorkshopManifest

STOP_EVENT = asyncio.Event()
ASYNC_MAIN_DONE_EVENT = threading.Event()

# https://mhammond.github.io/pywin32/SERVICE_STATUS.html
ServiceStatusType = tuple[int, int, int, int, int, int, int]


def get_status(service_name: str) -> int:
    status: ServiceStatusType = win32serviceutil.QueryServiceStatus(service_name)
    return status[1]


class BOWinServerService(win32serviceutil.ServiceFramework):
    _svc_name_ = "BOWinServerService"
    _svc_display_name_ = "Black Orchestra Windows Server Service"
    _svc_description_ = "Runs Black Orchestra Windows Server and handles automatic updates."

    # Shorthand to avoid "protected" member IDE warnings.
    svc_name = _svc_name_

    rs2_config: RS2Config
    steamcmd_config: SteamCmdConfig
    discord_config: DiscordConfig

    @classmethod
    def cstatus(cls) -> int:
        # TODO: ONLY USE THIS SPARINGLY! UNNECESSARILY EXPENSIVE?
        # noinspection PyBroadException
        try:
            return get_status(cls._svc_name_)
        except Exception:
            return win32service.SERVICE_STOPPED

    @classmethod
    def parse_args(cls, args: list[str]):
        win32serviceutil.HandleCommandLine(cls, argv=args)

    def __init__(self, args):
        super().__init__(args)
        self.status = win32service.SERVICE_START_PENDING

    @property
    def status(self) -> int:
        return self._status

    @status.setter
    def status(self, status: int):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._status = status

    def log_info(self, msg: str):
        log_info(msg, self.status)

    def log_warning(self, msg: str):
        log_warning(msg, self.status)

    def log_error(self, msg: str):
        log_error(msg, self.status)

    # noinspection PyPep8Naming
    def SvcStop(self):
        global STOP_EVENT
        STOP_EVENT.set()
        self.status = win32service.SERVICE_STOP_PENDING

        exit_timeout = time.time() + 10.0
        # Wait for main tasks to finish.
        while time.time() < exit_timeout:
            if ASYNC_MAIN_DONE_EVENT.wait(0.1):
                break
        # no break
        else:
            self.log_error("timed out waiting for tasks to finish, exiting anyway")

        self.status = win32service.SERVICE_STOPPED
        self.log_info("exiting")

    # noinspection PyPep8Naming
    def SvcDoRun(self):
        self.log_info("starting")

        # Inject stored config into env, then build config objects.
        global CONFIG_PATH
        CONFIG_PATH = make_config_path()
        cfg = load_config(CONFIG_PATH)
        self.log_info(f"loaded {len(cfg)} config keys")
        for key, value in cfg.items():
            os.environ[key] = str(value)

        BOWinServerService.rs2_config = RS2Config()
        BOWinServerService.steamcmd_config = SteamCmdConfig()
        BOWinServerService.discord_config = DiscordConfig()

        self.status = win32service.SERVICE_RUNNING
        asyncio_run(main_task(
            BOWinServerService.rs2_config,
            BOWinServerService.steamcmd_config,
            BOWinServerService.discord_config,
        ))


def get_config_dir() -> Path:
    try:
        appdata = Path(os.environ["LOCALAPPDATA"]).resolve()
    except KeyError:
        log_error("cannot get LOCALAPPDATA from environment")
        raise
    return appdata / BOWinServerService.svc_name


def make_config_path() -> Path:
    return get_config_dir() / "config.json"


def make_pidfile_path() -> Path:
    return get_config_dir() / "pidfile.txt"


def load_config(path: Path) -> dict[str, str]:
    return orjson.loads(path.read_bytes())


CONFIG_PATH = make_config_path()


def log_info(msg: str, state: int = BOWinServerService.cstatus()):
    # TODO: does this crash? (Same goes for warning and error logs)!
    # https://github.com/mhammond/pywin32/issues/2155

    servicemanager.LogMsg(
        servicemanager.EVENTLOG_INFORMATION_TYPE,
        state,
        (BOWinServerService.svc_name, msg),
    )
    logger.info(msg)


def log_warning(msg: str, state: int = BOWinServerService.cstatus()):
    servicemanager.LogMsg(
        servicemanager.EVENTLOG_WARNING_TYPE,
        state,
        (BOWinServerService.svc_name, msg),
    )
    logger.warning(msg)


def log_error(msg: str, state: int = BOWinServerService.cstatus()):
    servicemanager.LogMsg(
        servicemanager.EVENTLOG_WARNING_TYPE,
        state,
        (BOWinServerService.svc_name, msg),
    )
    logger.error(msg)


async def terminate_server(
        server_proc: asyncio.subprocess.Process | psutil.Process,
        timeout: float = 5.0,
):
    if isinstance(server_proc, asyncio.subprocess.Process):
        server_proc_handle = psutil.Process(server_proc.pid)
    else:
        server_proc_handle = server_proc

    children = server_proc_handle.children(recursive=True)
    try:
        server_proc_handle.terminate()
    except psutil.Error:
        pass
    next_timeout = time.time() + timeout
    while server_proc_handle.is_running() and (time.time() < next_timeout):
        await asyncio.sleep(0.1)

    if server_proc_handle.is_running():
        log_warning(f"process {server_proc_handle.pid} did not stop gracefully, killing it")
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        try:
            server_proc_handle.kill()
        except psutil.Error:
            pass


async def steamcmd_update(
        steamcmd_install_script_path: Path,
        steamcmd_update_script_path: Path,
        branch: str,
        pidfile_path: Path,
        server_proc: psutil.Process | None,
):
    needs_update = False
    build_id: int | None = None
    branch = branch.lower()

    check_update_proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        str(steamcmd_update_script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ec = await check_update_proc.wait()
    if ec != 0:
        log_warning(f"SteamCMD exited with code: {ec}")
    out = (await check_update_proc.stdout.read()).decode(encoding="utf-8", errors="replace")
    out += (await check_update_proc.stderr.read()).decode(encoding="utf-8", errors="replace")

    install_state_found = False

    lines = out.split("\n")
    for i, line in enumerate(lines):
        log_info(f"SteamCMD output: [line {i}]: {line}")
        line = line.strip()
        # E.g.:
        #  - install state: Fully Installed,
        #  - install state: Fully Installed,Update Required,
        if "install state:" in line:
            install_state_found = True
            states_str = line.split(":")[1]
            states = [
                state.strip()
                for state in states_str.split(",")
                if state
            ]
            for state in states:
                if state == "Update Required":
                    needs_update = True
                    break
        # - size on disk: 13978936396 bytes, BuildID 16715839
        elif "size on disk:" in line:
            build_id = int(line.split("BuildID")[-1].strip())
            log_info(f"current BuildID: {build_id}")

    if not install_state_found:
        log_warning("'install state:' line not found in steamcmd output")

    if not build_id:
        log_warning("cannot determine BuildID from SteamCMD output")

    # Install state is not reliable, check app_info_print output too.
    if not needs_update and build_id:
        pattern = re.compile(r".*(\"1457890\"[\r\n]+{.*}).*", flags=re.DOTALL)
        if match := pattern.match(out):
            try:
                data = vdf.loads(match.group(1))
                latest_build_id = int(data["1457890"]["depots"]["branches"][branch]["buildid"])
                log_info(f"latest BuildID: {latest_build_id}")
                if latest_build_id != build_id:
                    needs_update = True
            except Exception as e:
                log_error(f"error parsing VDF: {type(e).__name__}: {e}")
        else:
            log_warning(f"{pattern} does not match output")

    log_info(f"BO server needs_update={needs_update}")

    if not needs_update:
        return

    # Shut down BO server if it's running.
    if server_proc is not None:
        log_info(f"terminating running server process: {server_proc}")
        try:
            pids = read_pids(pidfile_path)
            await terminate_many(pids)
            await terminate_server(server_proc)
        except psutil.Error as e:
            log_warning(f"{type(e).__name__}: {e}")
    else:
        log_info("no server process running, no need to terminate")

    log_info("running SteamCMD update script")
    steamcmd_proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        str(steamcmd_install_script_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ec = await steamcmd_proc.wait()
    out = (await steamcmd_proc.stdout.read()).decode(encoding="utf-8", errors="replace")
    out += (await steamcmd_proc.stderr.read()).decode(encoding="utf-8", errors="replace")
    out_lines = out.split("\n")
    for i, line in enumerate(out_lines):
        log_info(f"SteamCMD output: [line {i}]: {line}")
    log_info(f"{steamcmd_proc} exited with code: {ec}")


def read_manifest(
        rs2_cfg: RS2Config,
        # item_id: id,
) -> WorkshopManifest:
    raise NotImplementedError
    # TODO: do we read
    # manifest_dir = rs2_cfg.server_workshop_dir
    # return WorkshopManifest()


async def terminate_many(pids: list[int]):
    procs = []
    for pid in pids:
        if psutil.pid_exists(pid):
            procs.append(psutil.Process(pid))

    coros = [
        terminate_server(proc)
        for proc in procs
    ]

    await asyncio.gather(*coros)


def read_pids(pidfile_path: Path) -> list[int]:
    if not pidfile_path.exists():
        return []

    return [
        int(pid.strip())
        for pid in pidfile_path.read_text().split("\n")
    ]


async def is_running(proc: asyncio.subprocess.Process) -> bool:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=1e-6)
    return proc.returncode is None


async def main_task(
        service: BOWinServerService,
        rs2_config: RS2Config,
        steamcmd_config: SteamCmdConfig,
        discord_config: DiscordConfig,
) -> None:
    global ASYNC_MAIN_DONE_EVENT

    workshop_items: list[int] = [rs2_config.bo_dev_beta_workshop_id]
    workshop_items += list(rs2_config.bo_dev_beta_map_ids.values())
    service.log_info(f"workshop item count: {len(workshop_items)}")

    pidfile_path = make_pidfile_path()
    service.log_info(f"using pidfile_path: '{pidfile_path}'")
    pidfile_path.parent.mkdir(parents=True, exist_ok=True)

    server_proc: asyncio.subprocess.Process | None = None
    update_check_time = 0
    update_check_interval = 60

    if pidfile_path.exists():
        service.log_warning(f"pidfile: '{pidfile_path}' exists, old BO server process not cleaned up?")
        try:
            _pids = read_pids(pidfile_path)
            await terminate_many(_pids)
        except Exception as e:
            service.log_warning(f"error terminating process: {type(e).__name__}: {e}")

    pidfile_path.unlink(missing_ok=True)

    while not await asyncio.wait_for(STOP_EVENT.wait(), timeout=1.0):
        if time.time() > (update_check_interval + update_check_time):
            service.log_info("checking for BO Steam Workshop updates")
            # await steamcmd_update(
            #     steamcmd_install_script_path,
            #     steamcmd_update_script_path,
            #     branch,
            #     pidfile_path,
            #     s_proc_handle,
            # )
            update_check_time = time.time()

            if not server_proc:
                #         log_info("running server start script")
                #         changelist = read_changelist(build_id_file_path)
                #         full_server_name = f"{server_name} {changelist}"
                #         server_proc = await asyncio.create_subprocess_exec(
                #             "powershell.exe",
                #             "-NoProfile",
                #             "-ExecutionPolicy", "Bypass",
                #             str(script_path),
                #             *(
                #                 f"-ServerName \"{full_server_name}\"",
                #                 f"-Branch \"{branch}\"",
                #                 f"-Port \"{port}\"",
                #                 f"-QueryPort \"{query_port}\"",
                #             ),
                #             stderr=asyncio.subprocess.STDOUT,
                #         )
                #         # Wait a bit to let it start all children.
                #         await asyncio.sleep(1.0)
                #
                # This isn't necessarily reliable, but better than nothing.
                s_proc_handle = psutil.Process(server_proc.pid)
                pids = [
                    str(child.pid)
                    for child in s_proc_handle.children()
                ]
                pids.append(str(s_proc_handle.pid))
                pids_str = "\n".join(pids)
                pidfile_path.write_text(pids_str)

        if server_proc and not STOP_EVENT.is_set():
            if not await is_running(server_proc):
                ec = await server_proc.wait()
                service.log_info(
                    f"process {server_proc} exited with code: {ec}, "
                    f"needs to be restarted")
                server_proc = None

    if server_proc:
        await (await asyncio.create_subprocess_shell(
            f"taskkill.exe /pid {server_proc.pid} > nul 2>&1"
        )).wait()
        # A bit of grace shutdown time.
        await asyncio.sleep(1.0)

        # The nuclear option in case it hung.
        _pids = read_pids(pidfile_path)
        await terminate_many(_pids)
        await terminate_server(server_proc, timeout=1.0)

    ASYNC_MAIN_DONE_EVENT.set()
    pidfile_path.unlink(missing_ok=True)


def main() -> None:
    global CONFIG_PATH

    ap = argparse.ArgumentParser()
    _, svc_args = ap.parse_known_args()

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.touch(exist_ok=True)

    if "debug" not in svc_args:
        # No point in logging to stdout inside the actual service!
        logger.remove(stdout_handler_id)

    svc_args = [sys.argv[0]] + svc_args
    BOWinServerService.parse_args(svc_args)

    # When we get here it's safe to assume the service has been
    # installed and the registry entries for it exist.
    if "install" in svc_args:
        if not (_bo_log_file := get_var("BO_LOG_FILE", None)):
            # Avoid writing to the "regular" log file form the service.
            # TODO: this is still kinda error prone and the logging setup
            #   should definitely be improved.
            raise RuntimeError(
                "BO_LOG_FILE is required to be set for the service environment")

        # TODO: could be error prone, but fuck it.
        cfg_dict = {
            key: os.environ[key]
            for key in os.environ
            if key.startswith("BO_")
        }
        log_info(f"storing {len(cfg_dict)} env vars that stared with 'BO_'")
        CONFIG_PATH.write_bytes(orjson.dumps(cfg_dict))

    if "remove" in svc_args:
        cfg_dir = get_config_dir()
        log_info(f"removing service config directory: '{cfg_dir}'")
        shutil.rmtree(cfg_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as _e:
        _msg = f"unhandled exception: {type(_e).__name__}: {_e}"
        log_error(_msg)
        print(_msg)
        raise
