import asyncio
import re
from pathlib import Path

from bobuild.config import GitConfig
from bobuild.log import logger


async def run_cmd(
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: bool = False,
) -> tuple[int, None | str, None | str]:
    git_args = [
        *args,
    ]
    proc = await asyncio.create_subprocess_exec(
        "git",
        *git_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
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
            logger.info("git stdout: " + out)
            if return_output:
                all_out.append(out)
        err = (await proc.stderr.readline()
               ).decode("utf-8", errors="replace").rstrip()
        if err:
            logger.info("git stderr: " + err)
            if return_output:
                all_err.append(err)

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


async def repo_has_update(repo_path: Path, branch: str) -> bool:
    _, out, err = await run_cmd(
        "fetch", "--dry-run", "--verbose",
        cwd=repo_path,
        raise_on_error=True,
        return_output=True,
    )

    out += err  # type: ignore[operator]

    pat = re.compile(fr".*\[up to date]\s+{branch}.*",
                     flags=re.DOTALL)
    if pat.match(out):
        return False

    return True


async def main() -> None:
    config = GitConfig()

    exists = await repo_exists(config.repo_path)
    print(f"{exists=}")

    has_update = await repo_has_update(config.repo_path, config.branch)
    print(f"{has_update=}")

    if exists and has_update:
        await pull_repo(config.repo_path)


if __name__ == "__main__":
    asyncio.run(main())
