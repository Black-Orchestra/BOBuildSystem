import platform
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from boltons.cacheutils import cachedproperty

from bobuild.utils import get_var

_repo_dir = Path(__file__).parent.parent.resolve()

if platform.system() == "Windows":
    # NOTE: this is mirrored in install_steamcmd.ps1.
    _default_steamcmd_install_dir = str(_repo_dir / "bin/steamcmd/")
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
    """
    TODO: SteamCMD installation logic is duplicated in
      install_steamcmd.ps1. Do we need both, Python and PowerShell
      versions? Maybe get rid of the PS version and handle everything
      with the Python scripts?
    """

    download_url: str = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

    @cachedproperty
    def install_dir(self) -> Path:
        return Path(get_var("BO_STEAMCMD_INSTALL_DIR",
                            _default_steamcmd_install_dir)).resolve()

    @cachedproperty
    def exe_path(self) -> Path:
        return self.install_dir / _steamcmd_exe_name

    @cachedproperty
    def username(self) -> str:
        return get_var("BO_STEAMCMD_USERNAME")

    @cachedproperty
    def password(self) -> str:
        return get_var("BO_STEAMCMD_PASSWORD")

    @cachedproperty
    def steamguard_passkey(self) -> str:
        return get_var("BO_STEAMGUARD_PASSKEY", "")

    @cachedproperty
    def steamguard_cli_path(self) -> Path:
        # NOTE: this path is mirrored in install_steamguardcli.ps1.
        return Path(_repo_dir / "bin/steamguard.exe")


def map_ids_factory() -> dict[str, int]:
    return {
        "DRTE-Bardia": -1,
        "DRTE-ElAlamein": -1,
        "DRTE-HalfayaPass": -1,
        "DRTE-Leros": -1,
        "DRTE-LongstopHill": -1,
        "DRTE-Mareth": -1,
        "DRTE-Medjez": -1,
        "DRTE-Tobruk": -1,
        "RRTE-Apartments": -1,
        "RRTE-Barashka": -1,
        "RRTE-Barracks": -1,
        "RRTE-Beach_Invasion_Sim": -1,
        "RRTE-Betio": -1,
        "RRTE-BiblioHill": -1,
        "RRTE-Brecourt": -1,
        "RRTE-CommissarsHouse": -1,
        "RRTE-Demyansk": -1,
        "RRTE-FallenFighters": -1,
        "RRTE-Foy": -1,
        "RRTE-GrainElevator": -1,
        "RRTE-GuadalCanal": -1,
        "RRTE-HacksawRidge": -1,
        "RRTE-Halbe_BreakoutBlockOut": -1,
        "RRTE-Hanto": -1,
        "RRTE-HellsCorners": -1,
        "RRTE-HirosakiCastle": -1,
        "RRTE-Horson": -1,
        "RRTE-IwoJima": -1,
        "RRTE-Kobura": -1,
        "RRTE-Kwajalein": -1,
        "RRTE-MaggotHill": -1,
        "RRTE-MamayevKurgan": -1,
        "RRTE-MarcoPolo": -1,
        "RRTE-Mutanchiang": -1,
        "RRTE-MyshkovaRiver": -1,
        "RRTE-Oosterbeek": -1,
        "RRTE-PavlovsHouse": -1,
        "RRTE-Peleliu": -1,
        "RRTE-PortBrest": -1,
        "RRTE-RamreeIsland": -1,
        "RRTE-RedOctoberFactory": -1,
        "RRTE-Reichstag": -1,
        "RRTE-Saipan": -1,
        "RRTE-Shumshu": -1,
        "RRTE-ShuriCastle": -1,
        "RRTE-Spartanovka": -1,
        "RRTE-Station": -1,
        "RRTE-Suribachi": -1,
        "RRTE-Univermag": -1,
    }


@dataclass(frozen=True)
class RS2Config:
    bo_dev_beta_workshop_id: int = 3404127489
    bo_dev_beta_map_ids: dict[str, int] = field(default_factory=map_ids_factory)

    @cachedproperty
    def game_install_dir(self) -> Path:
        return Path(get_var("BO_RS2_GAME_INSTALL_DIR",
                            _default_rs2_game_dir)).resolve()

    @cachedproperty
    def server_install_dir(self) -> Path:
        return Path(get_var("BO_RS2_SERVER_INSTALL_DIR",
                            _default_rs2_server_dir)).resolve()

    @cachedproperty
    def published_dir(self) -> Path:
        return Path.home() / "Documents/My Games/Rising Storm 2/ROGame/Published/"

    @cachedproperty
    def unpublished_dir(self) -> Path:
        return Path.home() / "Documents/My Games/Rising Storm 2/ROGame/Unpublished/"
