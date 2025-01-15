import argparse
import asyncio
from functools import partial
from pathlib import Path
from typing import Literal
from typing import overload

from bobuild.config import MercurialConfig
from bobuild.log import logger
from bobuild.multiconfig import MultiConfigParser
from bobuild.run import read_stream_task
from bobuild.utils import asyncio_run


@overload
async def run_cmd(
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[True] = ...,
) -> tuple[int, str, str]:
    ...


@overload
async def run_cmd(
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[False] = ...,
) -> tuple[int, None, None]:
    ...


async def run_cmd(
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: bool = False,
) -> tuple[int, None | str, None | str]:
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

    all_out: list[str] = []
    all_err: list[str] = []

    if not proc.stdout:
        raise RuntimeError(f"process has no stdout: {proc}")
    if not proc.stderr:
        raise RuntimeError(f"process has no stderr: {proc}")

    def line_cb(_lines: list[str], _name: str, _line: str):
        logger.info("{}: {}", _name, _line)
        if return_output:
            _lines.append(_line)

    await asyncio.gather(*(
        read_stream_task(proc.stdout, partial(line_cb, all_out, "hg stdout")),
        read_stream_task(proc.stderr, partial(line_cb, all_err, "hg stderr")),
    ))

    ec = await proc.wait()
    logger.info("hg command exited with code: {}", ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"command exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def repo_exists(path: Path) -> bool:
    p = str(path.resolve())
    ec = (await run_cmd("--cwd", p, "root"))[0]
    return ec == 0


async def clone_repo(url: str, path: Path):
    p = str(path.resolve())
    await run_cmd("clone", url, p, raise_on_error=True)


async def sync(repo_path: Path) -> None:
    await run_cmd("pull", cwd=repo_path, raise_on_error=True)
    await run_cmd("update", "--clean", cwd=repo_path, raise_on_error=True)


async def get_local_hash(repo_path: Path) -> str:
    return (await run_cmd(
        "id",
        "-i",
        cwd=repo_path,
        return_output=True,
        raise_on_error=True,
    ))[1].strip()


async def hash_diff(repo_path: Path, repo_url: str) -> tuple[str, str]:
    """Return commit tuple (current local hash, incoming hash)."""
    local_hash = await get_local_hash(repo_path)
    remote_hash = (
        await run_cmd(
            "id",
            "-r",
            "tip",
            repo_url,
            raise_on_error=True,
            return_output=True,
        ))[1]
    return local_hash, remote_hash.strip()


async def incoming(path: Path) -> bool:
    """Returns 0 if there are incoming changes, 1 otherwise."""
    ec = await run_cmd("incoming", cwd=path)
    return ec == 0


async def has_missing(path: Path) -> bool:
    await run_cmd(
        "status",
        cwd=path,
        raise_on_error=True,
        return_output=True,
    )

    # TODO: check for lines starting with !

    return False


def ensure_config(config: MercurialConfig):
    logger.info("ensuring hg config is up to date")

    if not config.hgrc_path.exists():
        config.hgrc_path.parent.mkdir(parents=True, exist_ok=True)
        config.hgrc_path.touch(exist_ok=True)

    updated = False

    cfg = MultiConfigParser()
    cfg.read(config.hgrc_path)

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
            or cfg["auth"]["bo_packages.prefix"] != config.pkg_repo_url
            or cfg["auth"]["bo_packages.username"] != config.username
            or cfg["auth"]["bo_packages.password"] != config.password
    ):
        cfg["auth"]["bo_packages.prefix"] = config.pkg_repo_url
        cfg["auth"]["bo_packages.username"] = config.username
        cfg["auth"]["bo_packages.password"] = config.password
        updated = True

    if ("bo_maps.prefix" not in cfg["auth"]
            or "bo_maps.username" not in cfg["auth"]
            or "bo_maps.password" not in cfg["auth"]
            or cfg["auth"]["bo_maps.prefix"] != config.maps_repo_url
            or cfg["auth"]["bo_maps.username"] != config.username
            or cfg["auth"]["bo_maps.password"] != config.password
    ):
        cfg["auth"]["bo_maps.prefix"] = config.maps_repo_url
        cfg["auth"]["bo_maps.username"] = config.username
        cfg["auth"]["bo_maps.password"] = config.password
        updated = True

    if updated:
        with config.hgrc_path.open("w") as f:
            logger.info("writing config file: '{}'", config.hgrc_path)
            cfg.write(f, space_around_delimiters=True)


def configure() -> None:
    cfg = MercurialConfig()
    ensure_config(cfg)


async def main() -> None:
    ap = argparse.ArgumentParser()

    action_choices = {
        "configure": configure,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    action_choices[args.action]()
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
