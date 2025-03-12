import argparse
import asyncio
import hashlib
import platform
import re
import signal
from dataclasses import dataclass
from enum import IntEnum
from enum import StrEnum
from typing import AsyncIterator
from typing import cast
from urllib.parse import urlparse
from urllib.parse import urlunparse

import bs4
import httpx
from boltons.cacheutils import cachedproperty

from bobuild.config import RS2Config
from bobuild.log import logger
from bobuild.utils import asyncio_run


class ChatChannel(IntEnum):
    AXIS = 0
    ALLIES = 1
    ALL = -1


class Team(StrEnum):
    AXIS = "Axis"
    ALLIES = "Allies"
    UNKNOWN = "Unknown"
    ALL = "All"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    sender: str
    message: str
    channel: ChatChannel
    team: Team


def parse_chat_channel(x: str | int) -> ChatChannel | None:
    if x is None:
        return None

    if isinstance(x, int):
        return ChatChannel(x)
    else:
        # noinspection PyTypeChecker
        return ChatChannel[str(x).upper()]


HEX_COLOR_BLUE_TEAM = "#50A0F0"
HEX_COLOR_RED_TEAM = "#E54927"
HEX_COLOR_UNKNOWN_TEAM = "transparent"
HEX_COLOR_ALL_TEAM = ""
HEX_COLOR_TO_TEAM = {
    HEX_COLOR_BLUE_TEAM: Team.ALLIES,
    HEX_COLOR_RED_TEAM: Team.AXIS,
    HEX_COLOR_UNKNOWN_TEAM: Team.UNKNOWN,
    HEX_COLOR_ALL_TEAM: Team.ALL,
}


def parse_message(div: bs4.Tag) -> ChatMessage:
    # TODO: proper error handling here, which should also fix typing errors.
    teamcolor = str(div.find(
        "span", attrs={"class": "teamcolor"}).get("style"))  # type: ignore[union-attr]
    match = re.match(r"background: (.*);", teamcolor)
    team = HEX_COLOR_TO_TEAM[match.group(1)]  # type: ignore[union-attr]
    channel = ChatChannel.ALL
    tnotice = div.find("span", attrs={"class": "teamnotice"})
    if tnotice:
        if tnotice.text == "(Team)":
            if team == Team.ALLIES:
                channel = ChatChannel.ALLIES
            else:
                channel = ChatChannel.AXIS
    name = div.find("span", attrs={"class": "username"}).text  # type: ignore[union-attr]
    msg = div.find("span", attrs={"class": "message"}).text  # type: ignore[union-attr]
    # noinspection PyTypeChecker
    return ChatMessage(
        sender=name,
        message=msg,
        team=team,
        channel=channel,
    )


def parse_messages(html_text: str) -> list[ChatMessage]:
    html = bs4.BeautifulSoup(html_text, "html.parser")
    chat_msg_divs = html.find_all("div", {"class": "chatmessage"})
    msgs = []
    for div in chat_msg_divs:
        msgs.append(parse_message(div))
    return msgs


def parse_token(text: str) -> str:
    html = bs4.BeautifulSoup(text, "html.parser")
    token = html.find("input", attrs={"name": "token"})
    if not isinstance(token, bs4.Tag):
        raise ValueError(f"unexpected type: {type(token)}")
    if token is None:
        raise ValueError("cannot parse token")
    token_value = token.get("value")
    if token_value is None:
        raise ValueError("cannot get token value")
    return cast(str, token_value)


def encode_password(username: str, password: str) -> str:
    return hashlib.sha1(
        bytearray(password, "utf-8")
        + bytearray(username, "utf-8")
    ).hexdigest()


def check_error(html_text: str):
    html = bs4.BeautifulSoup(html_text, "html.parser")
    msg_error = html.find("div", attrs={"class": "message error"})
    if msg_error:
        value = msg_error.get_text().strip()
        if value:
            raise ValueError(f"WebAdmin returned error message: {value}")


class WebAdmin:
    """Rising Storm 2 Vietnam WebAdmin.

    TODO: add support using as context manager?
    TODO: do we need to support non-SHA1 login?
    """

    def __init__(
            self,
            username: str,
            password: str,
            url: str,
            msg_queue_maxsize: int = 250,
            get_messages_interval: float = 5.0,
    ):
        self._username = username
        self._password_hash = encode_password(username, password)
        self._url = url
        self._client = httpx.AsyncClient(follow_redirects=True)
        self._token = ""
        self._sessionid = ""
        self._msg_queue_maxsize = msg_queue_maxsize
        self._msg_queue: asyncio.Queue[ChatMessage] = asyncio.Queue(maxsize=msg_queue_maxsize)
        self._msg_queue_task: asyncio.Task | None = None
        self._get_messages_interval = get_messages_interval

        if platform.system() != "Windows":
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGINT, self._cancel_tasks)
            loop.add_signal_handler(signal.SIGTERM, self._cancel_tasks)
            loop.add_signal_handler(signal.SIGHUP, self._cancel_tasks)  # type: ignore[attr-defined]

    def _cancel_tasks(self):
        if self._msg_queue_task:
            self._msg_queue_task.cancel()

    @cachedproperty
    def url_current(self) -> str:
        new = urlparse(self._url)._replace(path="/ServerAdmin/current")
        # noinspection PyTypeChecker
        return urlunparse(new)

    @cachedproperty
    def url_chat(self) -> str:
        new = urlparse(self._url)._replace(path="/ServerAdmin/current/chat")
        # noinspection PyTypeChecker
        return urlunparse(new)

    @cachedproperty
    def url_chat_data(self) -> str:
        new = urlparse(self._url)._replace(path="/ServerAdmin/current/chat/data")
        # noinspection PyTypeChecker
        return urlunparse(new)

    @cachedproperty
    def url_logout(self) -> str:
        new = urlparse(self._url)._replace(path="/ServerAdmin/logout")
        # noinspection PyTypeChecker
        return urlunparse(new)

    async def close(self):
        await self._client.aclose()

    async def login(self):
        resp = await self._client.get(url=self.url_current)
        resp.raise_for_status()
        check_error(resp.text)
        self._client.cookies = resp.cookies
        self._token = parse_token(resp.text)
        resp = await self._client.post(
            url=self.url_current,
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "connection": "keep-alive",
            },
            data={
                "token": self._token,
                "password_hash": f"$sha1${self._password_hash}",
                "username": self._username,
                "remember": 315569260,  # 10 years.
                "password": "",
            },
        )
        resp.raise_for_status()
        check_error(resp.text)
        self._client.cookies = resp.cookies

        self._msg_queue = asyncio.Queue(maxsize=self._msg_queue_maxsize)
        self._msg_queue_task = asyncio.create_task(self.msg_queue_task())

    async def _shutdown_msg_queue(self):
        if self._msg_queue_task is not None:
            self._msg_queue_task.cancel()
            await self._msg_queue_task
        self._msg_queue.shutdown(immediate=True)

    async def logout(self):
        await self._shutdown_msg_queue()
        resp = await self._client.post(url=self.url_logout)
        resp.raise_for_status()
        check_error(resp.text)

    async def msg_queue_task(self):
        running = True
        while running:
            try:
                resp = await self._client.post(
                    url=self.url_chat_data,
                    headers={
                        "x-requested-with": "XMLHttpRequest",
                    },
                    data={
                        "ajax": 1,
                    }
                )
                resp.raise_for_status()
                check_error(resp.text)
                messages = parse_messages(resp.text)
                for msg in messages:
                    if self._msg_queue.full():
                        await self._msg_queue.get()
                    await self._msg_queue.put(msg)
            except asyncio.CancelledError:
                running = False
                break
            except Exception as e:
                logger.exception("msg_queue_task error: {}", type(e).__name__)
            finally:
                if running:
                    await asyncio.sleep(self._get_messages_interval)

    async def messages(self) -> AsyncIterator[ChatMessage]:
        try:
            while msg := await self._msg_queue.get():
                yield msg
        except asyncio.queues.QueueShutDown:
            return

    async def send_message(self, msg: str, channel: ChatChannel = ChatChannel.ALL):
        resp = await self._client.post(
            url=self.url_chat_data,
            headers={
                "x-requested-with": "XMLHttpRequest",
            },
            data={
                "ajax": 1,
                "message": msg,
                "teamsay": channel.value,
            }
        )
        resp.raise_for_status()
        check_error(resp.text)


async def print_messages_task(wa: WebAdmin):
    async for msg in wa.messages():
        print(msg)


async def send_webadmin_chat_message(
        *_,
        rs2_config: RS2Config | None = None,
        chat_message: str | None = None,
        chat_channel: ChatChannel | None = None,
        webadmin_url: str | None = None,
        **__,
):
    if (rs2_config is None
            or (chat_message is None)
            or (chat_channel is None)
            or (webadmin_url is None)
    ):
        raise RuntimeError("rs2_config, chat_message, chat_channel and webadmin_url are required")

    wa = WebAdmin(
        username=rs2_config.server_admin_username,
        password=rs2_config.server_admin_password,
        url=webadmin_url,
    )
    await wa.login()
    await wa.send_message(chat_message, chat_channel)

    # TODO: just for testing.
    print_msgs_task = asyncio.create_task(print_messages_task(wa))
    await asyncio.sleep(99999999999999999)

    await wa.logout()
    await wa.close()

    await print_msgs_task


async def main() -> None:
    ap = argparse.ArgumentParser()
    cfg = RS2Config()

    action_choices = {
        "send_message": send_webadmin_chat_message,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )
    ap.add_argument(
        "--chat-message",
        type=str,
        required=False,
        help="chat message to send for send_message action",
    )
    ap.add_argument(
        "--chat-channel",
        type=str,
        required=False,
        choices=[str(c.name) for c in ChatChannel],
        help="chat channel to send message to for send_message action, default=%(default)s)",
        default=ChatChannel.ALL.name,
    )
    ap.add_argument(
        "--webadmin-url",
        type=str,
        required=False,
        help="BO server WebAdmin URL",
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action](
        rs2_config=cfg,
        chat_message=args.chat_message,
        chat_channel=parse_chat_channel(args.chat_channel),
        webadmin_url=args.webadmin_url,
    )
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
