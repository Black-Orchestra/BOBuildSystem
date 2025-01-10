from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont

from bobuild.log import logger

_file_dir = Path(__file__).parent.resolve()
_repo_dir = _file_dir.parent
_draw_y = 880
_glow_x = 4
_glow_y = 4


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


def main() -> None:
    # BO red is cc1417.
    red = (204, 20, 23)
    draw_map_preview_file(
        map_name="DRTE-ElAlamein@@@@@@@@@@@@@@@@@@@@@@",
        template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
        output_file=_repo_dir / "workshop/generated/BOBetaMapImgTest.png",
        font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color=red,
    )

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
                    font_color=red,
                )


if __name__ == "__main__":
    main()
