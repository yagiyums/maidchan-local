from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def to_gif_frame(frame: Image.Image) -> Image.Image:
    alpha = frame.getchannel("A")
    paletted = frame.convert("RGB").quantize(
        colors=255,
        method=Image.Quantize.MEDIANCUT,
    )
    transparent_pixels = alpha.point(lambda value: 255 if value < 128 else 0)
    paletted.paste(255, mask=transparent_pixels)
    palette = paletted.getpalette() or []
    palette.extend([0] * (768 - len(palette)))
    palette[255 * 3 : 255 * 3 + 3] = [0, 0, 0]
    paletted.putpalette(palette)
    paletted.info["transparency"] = 255
    paletted.info["disposal"] = 2
    return paletted


def build_idle_gif(source: Path, output: Path, columns: int = 4, rows: int = 2) -> None:
    sheet = Image.open(source).convert("RGBA")
    if sheet.width % columns or sheet.height % rows:
        raise ValueError("Sprite sheet dimensions must be divisible by the grid size")

    frame_width = sheet.width // columns
    frame_height = sheet.height // rows
    frames: list[Image.Image] = []
    for index in range(columns * rows):
        column = index % columns
        row = index // columns
        frame = sheet.crop(
            (
                column * frame_width,
                row * frame_height,
                (column + 1) * frame_width,
                (row + 1) * frame_height,
            )
        )
        alpha = frame.getchannel("A").point(lambda value: 0 if value < 8 else value)
        frame.putalpha(alpha)
        frames.append(to_gif_frame(frame))

    output.parent.mkdir(parents=True, exist_ok=True)
    durations = [360, 360, 130, 360, 360, 360, 130, 360]
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        disposal=2,
        optimize=False,
        transparency=255,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Maid-chan's idle animation GIF")
    parser.add_argument("source", type=Path, help="4x2 RGBA sprite sheet")
    parser.add_argument("output", type=Path, help="Destination GIF")
    args = parser.parse_args()
    build_idle_gif(args.source, args.output)


if __name__ == "__main__":
    main()
