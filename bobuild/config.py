import platform
from dataclasses import dataclass
from pathlib import Path

from boltons.cacheutils import cachedproperty

from bobuild.utils import get_var

if platform.system() == "Windows":
    _default_steamcmd_install_dir = r"C:\steamcmd\\"
    _default_repo_path = Path().home() / "Documents/My Games/Rising Storm 2/ROGame/Src/WW2"
    _default_rs2_game_dir = r"C:\rs2vietnam\\"
    _default_rs2_server_dir = r"C:\rs2server\\"
    _steamcmd_exe_name = "steamcmd.exe"
else:
    # TODO: set good defaults for Linux too?
    _default_steamcmd_install_dir = "TODO"
    _default_repo_path = "TODO"  # type: ignore[assignment]
    _default_rs2_game_dir = "TODO"
    _default_rs2_server_dir = "TODO"
    _steamcmd_exe_name = "steamcmd.sh"
    raise NotImplementedError


@dataclass(slots=True, frozen=True)
class MercurialConfig:
    @cachedproperty
    def username(self) -> str:
        return get_var("BO_HG_USERNAME")

    @cachedproperty
    def password(self) -> str:
        return get_var("BO_HG_PASSWORD")

    @cachedproperty
    def pkg_repo_path(self) -> Path:
        return Path(get_var("BO_HG_PKG_REPO_PATH")).resolve()

    @cachedproperty
    def maps_repo_path(self) -> Path:
        return Path(get_var("BO_HG_MAPS_REPO_PATH")).resolve()

    @cachedproperty
    def pkg_repo_url(self) -> str:
        return get_var("BO_HG_PKG_REPO_URL")

    @cachedproperty
    def maps_repo_url(self) -> str:
        return get_var("BO_HG_MAPS_REPO_URL")

    @cachedproperty
    def hgrc_path(self) -> Path:
        return (Path.home() / ".hgrc").resolve()


@dataclass(frozen=True)
class GitConfig:

    @cachedproperty
    def token(self) -> str:
        return get_var("BO_GITHUB_TOKEN")

    @cachedproperty
    def repo_url(self) -> str:
        return f"https://oauth2:{self.token}@github.com/adriaNsteam/WW2.git"

    @cachedproperty
    def repo_path(self) -> Path:
        return Path(get_var("BO_GITHUB_REPO_PATH",
                            _default_repo_path)).resolve()

    @cachedproperty
    def branch(self) -> str:
        return get_var("BO_GITHUB_BRANCH", "main")


@dataclass(frozen=True)
class SteamCmdConfig:
    download_url: str = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

    @cachedproperty
    def install_dir(self) -> Path:
        return Path(get_var("BO_STEAMCMD_INSTALL_DIR"),
                    _default_steamcmd_install_dir).resolve()

    @cachedproperty
    def exe_path(self) -> Path:
        return self.install_dir / _steamcmd_exe_name

    @cachedproperty
    def username(self) -> str:
        return get_var("BO_STEAMCMD_USERNAME")

    @cachedproperty
    def password(self) -> str:
        return get_var("BO_STEAMCMD_PASSWORD")


@dataclass(frozen=True)
class RS2Config:
    @cachedproperty
    def game_install_dir(self) -> Path:
        return Path(get_var("BO_RS2_GAME_INSTALL_DIR",
                            _default_rs2_game_dir)).resolve()

    @cachedproperty
    def server_install_dir(self) -> Path:
        return Path(get_var("BO_RS2_SERVER_INSTALL_DIR",
                            _default_rs2_server_dir)).resolve()
