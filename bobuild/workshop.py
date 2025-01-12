import argparse
import asyncio
from concurrent.futures import Future
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from pprint import pformat

import vdf
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont

from bobuild.config import SteamCmdConfig
from bobuild.log import logger
from bobuild.steamcmd import get_steamguard_code
from bobuild.steamcmd import workshop_build_item

_file_dir = Path(__file__).parent.resolve()
_repo_dir = _file_dir.parent
_draw_y = 880
_glow_x = 4
_glow_y = 4

# BO red is cc1417.
_bo_red = (204, 20, 23)


def find_map_names(base_dir: Path) -> set[str]:
    roes = base_dir.rglob("*.roe")
    return {
        str(file.stem) for file in roes
        if (file.name.startswith("RRTE")
            or file.name.startswith("DRTE"))
           and file.stat().st_size > 4096 * 1024
    }


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
        font_file: Path,
        font_color: tuple[int, int, int],
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
    l = len(map_name)
    if l > 36:
        logger.warning("map name longer than 36 characters: {}", l)
    if l > 22:
        # Swap old_min and old_max for "linear inversion".
        font_size = int(linear_convert(l, 36, 22, 59, 90))
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

    img.save(output_file)


async def test() -> None:
    draw_map_preview_file(
        map_name="DRTE-ElAlamein@@@@@@@@@@@@@@@@@@@@@@",
        template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
        output_file=_repo_dir / "workshop/generated/BOBetaMapImgTest.png",
        font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color=_bo_red,
    )

    # TODO: take this as an argument?
    test_dir = Path(r"P:\BO_Repos\BO_Maps")
    if test_dir.exists():
        map_names = find_map_names(test_dir)
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


async def list_maps() -> None:
    # TODO: take this as an argument?
    test_dir = Path(r"P:\BO_Repos\BO_Maps")
    if test_dir.exists():
        map_names = sorted(find_map_names(test_dir))
        for m in map_names:
            print(m)


def write_map_sws_config(
        out_file: Path,
        template_file: Path,
        map_name: str,
        content_folder: Path,
        preview_file: Path,
):
    template = vdf.loads(template_file.read_text())
    template["workshopitem"]["publishedfileid"] = 0  # Create new item.
    template["workshopitem"]["contentfolder"] = str(content_folder.resolve())
    template["workshopitem"]["previewfile"] = str(preview_file)
    title = template["workshopitem"]["title"].format(_mapname=map_name)
    template["workshopitem"]["title"] = title
    desc = template["workshopitem"]["description"].format(
        _mapname=map_name,
        _git_hash="null",
        _hg_pkg_hash="null",
        _hg_maps_hash="null",
    )
    template["workshopitem"]["changenote"] = "Initial upload of dummy files."
    template["workshopitem"]["description"] = desc

    with out_file.open("w") as f:
        logger.info("writing '{}'", out_file)
        vdf.dump(template, f, pretty=True)


def do_map_first_time_config(
        map_name: str,
) -> Path:
    p = Path(_repo_dir) / "workshop/generated/sws_map_staging/" / map_name
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

    write_map_sws_config(
        out_file=map_vdf_file,
        template_file=_repo_dir / "workshop/BOBetaMapTemplate.vdf",
        map_name=map_name,
        content_folder=content_folder,
        preview_file=preview_file,
    ),

    content_folder.mkdir(parents=True, exist_ok=True)
    dummy_file = content_folder / "dummy.txt"
    logger.info("writing '{}'", dummy_file)
    dummy_file.write_text(f"This is a dummy file for {map_name}!")

    return map_vdf_file


async def first_time_upload_all_maps(
        # maps_dir: Path,
) -> None:
    """WARNING: this will create new workshop items for all
    BO dev maps and list their workshop IDs. The SWS items are
    created with only a dummy text file in them.

    Run this as a first-time setup action to create the SWS items
    for later usage in automation.

    TODO: add option to skip existing items?
    """
    cfg = SteamCmdConfig()

    # TODO: take this as an argument!!!
    maps_dir = Path(r"P:\BO_Repos\BO_Maps")

    logger.info("first-time uploading all maps")

    map_names = sorted(find_map_names(maps_dir))
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
    map_cfg_paths = map_cfg_paths[:1]  # TODO: SLICING ONLY FOR DEBUGGING!
    for map_cfg_path in map_cfg_paths:
        code = await get_steamguard_code(cfg.steamguard_cli_path, pk)
        logger.info("building workshop item: '{}'", map_cfg_path)
        await workshop_build_item(
            cfg.exe_path,
            cfg.username,
            cfg.password,
            item_config_path=map_cfg_path,
            steamguard_code=code,
        )

        map_name = map_cfg_path.stem
        map_vdf = vdf.loads(map_cfg_path.read_text())
        title = map_vdf["workshopitem"]["title"]
        sws_id = int(map_vdf["workshopitem"]["publishedfileid"])
        logger.info("{}: {}: new workshop item ID: {}", map_name, title, sws_id)
        name_to_id[map_name] = sws_id

    logger.info("{}", pformat(name_to_id))

    # 1. find list of maps in published?
    # 2. generate .vdf files for maps
    # 3. render workshop preview images
    # 4. upload maps (WITH EMPTY FILES!)
    # 5. print {map_name -> sws_id} dict


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

    args = ap.parse_args()
    action = args.action
    logger.info("performing action: {}", action)
    await action_choices[args.action]()
    logger.info("exiting")


# TODO: functions to format .vdf workshop files from the templates.


if __name__ == "__main__":
    asyncio.run(main())
