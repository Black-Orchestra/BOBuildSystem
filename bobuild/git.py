import asyncio
import re
from functools import partial
from pathlib import Path
from typing import Literal

from bobuild.config import GitConfig
from bobuild.log import logger
from bobuild.run import read_stream_task
from bobuild.typing_bo import overload
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
    git_args = [
        *args,
    ]

    logger.info("running git command: '{}', cwd={}", git_args, cwd)

    proc = await asyncio.create_subprocess_exec(
        "git",
        *git_args,
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

    await asyncio.gather(
        read_stream_task(proc.stdout, partial(line_cb, all_out, "git stdout")),
        read_stream_task(proc.stderr, partial(line_cb, all_err, "git stderr")),
    )

    ec = await proc.wait()
    logger.info("git command exited with code: {}", ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"command exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def repo_exists(repo_path: Path) -> bool:
    if not repo_path.exists():
        return False

    # TODO: this is not reliable for example when the repo
    #  exists but it has invalid permissions/owner. There's
    #  no way to detect this from the exit code.
    ec, _, _ = await run_cmd(
        "status",
        cwd=repo_path,
    )
    return ec == 0


async def clone_repo(repo_url: str, repo_path: Path):
    await run_cmd(
        "clone",
        repo_url,
        str(repo_path),
        raise_on_error=True,
    )


async def pull_repo(repo_path: Path):
    await run_cmd(
        "pull",
        cwd=repo_path,
        raise_on_error=True,
    )


async def fetch_repo(repo_path: Path) -> None:
    await run_cmd(
        "fetch",
        "--verbose",
        cwd=repo_path,
        raise_on_error=True,
    )


async def sync_repo(
        repo_path: Path,
        branch: str,
):
    """WARNING: does a hard reset and clean!"""
    await fetch_repo(repo_path)
    await run_cmd(
        "reset",
        "--hard",
        f"origin/{branch}",
        cwd=repo_path,
        raise_on_error=True
    )
    await run_cmd(
        "clean",
        "-x",
        "-d",
        "-f",
        cwd=repo_path,
        raise_on_error=True,
    )


async def repo_has_update(repo_path: Path, branch: str) -> bool:
    _, out, err = await run_cmd(
        "fetch", "--dry-run", "--verbose",
        cwd=repo_path,
        raise_on_error=True,
        return_output=True,
    )

    out += err

    pat = re.compile(fr".*\[up to date]\s+{branch}.*",
                     flags=re.DOTALL)
    if pat.match(out):
        return False

    return True


async def get_local_hash(repo_path: Path) -> str:
    return (
        await run_cmd(
            "rev-parse",
            "--verify",
            "HEAD",
            cwd=repo_path,
            return_output=True,
            raise_on_error=True,
        )
    )[1].strip()


async def hash_diff(repo_path: Path, repo_url: str) -> tuple[str, str]:
    """Return commit tuple (current local hash, latest remote hash)."""
    local_hash = await get_local_hash(repo_path)
    remote_refs = (
        await run_cmd(
            "ls-remote",
            repo_url,
            "HEAD",
            raise_on_error=True,
            return_output=True,
        )
    )[1]
    remote_hash = remote_refs.split()[0]
    return local_hash, remote_hash.strip()


async def main() -> None:
    config = GitConfig()

    exists = await repo_exists(config.repo_path)
    print(f"{exists=}")

    has_update = await repo_has_update(config.repo_path, config.branch)
    print(f"{has_update=}")

    if exists and has_update:
        await fetch_repo(config.repo_path)
        await pull_repo(config.repo_path)


if __name__ == "__main__":
    asyncio_run(main())
