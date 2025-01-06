import os
import platform
from pathlib import Path
from typing import TypeVar
from typing import cast

from bobuild.log import logger

T = TypeVar("T")

_default = object()


# TODO: rename this entire module?

# TODO: allow lazy loading of env vars here (and other modules?)
#      - Return a 'var' object that checks if the env var exists on
#        creation, if it does not exist, check again on the first use
#        of the var?
def get_var(name: str, default: T | object = _default) -> str | T:
    if default is _default:
        return os.environ[name]

    if name not in os.environ:
        logger.warning("{} not set in environment", name)
    return os.environ.get(name, cast(T, default))


def is_dev_env() -> bool:
    return get_var("BO_DEV_ENV", "0") == "1"


if platform.system() == "Windows":
    _default_rs2_game_dir = r"C:\rs2vietnam\\"
    _default_rs2_server_dir = r"C:\rs2server\\"
else:
    # TODO: set good defaults for Linux too!
    _default_rs2_game_dir = "TODO"
    _default_rs2_server_dir = "TODO"

# Use the same path for both the game and SDK.
RS2_GAME_INSTALL_DIR = Path(get_var("BO_RS2_GAME_INSTALL_DIR",
                                    _default_rs2_game_dir))
RS2_SERVER_INSTALL_DIR = Path(get_var("BO_RS2_SERVER_INSTALL_DIR",
                                      _default_rs2_server_dir))
