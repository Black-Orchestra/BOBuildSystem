from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter
from PIL import ImageFont

_file_dir = Path(__file__).parent.resolve()
_repo_dir = _file_dir.parent
_draw_y = 880
_glow_x = 4
_glow_y = 4


def draw_map_preview_file(
        map_name: str,
        template_file: Path,
        output_file: Path,
        font_file: Path,
        font_color: tuple[int, int, int],
):
    img = Image.open(template_file)
    iw, ih = img.size
    font = ImageFont.truetype(str(font_file.resolve()), 100)

    draw = ImageDraw.Draw(img)
    glow_img = Image.new("RGBA", (iw, ih), color=(0, 0, 0))
    draw_glow = ImageDraw.Draw(glow_img)

    _, _, w, h = draw.textbbox((0, _draw_y), map_name, font=font)
    text_x = (iw - w) / 2
    text_y = ((ih - h) / 2) + _draw_y

    # Background glow.
    draw_glow.text(
        (text_x + _glow_x, text_y + _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
    )
    draw_glow.text(
        (text_x - _glow_x, text_y - _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
    )
    draw_glow.text(
        (text_x + _glow_x, text_y - _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
    )
    draw_glow.text(
        (text_x - _glow_x, text_y + _glow_y),
        text=map_name,
        font=font,
        fill=(255, 255, 255),
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

    img.show()
    img.save(output_file)


def main() -> None:
    # BO red is cc1417.
    red = (204, 20, 23)
    draw_map_preview_file(
        map_name="DRTE-ElAlamein",
        template_file=_repo_dir / "workshop/bo_beta_workshop_map.png",
        output_file=_repo_dir / "workshop/generated/BOBetaMapImgTest.png",
        font_file=_repo_dir / "workshop/FRONTAGE-REGULAR.OTF",
        font_color=red,
    )


if __name__ == "__main__":
    main()
