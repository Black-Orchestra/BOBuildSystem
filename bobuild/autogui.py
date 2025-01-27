import asyncio
from pathlib import Path
from typing import TextIO

import pyautogui
import pygetwindow

from bobuild.utils import asyncio_run

_file_dir = Path(__file__).parent.resolve()
_resources_dir = _file_dir / "resources/autogui"
_img_button_lighting_production = _resources_dir / "editor_button_lighting_production.png"
_img_button_lighting_high = _resources_dir / "editor_button_lighting_high.png"
_img_button_lighting_medium = _resources_dir / "editor_button_lighting_medium.png"
_img_button_lighting_preview = _resources_dir / "editor_button_lighting_preview.png"

_editor_title = "Unreal Editor for Rising Storm 2 (64-bit)"
_cmd_map_load = 'MAP LOAD -FILE="{}"'


def wait_for_log_text(
        log_file: TextIO,
        text: str,
        pos: int,
        timeout: float,
) -> int:
    # log_file.readline()
    return log_file.tell()


async def main() -> None:
    # temp = Path()
    # x = temp.open()

    print(pyautogui.position())
    window = pygetwindow.getWindowsWithTitle(_editor_title)[0]
    print(window)
    window.maximize()
    window.activate()
    print(window.bottomleft)

    w = window.width
    h = window.height

    await asyncio.sleep(1.0)
    button_loc = pyautogui.locateOnScreen(
        image=str(_img_button_lighting_production),
        region=(0, 0, w, h // 2),
        confidence=0.90,
        grayscale=False,
    )
    print(button_loc)


if __name__ == "__main__":
    asyncio_run(main())
