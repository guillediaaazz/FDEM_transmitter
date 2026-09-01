"""Generate the Windows ICO used by the PyInstaller build.

The geometry and colors mirror assets/fdem.svg. Pillow is already a runtime
dependency of CustomTkinter, so the build needs no extra converter.
"""

from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw


def rounded_line(draw: ImageDraw.ImageDraw, points: tuple[int, int, int, int], width: int, fill: str) -> None:
    draw.line(points, fill=fill, width=width)
    radius = width // 2
    for x, y in ((points[0], points[1]), (points[2], points[3])):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def render(size: int = 256) -> Image.Image:
    scale = size / 192

    def px(value: float) -> int:
        return round(value * scale)

    image = Image.new("RGBA", (size, size), "#091a2b")
    draw = ImageDraw.Draw(image)
    draw.ellipse((px(39), px(39), px(153), px(153)), outline="#3bd4e8", width=px(10))
    draw.ellipse((px(60), px(60), px(132), px(132)), outline="#4a8dff", width=px(8))
    for line in ((32, 96, 70, 96), (122, 96, 160, 96), (96, 32, 96, 70), (96, 122, 96, 160)):
        rounded_line(draw, tuple(px(value) for value in line), px(8), "#5ae2a0")
    draw.ellipse((px(85), px(85), px(107), px(107)), fill="#ffbd5c")
    return image


def main() -> None:
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/generated/fdem.ico")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = render()
    image.save(destination, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(destination.resolve())


if __name__ == "__main__":
    main()

