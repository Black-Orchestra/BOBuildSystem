import argparse
import asyncio
import datetime
import ssl

import aiohttp
import certifi
import discord
import ujson

from bobuild.utils import utcnow
from bobuild.config import DiscordConfig
from bobuild.log import logger

_certs = certifi.where()
_ssl_ctx = ssl.create_default_context(cafile=_certs)


async def test_builds_webhook(cfg: DiscordConfig):
    await send_webhook(
        url=cfg.builds_webhook_url,
        embed_title="Build start test message!",
        embed_description="This is a test message!",
        embed_color=discord.Color.light_embed(),
        embed_timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
    )


async def test_builds_webhook_rate_limit(cfg: DiscordConfig):
    for x in range(50):
        await send_webhook(
            url=cfg.builds_webhook_url,
            embed_color=discord.Color.random(),
            embed_title=f"test_{x}",
            embed_description=f"test_{x}",
        )


async def send_webhook(
        url: str,
        content: str | None = None,
        embed_color: discord.Color | None = None,
        embed_title: str | None = None,
        embed_description: str | None = None,
        embed_timestamp: datetime.datetime | None = None,
        embed_footer: str | None = None,
        fields: list[tuple[str, str, bool]] | None = None,
) -> None:
    content = content or ""

    if embed_timestamp is None:
        embed_timestamp = utcnow()

    embed = discord.Embed(
        title=embed_title,
        description=embed_description,
        color=embed_color,
        timestamp=embed_timestamp,
    )
    embed.set_footer(text=embed_footer)
    if fields:
        for field in fields:
            embed.add_field(name=field[0], value=field[1], inline=field[2])

    async with aiohttp.TCPConnector(ssl=_ssl_ctx) as conn:
        async with aiohttp.ClientSession(
                json_serialize=ujson.dumps,
                connector=conn,
        ) as session:
            webhook: discord.Webhook = discord.Webhook.from_url(url, session=session)
            length = len(embed) + len(content)
            logger.info("sending webhook, length={}", length)
            await webhook.send(
                content=content,
                embed=embed,
            )


async def main():
    ap = argparse.ArgumentParser()
    cfg = DiscordConfig()

    action_choices = {
        "test_builds_webhook": test_builds_webhook,
        "test_builds_webhook_rate_limit": test_builds_webhook_rate_limit,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action](cfg)
    logger.info("exiting")


if __name__ == "__main__":
    asyncio.run(main())
