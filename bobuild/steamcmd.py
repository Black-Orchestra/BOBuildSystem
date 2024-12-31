import asyncio
import platform
import tempfile
from pathlib import Path

import httpx
import tqdm

from bobuild.log import logger
from bobuild.utils import get_var

# Windows only variables.
STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
STEAMCMD_INSTALL_DIR = ""

STEAMCMD_USERNAME = get_var("BO_STEAMCMD_USERNAME")
STEAMCMD_PASSWORD = get_var("BO_STEAMCMD_PASSWORD")


async def install_update_steamcmd():
    if platform.system() == "Windows":
        await install_stemacmd_windows()
    else:
        raise NotImplemented("https://developer.valvesoftware.com/wiki/SteamCMD#Linux")


async def install_stemacmd_windows():
    tmpdir = Path(tempfile.gettempdir()).resolve() / "steamcmd/"
    tmpdir.mkdir(parents=True, exist_ok=True)
    dl_file = tmpdir / "steamcmd.zip"

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


async def main() -> None:
    await install_update_steamcmd()


if __name__ == "__main__":
    asyncio.run(main())
