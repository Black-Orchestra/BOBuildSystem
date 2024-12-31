import asyncio
from pprint import pprint

import githubkit

from bobuild.utils import get_var

GITHUB_TOKEN = get_var("BO_GITHUB_TOKEN")


async def main() -> None:
    gh = githubkit.GitHub(GITHUB_TOKEN)

    resp = await gh.rest.repos.async_get(owner="adriaNsteam", repo="WW2")
    pprint(resp.json())

    resp = await gh.rest.repos.async_get_commit("adriaNsteam", "WW2", "heads/main")
    pprint(resp.json())


if __name__ == "__main__":
    asyncio.run(main())
