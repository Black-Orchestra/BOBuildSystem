import argparse
import datetime
import os
from concurrent.futures import Future
from concurrent.futures.thread import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from typing import Generator

import orjson
import vdf
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont

from bobuild.config import RS2Config
from bobuild.config import SteamCmdConfig
from bobuild.log import logger
from bobuild.steamcmd import get_steamguard_code
from bobuild.steamcmd import workshop_build_item_many
from bobuild.utils import asyncio_run
from bobuild.utils import file_digest
from bobuild.utils import file_hexdigest

_file_dir = Path(__file__).parent.resolve()
_repo_dir = _file_dir.parent
_draw_y = 880
_glow_x = 4
_glow_y = 4

# BO red is cc1417.
_bo_red = (204, 20, 23)


@dataclass(slots=True, frozen=True)
class WorkshopManifest:
    workshop_item_id: int
    git_hash: str
    git_tag: str
    hg_packages_hash: str
    hg_packages_tag: str
    hg_maps_hash: str
    hg_maps_tag: str
    build_id: str
    build_time_utc: datetime.datetime
    file_to_md5: dict[str, str]


def iter_maps(
        base_dir: Path,
        prefixes: list[str] | None = None,
) -> Generator[Path]:
    if not prefixes:
        prefixes = ["RRTE", "DRTE"]

    for roe in base_dir.rglob("*.roe"):
        if (any(roe.name.startswith(p) for p in prefixes)
                and roe.stat().st_size > 100_000):
            yield roe


def find_map_names(base_dir: Path) -> set[str]:
    return {str(file.stem) for file in iter_maps(base_dir)}


def linear_convert(
        value: float,
        old_min: float,
        old_max: float,
        new_min: float,
        new_max: float,
) -> float:
    return ((value - old_min) / (old_max - old_min)) * (new_max - new_min) + new_min


def draw_map_preview_file(
        map_name: str,
        template_file: Path,
        output_file: Path,
        font_file: Path = _repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color: tuple[int, int, int] = _bo_red,
):
    logger.info(
        "drawing map preview, map_name={}, template_file={}, output_file={}"
        ", font_file={}, font_color={}",
        map_name, template_file, output_file, font_file, font_color,
    )

    img = Image.open(template_file)
    iw, ih = img.size

    # Font size 90 is good for max 22 characters.
    # For size 59 we can fill up to 36 characters.
    # NOTE: this is just a rough estimate since we are not using a monospace font!
    font_size = 90
    length = len(map_name)
    if length > 36:
        logger.warning("map name longer than 36 characters: {}", length)
    if length > 22:
        # Swap old_min and old_max for "linear inversion".
        font_size = int(linear_convert(length, 36, 22, 59, 90))
    font = ImageFont.truetype(str(font_file.resolve()), font_size)

    draw = ImageDraw.Draw(img)
    glow_img = Image.new("RGBA", (iw, ih), color=(0, 0, 0))
    draw_glow = ImageDraw.Draw(glow_img)

    _, _, w, h = draw.textbbox((0, _draw_y), map_name, font=font)
    if w > iw:
        delta = (w - iw) / iw
        font_size = int((1 - delta) * font_size)
        logger.info("map name exceeds image width, setting new font size: {}",
                    font_size)
        font = ImageFont.truetype(str(font_file.resolve()), font_size)
        _, _, w, h = draw.textbbox((0, _draw_y), map_name, font=font)

    text_x = (iw - w) / 2
    text_y = ((ih - h) / 2) + _draw_y

    # Background glow.
    draw_glow.text(
        (text_x + _glow_x, text_y + _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
    )
    draw_glow.text(
        (text_x - _glow_x, text_y - _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
    )
    draw_glow.text(
        (text_x + _glow_x, text_y - _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
    )
    draw_glow.text(
        (text_x - _glow_x, text_y + _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
    )
    glow_img = glow_img.filter(ImageFilter.BoxBlur(7))

    mask = Image.new("RGBA", (iw, ih), color=(0, 0, 0, 0))
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rectangle((0, _draw_y, iw, ih), fill=(0, 0, 0, 255))
    img.paste(glow_img, mask=mask)

    # Main text.
    draw.text(
        (text_x, text_y),
        text=map_name,
        font=font,
        fill=font_color,
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_file)


async def test(
        *_,
        maps_dir: Path | None = None,
        **__,
) -> None:
    if maps_dir is None:
        raise RuntimeError(
            f"invalid maps_dir: {maps_dir}, required for action 'test'")

    draw_map_preview_file(
        map_name="DRTE-ElAlamein@@@@@@@@@@@@@@@@@@@@@@",
        template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
        output_file=_repo_dir / "workshop/generated/BOBetaMapImgTest.png",
        font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color=_bo_red,
    )

    if maps_dir.exists():
        map_names = find_map_names(maps_dir)
        with ThreadPoolExecutor() as executor:
            for map_name in map_names:
                executor.submit(
                    draw_map_preview_file,
                    map_name=map_name,
                    template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
                    output_file=_repo_dir / f"workshop/generated/BOBetaMapImg_{map_name}.png",
                    font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
                    font_color=_bo_red,
                )


async def list_maps(
        *_,
        maps_dir: Path | None = None,
        **__,
) -> None:
    if maps_dir is None:
        raise RuntimeError(
            f"invalid maps_dir: {maps_dir}, required for action 'list_maps'")

    if maps_dir.exists():
        map_names = sorted(find_map_names(maps_dir))
        for m in map_names:
            print(m)


def write_sws_config(
        out_file: Path,
        template_file: Path,
        content_folder: Path,
        preview_file: Path,
        git_hash: str = "null",
        hg_pkg_hash: str = "null",
        hg_maps_hash: str = "null",
        changenote: str = "",
        published_file_id: int | None = None,
        build_id: str | None = None,
):
    build_id = build_id or "null"

    template = vdf.loads(template_file.read_text())
    if published_file_id is not None:
        template["workshopitem"]["publishedfileid"] = published_file_id
    template["workshopitem"]["contentfolder"] = str(content_folder.resolve())
    template["workshopitem"]["previewfile"] = str(preview_file)
    desc = template["workshopitem"]["description"].format(
        _git_hash=git_hash,
        _hg_pkg_hash=hg_pkg_hash,
        _hg_maps_hash=hg_maps_hash,
        _build_id=build_id
    )
    template["workshopitem"]["changenote"] = changenote
    template["workshopitem"]["description"] = desc

    with out_file.open("w") as f:
        logger.info("writing '{}'", out_file)
        vdf.dump(template, f, pretty=True, escaped=False)


def write_map_sws_config(
        out_file: Path,
        template_file: Path,
        map_name: str,
        content_folder: Path,
        preview_file: Path,
        publishedfileid: int,
        git_hash: str = "null",
        hg_pkg_hash: str = "null",
        hg_maps_hash: str = "null",
        changenote: str = "",
        build_id: str | None = None,
):
    build_id = build_id or "null"

    template = vdf.loads(template_file.read_text())
    template["workshopitem"]["publishedfileid"] = publishedfileid
    template["workshopitem"]["contentfolder"] = str(content_folder.resolve())
    template["workshopitem"]["previewfile"] = str(preview_file)
    title = template["workshopitem"]["title"].format(_mapname=map_name)
    template["workshopitem"]["title"] = title
    desc = template["workshopitem"]["description"].format(
        _mapname=map_name,
        _git_hash=git_hash,
        _hg_pkg_hash=hg_pkg_hash,
        _hg_maps_hash=hg_maps_hash,
        _build_id=build_id,
    )
    template["workshopitem"]["changenote"] = changenote
    template["workshopitem"]["description"] = desc

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w") as f:
        logger.info("writing '{}'", out_file)
        vdf.dump(template, f, pretty=True, escaped=False)


def do_map_first_time_config(
        map_name: str,
) -> Path:
    p = _repo_dir / "workshop/generated/sws_map_staging/" / map_name
    p.mkdir(parents=True, exist_ok=True)

    preview_file = p / f"BOBetaMapImg_{map_name}.png"
    draw_map_preview_file(
        map_name=map_name,
        template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
        output_file=preview_file,
        font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color=_bo_red,
    )

    map_vdf_file = p / f"{map_name}.vdf"
    content_folder = p / "content"

    changenote = r"""Initial upload of dummy files.
Git commit: null.
Mercurial packages commit: null.
Mercurial maps commit: null.
"""

    write_map_sws_config(
        out_file=map_vdf_file,
        template_file=_repo_dir / "workshop/BOBetaMapTemplate.vdf",
        map_name=map_name,
        publishedfileid=0,  # Create new item.
        content_folder=content_folder,
        preview_file=preview_file,
        changenote=changenote,
    ),

    content_folder.mkdir(parents=True, exist_ok=True)
    dummy_file = content_folder / "dummy.txt"
    logger.info("writing '{}'", dummy_file)
    dummy_file.write_text(f"This is a dummy file for {map_name}!")

    return map_vdf_file


async def first_time_upload_all_maps(
        *_,
        maps_dir: Path | None = None,
        **__,
) -> None:
    """WARNING: this will create new workshop items for all
    BO dev maps and list their workshop IDs. The SWS items are
    created with only a dummy text file in them.

    Run this as a first-time setup action to create the SWS items
    for later usage in automation.
    """
    if maps_dir is None:
        raise RuntimeError(
            f"invalid maps_dir: {maps_dir}, "
            "required for action 'first_time_upload_all_maps'")

    cfg = SteamCmdConfig()
    rs2_cfg = RS2Config()

    logger.info("first-time uploading all maps")

    map_names = sorted(find_map_names(maps_dir))
    to_skip: set[str] = set()
    for map_name in map_names:
        if (map_id := rs2_cfg.bo_dev_beta_map_ids.get(map_name, -1)) != -1:
            logger.warning(
                "skipping map '{}' with existing SWS ID: {}",
                map_name, map_id)
            to_skip.add(map_name)
    for ts in to_skip:
        map_names.remove(ts)

    map_cfg_paths: list[Path] = []
    with ThreadPoolExecutor() as executor:
        futs: list[Future[Path]] = []
        for map_name in map_names:
            futs.append(executor.submit(
                do_map_first_time_config, map_name))

        for f in futs:
            ex = f.exception()
            if ex:
                logger.error("future {} failed with error: {}", f, ex)
            else:
                map_cfg_paths.append(f.result())

    name_to_id: dict[str, int] = {}

    pk = cfg.steamguard_passkey
    code = await get_steamguard_code(cfg.steamguard_cli_path, pk)

    logger.info("building {} workshop items", len(map_cfg_paths))
    await workshop_build_item_many(
        cfg.exe_path,
        cfg.username,
        cfg.password,
        item_config_paths=map_cfg_paths,
        steamguard_code=code,
    )

    # Read back the new item IDs written by SteamCMD.
    for map_cfg_path in map_cfg_paths:
        logger.info("built workshop item: '{}'", map_cfg_path)
        map_name = map_cfg_path.stem
        map_vdf = vdf.loads(map_cfg_path.read_text())
        title = map_vdf["workshopitem"]["title"]
        sws_id = int(map_vdf["workshopitem"]["publishedfileid"])
        logger.info("{}: {}: new workshop item ID: {}", map_name, title, sws_id)
        name_to_id[map_name] = sws_id

    logger.info("{}", pformat(name_to_id))


def calculate_file_md5_hashes(path: Path) -> dict[Path, str]:
    results = {}
    for file in [x for x in path.rglob("*") if x.is_file()]:
        results[file] = file_digest(file).hexdigest()
    return results


def dump_manifest(manifest: WorkshopManifest, out_file: Path):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("wb") as f:
        logger.info("writing SWS manifest: '{}'", out_file)
        f.write(orjson.dumps(
            manifest,
            option=orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE | orjson.OPT_SORT_KEYS
        ))


def load_manifest(file: Path) -> WorkshopManifest:
    file = file.resolve()
    logger.info("reading SWS manifest: '{}'", file)
    return WorkshopManifest(**orjson.loads(file.read_bytes()))


def make_sws_manifest(
        out_file: Path,
        content_folder: Path,
        content_folder_parent: Path,
        item_id: int,
        git_hash: str,
        hg_packages_hash: str,
        hg_maps_hash: str,
        build_id: str,
        build_time_utc: datetime.datetime,
        executor: ThreadPoolExecutor | None = None,
) -> WorkshopManifest:
    # TODO: is content_folder_parent useless?
    #   It's always the same as content_folder?

    file_to_md5: dict[str, str] = {}

    if executor:
        md5_future: Future[dict[Path, str]] = executor.submit(
            calculate_file_md5_hashes,
            content_folder,
        )
        file_to_md5 = {
            str(file): md5
            for file, md5 in md5_future.result().items()
        }

    else:
        md5_futures: dict[Path, Future[str]] = {}
        workers = max(((os.cpu_count() or 1) - 2), 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for file in [x for x in content_folder.rglob("*") if x.is_file()]:
                md5_futures[file] = executor.submit(
                    file_hexdigest,
                    file,
                )
        for file, md5_fut in md5_futures.items():
            file_to_md5[str(file.relative_to(content_folder_parent))] = md5_fut.result()

    manifest = WorkshopManifest(
        workshop_item_id=item_id,
        git_hash=git_hash,
        git_tag="null",  # TODO
        hg_packages_hash=hg_packages_hash,
        hg_packages_tag="null",  # TODO
        hg_maps_hash=hg_maps_hash,
        hg_maps_tag="null",  # TODO
        build_id=build_id,
        build_time_utc=build_time_utc,
        file_to_md5=file_to_md5,
    )

    dump_manifest(manifest, out_file)

    return manifest


async def main() -> None:
    ap = argparse.ArgumentParser()

    action_choices = {
        "test": test,
        "list_maps": list_maps,
        "first_time_upload_all_maps": first_time_upload_all_maps,
    }
    ap.add_argument(
        "action",
        choices=action_choices.keys(),
        help="action to perform",
    )
    ap.add_argument(
        "--maps-dir",
        help="path to a directory for actions that take map directory as an argument",
        type=Path,
        required=False,
    )

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)

    await action_choices[args.action](
        maps_dir=args.maps_dir,
    )
    logger.info("exiting")


if __name__ == "__main__":
    asyncio_run(main())
