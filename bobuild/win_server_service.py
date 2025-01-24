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
import random
import shutil
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

import discord
import orjson
import psutil
import servicemanager
import win32api
import win32con
import win32service
import win32serviceutil
from redis.asyncio import Redis
from redis.asyncio.lock import Lock

from bobuild.bo_discord import send_webhook
from bobuild.config import DiscordConfig
from bobuild.config import RS2Config
from bobuild.config import SteamCmdConfig
from bobuild.log import logger
from bobuild.log import stdout_handler_id
from bobuild.multiconfig import MultiConfigParser
from bobuild.steamcmd import RS2_APPID
from bobuild.steamcmd import download_workshop_item_many
from bobuild.steamcmd import install_validate_app
from bobuild.steamcmd import workshop_status
from bobuild.tasks import bo_build_lock_name
from bobuild.tasks import shared_redis_pool
from bobuild.tasks_bo import gather
from bobuild.utils import asyncio_run
from bobuild.utils import get_var
from bobuild.utils import utcnow
from bobuild.webadmin import WebAdmin
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
        asyncio_run(wrap_main_task(
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


def read_manifest(
        rs2_cfg: RS2Config,
        # item_id: id,
) -> WorkshopManifest:
    raise NotImplementedError
    # TODO: do we read
    # manifest_dir = rs2_cfg.server_workshop_dir
    # return WorkshopManifest()


def make_bo_map_cycles(rs2_config: RS2Config, round_limit: int = 2) -> list[str]:
    map_names = list(rs2_config.bo_dev_beta_map_ids)
    random.shuffle(map_names)
    maps_str = ",".join(f'"{x}"' for x in map_names)
    limits = (f"{round_limit}," * len(map_names)).rstrip(",")
    map_cycle_str = f'(Maps=({maps_str}),RoundLimits=({limits}))'
    return [map_cycle_str]


T = TypeVar("T")


def ensure_list_contains(lst: list[T], *args: T) -> list[T]:
    for item in args:
        if item not in lst:
            lst.append(item)
    return lst


def ensure_server_config(
        rs2_cfg: RS2Config,
):
    web = rs2_cfg.server_install_dir / "ROGame/Config/ROWeb.ini"
    engine = rs2_cfg.server_install_dir / "ROGame/Config/ROEngine.ini"
    game = rs2_cfg.server_install_dir / "ROGame/Config/ROGame.ini"
    webadmin = rs2_cfg.server_install_dir / "ROGame/Config/ROWebAdmin.ini"
    # memberdb = rs2_cfg.server_install_dir / "ROGame/Config/ROMemberDb.ini"

    # ########################################################################
    # ROGame.ini
    # ########################################################################

    game_cfg = MultiConfigParser()
    game_cfg.read(game)
    game_cfg["Engine.GameReplicationInfo"]["ShortName"] = "BOServer"
    game_cfg["Engine.GameReplicationInfo"]["ServerName"] = "Black Orchestra Dev Server"
    game_cfg["ROGame.ROGameReplicationInfo"]["bLogVoting"] = "True"
    game_cfg["ROGame.ROGameInfo"]["AdminContact"] = "https://www.blackorchestra.net"
    game_cfg["ROGame.ROGameInfo"]["bEnableMapVoting"] = "True"
    game_cfg["ROGame.ROGameInfo"]["MapRepeatLimit"] = "3"
    game_cfg["ROGame.ROGameInfo"]["ClanMotto"] = "Black Orchestra Dev Server"
    game_cfg["ROGame.ROGameInfo"]["ServerMOTD"] = "Welcome to the Black Orchestra development test server!"
    game_cfg["ROGame.ROGameInfo"]["WebLink"] = "https://www.blackorchestra.net"
    game_cfg["ROGame.ROGameInfo"]["WebLinkColor"] = "(B=0,G=0,R=255,A=255)"
    game_cfg["ROGame.ROGameInfo"]["BannerLink"] = "TODO"
    game_cfg["Engine.GameInfo"]["MaxPlayers"] = "64"
    game_cfg["Engine.AccessControl"]["AdminPassword"] = rs2_cfg.server_admin_password
    game_cfg["Engine.AccessControl"]["GamePassword"] = "boserverpassword"  # TODO: generate new one for each build?
    game_cfg["Engine.AccessControl"]["IPPolicies"] = "ACCEPT;*"
    game_cfg["ROGame.ROMembers"]["bBroadcastWelcomeMembers"] = "True"
    game_cfg["ROGame.ROMembers"]["bAutoSignInAdmins"] = "True"
    game_cfg["ROGame.ROMembers"]["bAdminsSupersedeNormalMembers"] = "True"
    game_cfg["ROGame.ROMembers"]["bRestrictAdminLoginToMembersOnly"] = "True"
    game_cfg["ROGame.ROTracking"]["DeleteTrackRecordsOlderThan"] = "0"
    game_cfg["ROGame.ROTracking"]["DeleteTrackRecordsIfNotSeenAfter"] = "0"

    map_cycles = make_bo_map_cycles(rs2_cfg)
    game_cfg["ROGame.ROGameInfo"]["GameMapCycles"] = "\n".join(map_cycles)
    game_cfg["ROGame.ROGameInfo"]["ActiveMapCycle"] = "0"

    with game.open("w") as f:
        game_cfg.write(f, space_around_delimiters=False)

    # ########################################################################
    # ROEngine.ini
    # ########################################################################

    engine_cfg = MultiConfigParser()
    engine_cfg.read(engine)

    engine_cfg["URL"]["GameName"] = "Black Orchestra"
    engine_cfg["LogFiles"]["PurgeLogsDays"] = "365"

    tw_sws_key = "OnlineSubsystemSteamworks.TWWorkshopSteamworks"
    if tw_sws_key not in engine_cfg:
        engine_cfg[tw_sws_key] = {}
    item_ids = engine_cfg[tw_sws_key].getlist("ServerSubscribedWorkshopItems") or []
    item_ids = ensure_list_contains(
        item_ids,
        *(
            rs2_cfg.bo_dev_beta_workshop_id,
            *rs2_cfg.bo_dev_beta_map_ids.keys(),
        ),
    )
    engine_cfg[tw_sws_key]["ServerSubscribedWorkshopItems"] = "\n".join(sorted(item_ids))

    dl_mgrs = [
        "OnlineSubsystemSteamworks.TWWorkshopSteamworks",
        "OnlineSubsystemSteamworks.SteamWorkshopDownload",
        "IpDrv.HTTPDownload",
    ]
    engine_cfg["IpDrv.TcpNetDriver"]["DownloadManagers"] = "\n".join(dl_mgrs)
    engine_cfg["IpDrv.TcpNetDriver"]["NetServerMaxTickRate"] = "35"  # TODO: see how CPU handles this!

    suppressions = engine_cfg["Core.System"].getlist("Suppress") or []
    if "DevBalanceStats" in suppressions:
        suppressions.remove("DevBalanceStats")
    if "DevOnlineWorkshop" in suppressions:
        suppressions.remove("DevOnlineWorkshop")
    if "Init" in suppressions:
        suppressions.remove("Init")
    if "GameStats" in suppressions:
        suppressions.remove("GameStats")
    if "DevShaders" in suppressions:
        suppressions.remove("DevShaders")
    if "DevConfig" in suppressions:
        suppressions.remove("DevConfig")
    engine_cfg["Core.System"]["Suppress"] = "\n".join(suppressions)

    with engine.open("w") as f:
        engine_cfg.write(f, space_around_delimiters=False)

    # ########################################################################
    # ROWeb.ini
    # ########################################################################

    # Keep ROWeb.ini read-only outside these modifications due to
    # daylight saving resetting some RS2 configs to defaults, which
    # leads to WebAdmin being disabled after the server starts up.
    attrs: int = win32api.GetFileAttributes(str(web))
    win32api.SetFileAttributes(str(web), attrs & ~win32con.FILE_ATTRIBUTE_READONLY)
    web_cfg = MultiConfigParser()
    web_cfg.read(web)
    web_cfg["IpDrv.WebServer"]["bEnabled"] = "true"
    web_cfg["IpDrv.WebServer"]["ListenPort"] = "8080"
    with web.open("w") as f:
        web_cfg.write(f, space_around_delimiters=False)
    win32api.SetFileAttributes(str(web), attrs | win32con.FILE_ATTRIBUTE_READONLY)

    # ########################################################################
    # ROWebAdmin.ini
    # ########################################################################

    wa_cfg = MultiConfigParser()
    wa_cfg.read(webadmin)
    wa_cfg["WebAdmin.WebAdmin"]["bChatLog"] = "True"
    wa_cfg["WebAdmin.WebAdmin"]["AuthenticationClass"] = "WebAdmin.MultiWebAdminAuth"
    wa_cfg["WebAdmin.Chatlog"]["bUnique"] = "True"
    wa_cfg["WebAdmin.Chatlog"]["bIncludeTimeStamp"] = "True"
    with webadmin.open("w") as f:
        wa_cfg.write(f, space_around_delimiters=False)

    # ########################################################################
    # ROMemberDb.ini
    # ########################################################################

    # TODO: DO WE WANT TO MANAGE THIS AUTOMATICALLY?
    # member_cfg = MultiConfigParser()
    # member_cfg.read(memberdb)
    # members = member_cfg["ROGame.MemberDb"].getlist("Table_Members") or []
    # members = ensure_list_contains(
    #     members,
    #     "",
    # )
    # member_cfg["ROGame.MemberDb"]["Table_Members"] = "\n".join(members)
    # with memberdb.open("w") as f:
    #     member_cfg.write(f, space_around_delimiters=False)


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


async def wrap_main_task(
        service: BOWinServerService,
        rs2_config: RS2Config,
        steamcmd_config: SteamCmdConfig,
        discord_config: DiscordConfig,
):
    try:
        await main_task(
            service=service,
            rs2_config=rs2_config,
            steamcmd_config=steamcmd_config,
            discord_config=discord_config,
        )
    except (Exception, asyncio.CancelledError) as e:
        try:
            service.log_error(f"main_task error: {type(e).__name__}: {e}")
            desc = f"```\n{traceback.format_exc()}```"
            await send_webhook(
                url=discord_config.server_service_webhook_url,
                embed_title="Error Running BO Server! :loudspeaker:",
                embed_description=desc,
                embed_color=discord.Color.dark_red(),
                embed_timestamp=utcnow(),
                embed_footer="Black Orchestra Dedicated Server",
            )
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            raise
    finally:
        # TODO: what were we supposed to do here?
        #  Ensure processes cleaned up?
        raise


async def notify_shutdown(
        discord_config: DiscordConfig,
        embed_title: str,
        embed_footer: str,
        message: str,
        web_admin: WebAdmin,
):
    await send_webhook(
        url=discord_config.server_service_webhook_url,
        embed_title=embed_title,
        embed_description=message,
        embed_color=discord.Color.blue(),
        embed_timestamp=utcnow(),
        embed_footer=embed_footer,
    )
    for x in range(10):
        await web_admin.send_message(message)
        await asyncio.sleep(0.1)


def install_workshop_item():
    pass


async def install_workshop_content(
        service: BOWinServerService,
        content_dir: Path,
        cache_dir: Path,
        item_ids: list[int],
):
    service.log_info(
        f"installing workshop content, content_dir='{content_dir}', "
        f"cache_dir='{cache_dir}'"
    )
    item_dirs = (d for d in content_dir.iterdir() if d.is_dir())

    pool = asyncio.get_running_loop()
    workers = max(((os.cpu_count() or 1) - 2), 1)
    install_tasks = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for item_dir in item_dirs:
            try:
                item_id = int(item_dir.name)
            except ValueError as e:
                service.log_warning(
                    "invalid workshop content directory: "
                    f"'{item_dir}': cannot convert dir name to ID: {e}")
                continue
            if item_id not in item_ids:
                service.log_info(
                    f"found item {item_id} in content dir, but it is not found in"
                    "list of item IDS to install, skipping")
                continue

            service.log_info(f"installing item: {item_id}")
            inis = item_dir.glob("*.ini")
            # TODO: need to update this if we get more localization languages!
            ints = item_dir.glob("*.int")

            install_tasks.append(pool.run_in_executor(
                executor, install_workshop_item))

    await gather(*install_tasks)


async def main_task(
        service: BOWinServerService,
        rs2_config: RS2Config,
        steamcmd_config: SteamCmdConfig,
        discord_config: DiscordConfig,
) -> None:
    global ASYNC_MAIN_DONE_EVENT

    embed_title = "BO Server Status Update! :mega:"
    embed_footer = "BO Dedicated Server"

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

    # TODO: is it enough to download the binaries here? Do we need to
    #   check their state regularly?
    service.log_info("installing Steamworks SDK Redist")
    await install_validate_app(
        steamcmd_config.exe_path,
        install_dir=rs2_config.server_install_dir / "Binaries/Win64",
        app_id=1007,  # Steamworks SDK Redist.
        username="anonymous",
        password="",
    )

    all_item_ids = [rs2_config.bo_dev_beta_workshop_id] + list(
        rs2_config.bo_dev_beta_map_ids.values()
    )
    service.log_info(f"total SWS items: {len(all_item_ids)}")

    service.log_info("setting up WebAdmin client")
    wa = WebAdmin(
        username=rs2_config.server_admin_username,
        password=rs2_config.server_admin_password,
        url="http://100.100.72.124:8080",  # TODO: put this in config?
    )

    redis = Redis.from_pool(shared_redis_pool)
    lock: Lock | None = None
    acquired = False

    # TODO: refactor to reduce nesting.
    service.log_info("entering main service loop")
    while not await asyncio.wait_for(STOP_EVENT.wait(), timeout=1.0):
        if time.time() > (update_check_interval + update_check_time):
            try:
                lock = redis.lock(bo_build_lock_name, timeout=180 * 60, blocking=True)
                acquired = await lock.acquire(blocking=True, blocking_timeout=0.1)
                if acquired:
                    service.log_info("checking for BO Steam Workshop updates")

                    sws_status = await workshop_status(
                        steamcmd_config.exe_path,
                        download_dir=rs2_config.server_workshop_dir,
                        username=steamcmd_config.username,
                        password=steamcmd_config.password,
                    )
                    service.log_info(f"workshop status: {sws_status}")

                    items_needing_update = [
                        status[0] for status in sws_status
                        if status[1] != "installed"
                    ]
                    installed_ids = [status[0] for status in sws_status]
                    for item_id in all_item_ids:
                        if item_id not in installed_ids:
                            service.log_info(f"SWS item {item_id} is not installed")
                            items_needing_update.append(item_id)

                    if items_needing_update:
                        service.log_info(f"items needing update/install: {items_needing_update}")
                        desc = ("Updating/installing the following Workshop items: "
                                f"{", ".join(str(x) for x in items_needing_update)}")
                        await send_webhook(
                            url=discord_config.server_service_webhook_url,
                            embed_title=embed_title,
                            embed_description=desc,
                            embed_color=discord.Color.blue(),
                            embed_timestamp=utcnow(),
                            embed_footer=embed_footer,
                        )

                        await download_workshop_item_many(
                            steamcmd_config.exe_path,
                            download_dir=rs2_config.server_workshop_dir,
                            workshop_item_ids=items_needing_update,
                            username=steamcmd_config.username,
                            password=steamcmd_config.password,
                        )

                        # Shut down BO server if it's running.
                        if server_proc is not None:
                            service.log_info(f"terminating running server process: {server_proc}")
                            await notify_shutdown(
                                discord_config,
                                embed_title=embed_title,
                                embed_footer=embed_footer,
                                message="Shutting down BO server for updates.",
                                web_admin=wa,
                            )
                            await asyncio.sleep(2.0)  # Small grace period.
                            try:
                                pids = read_pids(pidfile_path)
                                await terminate_many(pids)
                                await terminate_server(server_proc)
                            except psutil.Error as e:
                                service.log_warning(f"{type(e).__name__}: {e}")
                        else:
                            service.log_info("no server process running, no need to terminate")

                        content_dir = rs2_config.server_workshop_dir / f"content/{RS2_APPID}/"
                        cache_dir = rs2_config.server_cache_dir
                        await install_workshop_content(
                            service=service,
                            content_dir=content_dir,
                            cache_dir=cache_dir,
                            item_ids=workshop_items,
                        )

                        await send_webhook(
                            url=discord_config.server_service_webhook_url,
                            embed_title=embed_title,
                            embed_description="Done updating Workshop items.",
                            embed_color=discord.Color.blue(),
                            embed_timestamp=utcnow(),
                            embed_footer=embed_footer,
                        )
                else:
                    service.log_info("could not acquire build lock, checking for updates later")
            except Exception as e:
                service.log_error(f"error checking for updates: {type(e).__name__}: {e}")
                raise
            finally:
                if lock and acquired:
                    try:
                        await lock.release()
                    except Exception as e:
                        service.log_error(f"error releasing lock: {type(e).__name__}: {e}")

            update_check_time = time.time()

        if not server_proc:
            service.log_info("server is not running, starting it")
            await send_webhook(
                url=discord_config.server_service_webhook_url,
                embed_title=embed_title,
                embed_description="Starting BO server.",
                embed_color=discord.Color.blue(),
                embed_timestamp=utcnow(),
                embed_footer=embed_footer,
            )

            # log_info("running server start script")
            # changelist = read_changelist(build_id_file_path)
            # full_server_name = f"{server_name} {changelist}"
            # server_proc = await asyncio.create_subprocess_exec(
            #     "powershell.exe",
            #     "-NoProfile",
            #     "-ExecutionPolicy", "Bypass",
            #     str(script_path),
            #     *(
            #         f"-ServerName \"{full_server_name}\"",
            #         f"-Branch \"{branch}\"",
            #         f"-Port \"{port}\"",
            #         f"-QueryPort \"{query_port}\"",
            #     ),
            #     stderr=asyncio.subprocess.STDOUT,
            # )
            # Wait a bit to let it start up fully.
            # TODO: is this stupid?
            await asyncio.sleep(1.0)

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
                rc = server_proc.returncode
                service.log_info(
                    f"process {server_proc} exited with code: {rc}, "
                    f"needs to be restarted")
                server_proc = None
                await asyncio.sleep(3.0)

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

    pidfile_path.unlink(missing_ok=True)

    # noinspection PyBroadException
    try:
        await redis.close()
    except Exception:
        pass

    ASYNC_MAIN_DONE_EVENT.set()


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
