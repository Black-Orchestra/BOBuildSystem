import asyncio
import os
from pathlib import Path

from loguru import logger

from multiconfig import MultiConfigParser

# NOTE: allow missing values here on purpose for easy development.
# None of these should be missing in production deployment, however.
HG_USERNAME = os.environ.get("BO_HG_USERNAME", None)
HG_PASSWORD = os.environ.get("BO_HG_PASSWORD", None)
HG_PKG_REPO_PATH = Path(os.environ.get("BO_HG_PKG_REPO_PATH", "./.DUMMY_PKGS/")).resolve()
HG_MAPS_REPO_PATH = Path(os.environ.get("BO_HG_MAPS_REPO_PATH", "./.DUMMY_MAPS/")).resolve()
HG_PKG_REPO_URL = os.environ.get("BO_HG_PKG_REPO_URL", None)
HG_MAPS_REPO_URL = os.environ.get("BO_HG_MAPS_REPO_URL", None)

HG_CONFIG_PATH = (Path.home() / ".hgrc").resolve()

# TODO: use logrotate on Linux if we run this as a service?
logger.add("hg.log", rotation="10 MB", retention=5)


async def hg_run_cmd(*args: str, cwd: Path | None = None) -> int:
    logger.info("running hg command: '{}', cwd={}", args, cwd)

    hg_args = [
        "--noninteractive",
        "--verbose",
        "--pager", "never",
        *args,
    ]
    proc = await asyncio.create_subprocess_exec(
        "hg",
        *hg_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    while True:
        if proc.stdout.at_eof() and proc.stderr.at_eof():
            break

        out = (await proc.stdout.readline()
               ).decode("utf-8", errors="replace")
        if out:
            logger.info(out)
        err = (await proc.stderr.readline()
               ).decode("utf-8", errors="replace")
        if err:
            logger.info(err)

    return await proc.wait()


async def hg_repo_exists(path: Path) -> bool:
    p = str(path.resolve())
    ec = await hg_run_cmd("--cwd", p, "root")
    return ec == 0


async def hg_clone_repo(url: str, path: Path):
    p = str(path.resolve())
    ec = await hg_run_cmd()


async def hg_sync_packages() -> None:
    pass


async def hg_sync_maps() -> None:
    pass


async def hg_incoming(path: Path) -> bool:
    """Returns 0 if there are incoming changes, 1 otherwise."""
    ec = await hg_run_cmd("incoming", cwd=path)
    return ec == 0


def hg_ensure_config():
    if not HG_CONFIG_PATH.exists():
        HG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        HG_CONFIG_PATH.touch(exist_ok=True)

    updated = False

    cfg = MultiConfigParser()
    cfg.read(HG_CONFIG_PATH)

    if "extensions" not in cfg:
        cfg["extensions"] = {}
        updated = True

    if "largefiles" not in cfg["extensions"]:
        cfg["extensions"]["largefiles"] = ""
        updated = True

    if "progress" not in cfg["extensions"]:
        cfg["extensions"]["progress"] = ""
        updated = True

    if "largefiles" not in cfg:
        cfg["largefiles"] = {}
        updated = True

    patterns = cfg["largefiles"].getlist("patterns") or []
    if "**.upkg" not in patterns:
        patterns.append("**.upkg")
        updated = True
    if "**.roe" not in patterns:
        patterns.append("**.roe")
        updated = True
    cfg["largefiles"]["patterns"] = "\n".join(patterns)

    if "auth" not in cfg:
        cfg["auth"] = {}
        updated = True

    if ("bo_packages.prefix" not in cfg["auth"]
            or "bo_packages.username" not in cfg["auth"]
            or "bo_packages.password" not in cfg["auth"]
            or cfg["auth"]["bo_packages.prefix"] != HG_PKG_REPO_URL
            or cfg["auth"]["bo_packages.username"] != HG_USERNAME
            or cfg["auth"]["bo_packages.password"] != HG_PASSWORD
    ):
        cfg["auth"]["bo_packages.prefix"] = HG_PKG_REPO_URL
        cfg["auth"]["bo_packages.username"] = HG_USERNAME
        cfg["auth"]["bo_packages.password"] = HG_PASSWORD
        updated = True

    if ("bo_maps.prefix" not in cfg["auth"]
            or "bo_maps.username" not in cfg["auth"]
            or "bo_maps.password" not in cfg["auth"]
            or cfg["auth"]["bo_maps.prefix"] != HG_MAPS_REPO_URL
            or cfg["auth"]["bo_maps.username"] != HG_USERNAME
            or cfg["auth"]["bo_maps.password"] != HG_PASSWORD
    ):
        cfg["auth"]["bo_maps.prefix"] = HG_MAPS_REPO_URL
        cfg["auth"]["bo_maps.username"] = HG_USERNAME
        cfg["auth"]["bo_maps.password"] = HG_PASSWORD
        updated = True

    if updated:
        with open(HG_CONFIG_PATH, "w") as f:
            logger.info("writing config file: '{}'", HG_CONFIG_PATH)
            cfg.write(f, space_around_delimiters=True)


async def main() -> None:
    hg_ensure_config()
    # await hg_sync_packages()
    # await hg_sync_maps()


if __name__ == "__main__":
    asyncio.run(main())
