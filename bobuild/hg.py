import asyncio
from pathlib import Path

from bobuild.log import logger
from bobuild.multiconfig import MultiConfigParser
from bobuild.utils import get_var

HG_CONFIG_PATH = (Path.home() / ".hgrc").resolve()

# NOTE: allow missing values here on purpose for easy development.
# None of these should be missing in production deployment, however.
HG_USERNAME = get_var("BO_HG_USERNAME", None)
HG_PASSWORD = get_var("BO_HG_PASSWORD", None)
HG_PKG_REPO_PATH = Path(get_var("BO_HG_PKG_REPO_PATH", "./.DUMMY_PKGS/")).resolve()
HG_MAPS_REPO_PATH = Path(get_var("BO_HG_MAPS_REPO_PATH", "./.DUMMY_MAPS/")).resolve()
HG_PKG_REPO_URL = get_var("BO_HG_PKG_REPO_URL", None)
HG_MAPS_REPO_URL = get_var("BO_HG_MAPS_REPO_URL", None)


async def run_cmd(
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
) -> int:
    hg_args = [
        *args,
        "--noninteractive",
        "--verbose",
        "--pager", "never",
    ]

    logger.info("running hg command: '{}', cwd={}", hg_args, cwd)
    proc = await asyncio.create_subprocess_exec(
        "hg",
        *hg_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    if not proc.stdout:
        raise RuntimeError(f"process has no stdout: {proc}")
    if not proc.stderr:
        raise RuntimeError(f"process has no stderr: {proc}")

    while True:
        if proc.stdout.at_eof() and proc.stderr.at_eof():
            break

        out = (await proc.stdout.readline()
               ).decode("utf-8", errors="replace").strip()
        if out:
            logger.info(out)
        err = (await proc.stderr.readline()
               ).decode("utf-8", errors="replace").strip()
        if err:
            logger.info(err)

    ec = await proc.wait()
    logger.info("hg command exited with code: {}", ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"command exited with non-zero exit code: {ec}")

    return ec


async def repo_exists(path: Path) -> bool:
    p = str(path.resolve())
    ec = await run_cmd("--cwd", p, "root")
    return ec == 0


async def clone_repo(url: str, path: Path):
    p = str(path.resolve())
    await run_cmd("clone", url, p, raise_on_error=True)


async def sync_packages() -> None:
    await run_cmd("pull", cwd=HG_PKG_REPO_PATH, raise_on_error=True)
    await run_cmd("update", "--clean", cwd=HG_PKG_REPO_PATH, raise_on_error=True)


async def sync_maps() -> None:
    await run_cmd("pull", cwd=HG_MAPS_REPO_PATH, raise_on_error=True)
    await run_cmd("update", "--clean", cwd=HG_MAPS_REPO_PATH, raise_on_error=True)


async def incoming(path: Path) -> bool:
    """Returns 0 if there are incoming changes, 1 otherwise."""
    ec = await run_cmd("incoming", cwd=path)
    return ec == 0


def ensure_config():
    logger.info("ensuring hg config is up to date")

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
    ensure_config()

    exists = await repo_exists(HG_PKG_REPO_PATH)
    logger.info("hg repo exists: {}", exists)

    repo_inc = await incoming(HG_PKG_REPO_PATH)
    logger.info("hg repo has incoming: {}", repo_inc)

    # await hg_sync_packages()
    # await hg_sync_maps()


if __name__ == "__main__":
    asyncio.run(main())
