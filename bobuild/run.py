import asyncio
from pathlib import Path
from typing import Callable
from typing import Iterable
from typing import Literal
from typing import overload

from bobuild.log import logger


@overload
async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[True] = ...,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
) -> tuple[int, str, str]:
    ...


@overload
async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[False] = ...,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
) -> tuple[int, None, None]:
    ...


async def run_process(
        program: Path | str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: bool = False,
        redact: Callable[[Iterable[str]], list[str]] | None = None,
) -> tuple[int, None | str, None | str]:
    if redact is not None:
        logger.info("running program {}: {}, cwd={}", program, redact(args), cwd)
    else:
        logger.info("running program {}: {}, cwd={}", program, args, cwd)
    proc = await asyncio.create_subprocess_exec(
        str(program),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    all_out = []
    all_err = []

    if isinstance(program, Path):
        pn = program.name
    else:
        pn = program

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
            logger.info("{} stdout: {}", pn, out)
            if return_output:
                all_out.append(out)
        err = (await proc.stderr.readline()
               ).decode("utf-8", errors="replace").rstrip()
        if err:
            logger.info("{} stderr: {}", pn, err)
            if return_output:
                all_err.append(err)

    ec = await proc.wait()
    logger.info("program {} exited with code: {}", pn, ec)

    if raise_on_error and ec != 0:
        raise RuntimeError(f"program {program} exited with non-zero exit code: {ec}")

    if return_output:
        return ec, "\n".join(all_out), "\n".join(all_err)
    else:
        return ec, None, None


async def vneditor_make() -> None:
    ec, out, err = await run_process(
        "vneditor",
        "make",
        "-log",
        "-unattended",
        "-useunpublished",
        "-stripsource",
        "-forcelogflush",
        raise_on_error=True,
        return_output=True,
    )
    print(out)
    print(err)


# TODO: all packages with .upk extension, .u and .roe files without!
async def vneditor_brew(content: list[str]) -> None:
    ec, out, err = await run_process(
        "vneditor",
        "brewcontent",
        *content,
        "-log",
        "-unattended",
        "-useunpublished",
        "-forcelogflush",
        raise_on_error=True,
        return_output=True,
    )


async def patch_shader_cache(
        script_package_path: Path,
        shader_cache_path: str,
        object_to_patch_path: str,
):
    repo_dir = Path(__file__).parent.parent
    patcher = Path(repo_dir).resolve() / "UE3ShaderCachePatcherCLI.exe"
    if not patcher.exists():
        raise RuntimeError(f"UE3ShaderCachePatcherCLI.exe does not exist in '{patcher}'")

    await run_process(
        str(patcher.name),
        "-f", str(script_package_path.resolve()),
        "-s", shader_cache_path,
        "-p", object_to_patch_path,
        cwd=patcher.parent,
        raise_on_error=True,
    )


async def main() -> None:
    await vneditor_make()


if __name__ == "__main__":
    asyncio.run(main())
