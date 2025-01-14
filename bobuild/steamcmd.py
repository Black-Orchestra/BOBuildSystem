import argparse
import asyncio
import datetime as dt
import platform
import re
import tempfile
import zipfile
from functools import partial
from pathlib import Path
from typing import Literal
from typing import overload

import httpx
import tqdm
import vdf

from bobuild.config import RS2Config
from bobuild.config import SteamCmdConfig
from bobuild.log import logger
from bobuild.run import run_process
from bobuild.utils import asyncio_run
from bobuild.utils import kill_process_tree
from bobuild.utils import redact

# TODO: put these in a config class?
RS2_APPID = 418460
RS2_SDK_APPID = 418500
RS2_DS_APPID = 418480

_script_dir = Path(__file__).parent


@overload
async def run_cmd(
        steamcmd_path: Path,
        *args: str,
        raise_on_error: bool = False,
        return_output: Literal[True] = ...,
        steamguard_code: str | None = None,
) -> tuple[int, str, str]:
    ...


@overload
async def run_cmd(
        steamcmd_path: Path,
        *args: str,
        raise_on_error: bool = False,
        return_output: Literal[False] = ...,
        steamguard_code: str | None = None,
) -> tuple[int, None, None]:
    ...


async def run_cmd(
        steamcmd_path: Path,
        *args: str,
        raise_on_error: bool = False,
        return_output: bool = False,
        steamguard_code: str | None = None,
) -> tuple[int, None | str, None | str]:
    """Run SteamCMD command.
    If return_output is True, returns a tuple
    (exit code, stdout, stderr), else
    returns a tuple (exit code, None, None).

    TODO: USE ASYNCIO TIMEOUTS!
    """

    steamcmd_args = [
        *args,
    ]

    if steamguard_code is not None:
        # TODO: this is a VERY dirty hack. What if password argument was not provided?
        login_idx = steamcmd_args.index("+login")
        steamcmd_args = (
                steamcmd_args[:login_idx + 3]
                + [steamguard_code]
                + steamcmd_args[login_idx + 3:]
        )

        # TODO: redacting it here is a bit pointless unless we do it everywhere?
        logger.info("running SteamCMD command: '{}'",
                    redact(steamguard_code, steamcmd_args))
    else:
        logger.info("running SteamCMD command: '{}'", steamcmd_args)

    # NOTE: we have to run SteamCMD through a PowerShell script
    # because for some unknown reason running it directly through
    # create_subprocess_exec or create_subprocess_shell causes it
    # to exit almost immediately without running the desired commands!
    script = str(_script_dir / "ps/steamcmd.ps1")
    args_str = " ".join(steamcmd_args)

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            f"powershell.exe",
            "-ExecutionPolicy", "ByPass",
            "-File", script,
            "-SteamCMDExePath", str(steamcmd_path),
            "-Args", args_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(steamcmd_path.parent.resolve()),
        )

        all_out = []
        all_err = []

        if not proc.stdout:
            raise RuntimeError(f"process has no stdout: {proc}")
        if not proc.stderr:
            raise RuntimeError(f"process has no stderr: {proc}")

        while True:
            if proc.stdout.at_eof() and proc.stderr.at_eof():
                break

            out = (await proc.stdout.readline()
                   ).decode("utf-8", errors="replace").rstrip()
            if out:
                logger.info("SteamCMD stdout: {}", out)
                if return_output:
                    all_out.append(out)
            err = (await proc.stderr.readline()
                   ).decode("utf-8", errors="replace").rstrip()
            if err:
                logger.info("SteamCMD stderr: {}", err)
                if return_output:
                    all_err.append(err)

        ec = await proc.wait()

    except (KeyboardInterrupt, Exception, asyncio.CancelledError) as e:
        logger.error("error: {}: {}", type(e).__name__, e)
        if proc:
            await kill_process_tree(proc.pid)
        raise

    logger.info("SteamCMD command exited with code: {}", ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"command exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def install_update_steamcmd():
    if platform.system() == "Windows":
        await install_update_steamcmd_windows()
    else:
        raise NotImplementedError("https://developer.valvesoftware.com/wiki/SteamCMD#Linux")


def file_is_older_than(
        file: Path,
        delta: dt.timedelta,
) -> bool:
    mtime = file.stat().st_mtime
    now = dt.datetime.now(tz=dt.timezone.utc)
    mod_dt = dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc)
    if (mod_dt + delta) > now:
        return False
    return True


async def download_windows_zip(
        steamcmd_download_url: str,
) -> tuple[Path, bool]:
    """Download steamcmd.zip to a temporary location.
    Return tuple where the first item is the .zip path and second
    item is a bool indicating whether the file was downloaded.
    False indicates the file existed and was new enough to not
    be re-downloaded.
    """
    tmpdir = Path(tempfile.gettempdir()).resolve() / "steamcmd/"
    tmpdir.mkdir(parents=True, exist_ok=True)
    dl_file = tmpdir / "steamcmd.zip"

    delta = dt.timedelta(hours=6)
    if dl_file.exists() and not file_is_older_than(dl_file, delta):
        logger.info(
            "'{}' is newer than {} hours, not re-downloading it",
            dl_file, delta.total_seconds() / 60 / 60)
        return dl_file, False

    logger.info("downloading '{}' to '{}'...", steamcmd_download_url, dl_file)
    client = httpx.AsyncClient()
    async with client.stream(
            "GET",
            steamcmd_download_url,
            timeout=30.0,
            follow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        total = int(resp.headers["Content-Length"])
        chunk_size = 1024 * 1024

        with dl_file.open("wb") as f:
            # TODO: this does not get removed in case of error down the line.
            # TODO: refactor this to reduce levels of nestedness.
            # TODO: even with the logger added here, any other logs will
            #       mess up the logging output. Need a better solution?
            x = logger.add(lambda msg: tqdm.tqdm.write(msg, end=""), colorize=True)
            with tqdm.tqdm(total=total, unit_scale=True, unit_divisor=1024,
                           unit="B") as progress:
                num_bytes_downloaded = resp.num_bytes_downloaded
                async for data in resp.aiter_bytes(chunk_size=chunk_size):
                    f.write(data)
                    progress.update(resp.num_bytes_downloaded - num_bytes_downloaded)
                    num_bytes_downloaded = resp.num_bytes_downloaded
            logger.remove(x)

    return dl_file, True


async def install_update_steamcmd_windows(
        download_url: str,
        install_dir: Path,
) -> None:
    zip_path, new_zip = await download_windows_zip(download_url)
    install_dir.mkdir(parents=True, exist_ok=True)

    if new_zip:
        logger.info("extracting steamcmd.zip to '{}'...", install_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(install_dir)

    await dry_run(install_dir / "steamcmd.exe")


async def is_app_installed(
        steamcmd_path: Path,
        app_dir: Path,
        app_id: int,
        username: str,
        password: str,
        steamguard_code: str | None = None,
) -> bool:
    """Returns True if app is installed AND up to date."""

    logger.info("checking app ID {} is installed in '{}'",
                app_id, app_dir)

    _, out, err = await run_cmd(
        steamcmd_path,
        "+force_install_dir", str(app_dir),
        "+login", username, password,
        "+app_info_update", "1",
        "+app_status", str(app_id),
        "+app_info_print", str(app_id),
        "+logoff",
        "+quit",
        raise_on_error=True,
        return_output=True,
        steamguard_code=steamguard_code,
    )

    out += err

    install_state_found = False
    build_id = 0

    lines = out.split("\n")
    for i, line in enumerate(lines):
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
                    return False
                # TODO: this check is unreliable! There might still be an update!
                # elif state == "Fully Installed":
                #    return True
                elif state.lower() == "uninstalled":
                    return False
        # - size on disk: 13978936396 bytes, BuildID 16715839
        elif "size on disk:" in line:
            build_id = int(line.split("BuildID")[-1].strip())
            logger.info("current BuildID: {}", build_id)

    if not install_state_found:
        logger.warning("'install state:' line not found in steamcmd output")

    # Install state is not reliable, check app_info_print output too.
    pattern = re.compile(fr".*(\"{app_id}\"[\r\n]+{{.*}}).*", flags=re.DOTALL)
    if match := pattern.match(out):
        try:
            data = vdf.loads(match.group(1))
            # TODO: double-check 'public' is the correct branch for all apps!
            latest_build_id = int(data[str(app_id)]["depots"]["branches"]["public"]["buildid"])
            logger.info("latest BuildID: {}", latest_build_id)
            if latest_build_id != build_id:
                return False
        except Exception as e:
            logger.error("error parsing VDF: {}: {}", type(e).__name__, e)
    else:
        logger.warning("pattern {} does not match output", pattern)

    return True


async def workshop_build_item(
        steamcmd_path: Path,
        username: str,
        password: str,
        item_config_path: Path,
        steamguard_code: str | None = None,
) -> None:
    await run_cmd(
        steamcmd_path,
        "+login", username, password,
        "+workshop_build_item",
        str(item_config_path.resolve()),
        "+quit",
        raise_on_error=True,
        steamguard_code=steamguard_code,
    )


async def workshop_build_item_many(
        steamcmd_path: Path,
        username: str,
        password: str,
        item_config_paths: list[Path],
        steamguard_code: str | None = None,
) -> None:
    args = [
        "+login", username, password,
    ]

    for cfg_path in item_config_paths:
        args.append("+workshop_build_item")
        args.append(str(cfg_path.resolve()))

    args += ["+quit"]

    await run_cmd(
        steamcmd_path,
        *args,
        raise_on_error=True,
        steamguard_code=steamguard_code,
    )


async def install_validate_app(
        steamcmd_path: Path,
        install_dir: Path,
        app_id: int,
        username: str,
        password: str,
        steamguard_code: str | None = None,
) -> None:
    args = [
        "+force_install_dir", str(install_dir),
        "+login", username
    ]

    if username == "anonymous":
        steamguard_code = None
    else:
        args.append(password)

    args += [
        f"+app_update {app_id} validate",
        "+quit",
    ]

    await run_cmd(
        steamcmd_path,
        *args,
        raise_on_error=True,
        steamguard_code=steamguard_code,
    )


async def dry_run(steamcmd_path: Path):
    """Run SteamCMD and login as anonymous user to let it
    auto-update itself.
    """
    await run_cmd(
        steamcmd_path,
        "+login",
        "anonymous",
        "+exit",
        # TODO: SteamCMD exit codes are undocumented!
        # raise_on_error=True,
    )


async def get_steamguard_code(
        steamguard_cli_path: Path,
        passkey: str,
) -> str:
    out = (await run_process(
        steamguard_cli_path,
        "-p", passkey,
        cwd=steamguard_cli_path.parent,
        raise_on_error=True,
        return_output=True,
        redact=partial(redact, passkey),
    ))[1]

    return out.strip()


async def install_rs2(
        config: RS2Config,
        steamcmd_config: SteamCmdConfig,
):
    code = await get_steamguard_code(
        steamcmd_config.steamguard_cli_path,
        steamcmd_config.steamguard_passkey,
    )
    await install_validate_app(
        steamcmd_config.exe_path,
        install_dir=config.game_install_dir,
        app_id=RS2_APPID,
        username=steamcmd_config.username,
        password=steamcmd_config.password,
        steamguard_code=code,
    )


async def install_rs2_sdk(
        config: RS2Config,
        steamcmd_config: SteamCmdConfig,
):
    code = await get_steamguard_code(
        steamcmd_config.steamguard_cli_path,
        steamcmd_config.steamguard_passkey,
    )
    await install_validate_app(
        steamcmd_config.exe_path,
        install_dir=config.game_install_dir,
        app_id=RS2_SDK_APPID,
        username=steamcmd_config.username,
        password=steamcmd_config.password,
        steamguard_code=code,
    )


async def install_rs2_server(
        config: RS2Config,
        steamcmd_config: SteamCmdConfig,
):
    await install_validate_app(
        steamcmd_config.exe_path,
        install_dir=config.server_install_dir,
        app_id=RS2_DS_APPID,
        username="anonymous",
        password="",
        steamguard_code=None,
    )


async def main() -> None:
    ap = argparse.ArgumentParser()

    cfg = RS2Config()
    rs2_game_path = cfg.game_install_dir
    rs2_server_path = cfg.server_install_dir
    logger.info("rs2_game_path: '{}'", rs2_game_path)
    logger.info("rs2_server_path: '{}'", rs2_server_path)

    action_choices = {
        "install_rs2": install_rs2,
        "install_rs2_sdk": install_rs2_sdk,
        "install_rs2_server": install_rs2_server,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )

    steamcmd_cfg = SteamCmdConfig()

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action](cfg, steamcmd_cfg)
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
