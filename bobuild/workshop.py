from pathlib import Path

from PIL import Image
from PIL import ImageFont


def draw_map_preview_file(
        template_file: Path,
        output_file: Path,
        font_file: Path,
        font_color: tuple[int, int, int],
):
    img = Image.open(template_file)
    font = ImageFont.load(str(font_file.resolve()))
