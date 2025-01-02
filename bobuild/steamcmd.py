import asyncio
import datetime as dt
import platform
import re
import tempfile
import zipfile
from pathlib import Path

import httpx
import tqdm
import vdf

from bobuild.log import logger
from bobuild.utils import RS2_GAME_INSTALL_DIR
from bobuild.utils import RS2_SERVER_INSTALL_DIR
from bobuild.utils import get_var

# Windows only variables.
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
_default_steamcmd_install_dir = r"C:\steamcmd\\"
STEAMCMD_INSTALL_DIR = Path(get_var("BO_STEAMCMD_INSTALL_DIR",
                                    _default_steamcmd_install_dir)).resolve()
STEAMCMD_EXE = STEAMCMD_INSTALL_DIR / "steamcmd.exe"

RS2_APPID = 418460
RS2_SDK_APPID = 418500
RS2_DS_APPID = 418480

STEAMCMD_USERNAME = get_var("BO_STEAMCMD_USERNAME")
STEAMCMD_PASSWORD = get_var("BO_STEAMCMD_PASSWORD")


async def run_cmd(
        *args: str,
        raise_on_error: bool = False,
        return_output: bool = False,
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

    logger.info("running SteamCMD command: '{}'", steamcmd_args)
    proc = await asyncio.create_subprocess_exec(
        str(STEAMCMD_EXE),
        *steamcmd_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
            logger.info("SteamCMD stdout: " + out)
            if return_output:
                all_out.append(out)
        err = (await proc.stderr.readline()
               ).decode("utf-8", errors="replace").rstrip()
        if err:
            logger.info("SteamCMD stderr: " + err)
            if return_output:
                all_err.append(err)

    ec = await proc.wait()
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
        raise NotImplemented("https://developer.valvesoftware.com/wiki/SteamCMD#Linux")


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


async def download_windows_zip() -> tuple[Path, bool]:
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

    logger.info("downloading '{}' to '{}'...", STEAMCMD_URL, dl_file)
    client = httpx.AsyncClient()
    async with client.stream(
            "GET",
            STEAMCMD_URL,
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


async def install_update_steamcmd_windows():
    zip_path, new_zip = await download_windows_zip()
    STEAMCMD_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    if new_zip:
        logger.info("extracting steamcmd.zip to '{}'...", STEAMCMD_INSTALL_DIR)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(STEAMCMD_INSTALL_DIR)

    await dry_run()


async def is_app_installed(app_dir: Path, app_id: int) -> bool:
    """Returns True if app is installed AND up to date."""

    logger.info("checking app ID {} is installed in '{}'",
                app_id, app_dir)

    _, out, err = await run_cmd(
        "+force_install_dir", str(app_dir),
        "+login", STEAMCMD_USERNAME, STEAMCMD_PASSWORD,
        "+app_info_update", "1",
        "+app_status", str(app_id),
        "+app_info_print", str(app_id),
        "+logoff",
        "+quit",
        raise_on_error=True,
        return_output=True
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


async def install_validate_app(install_dir: Path, app_id: int):
    await run_cmd(
        "+force_install_dir", str(install_dir),
        "+login", STEAMCMD_USERNAME, STEAMCMD_PASSWORD,
        f'"+app_update {app_id} validate"',
        "+quit",
        raise_on_error=True,
    )


async def is_rs2_installed() -> bool:
    return await is_app_installed(RS2_GAME_INSTALL_DIR, RS2_APPID)


async def is_rs2_sdk_installed() -> bool:
    return await is_app_installed(RS2_GAME_INSTALL_DIR, RS2_SDK_APPID)


async def is_rs2_server_installed() -> bool:
    return await is_app_installed(RS2_SERVER_INSTALL_DIR, RS2_DS_APPID)


async def dry_run():
    """Run SteamCMD and login as anonymous user to let it
    auto-update itself.
    """
    await run_cmd(
        "+login",
        "anonymous",
        "+exit",
        # TODO: SteamCMD exit codes are undocumented!
        # raise_on_error=True,
    )


async def main() -> None:
    await install_update_steamcmd()

    rs2_installed = await is_rs2_installed()
    rs2_sdk_installed = await is_rs2_sdk_installed()
    rs2_server_installed = await is_rs2_server_installed()

    logger.info("rs2_installed={}", rs2_installed)
    logger.info("rs2_sdk_installed={}", rs2_sdk_installed)
    logger.info("rs2_server_installed={}", rs2_server_installed)


if __name__ == "__main__":
    asyncio.run(main())
