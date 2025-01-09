import asyncio
from pathlib import Path
from typing import Literal
from typing import overload


@overload
async def run_proces(
        program: str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[True] = ...,
) -> tuple[int, str, str]:
    ...


@overload
async def run_proces(
        program: str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: Literal[False] = ...,
) -> tuple[int, None, None]:
    ...


async def run_proces(
        program: str,
        *args: str,
        cwd: Path | None = None,
        raise_on_error: bool = False,
        return_output: bool = False,
) -> tuple[int, None | str, None | str]:
    pass


async def vneditor_make() -> None:
    ec, out, err = await run_proces(
        "vneditor",
        "make",
        "-useunpublished",
        "-stripsource",
        "-forcelogflush",
        raise_on_error=True,
        return_output=True,
    )


async def vneditor_brew(content: list[str]) -> None:
    ec, out, err = await run_proces(
        "vneditor",
        "brewcontent",
        *content,
        "-useunpublished",
        "-forcelogflush",
        raise_on_error=True,
        return_output=True,
    )


async def main() -> None:
    pass


if __name__ == "__main__":
    asyncio.run(main())
