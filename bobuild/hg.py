import asyncio
import os

from loguru import logger

HG_USERNAME = os.environ["BO_HG_USERNAME"]
HG_PASSWORD = os.environ["BO_HG_PASSWORD"]
HG_PKG_REPO_PATH = os.environ["BO_HG_PKG_REPO_PATH"]
HG_MAPS_REPO_PATH = os.environ["BO_HG_MAPS_REPO_PATH"]
HG_PKG_REPO_URL = os.environ["BO_HG_PKG_REPO_URL"]
HG_MAPS_REPO_URL = os.environ["BO_HG_MAPS_REPO_URL"]

logger  # TODO: set up file logging!


async def run_hg_cmd() -> int:
    proc = await asyncio.create_subprocess_exec(
        "hg",

    )

    # proc.

    return await proc.wait()


async def sync_packages() -> None:
    pass


async def sync_maps() -> None:
    pass


async def main() -> None:
    await sync_packages()
    await sync_maps()


if __name__ == "__main__":
    asyncio.run(main())
