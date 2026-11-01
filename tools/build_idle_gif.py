from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def normalize_frame(
    frame: Image.Image,
    target_height: int = 482,
    anchor_x: int = 200,
    baseline_y: int = 496,
) -> Image.Image:
    alpha = frame.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        return frame

    left, top, right, bottom = bounds
    foot_zone_top = max(top, bottom - 72)
    foot_pixels: list[int] = []
    alpha_pixels = alpha.load()
    for y in range(foot_zone_top, bottom):
        for x in range(left, right):
            if alpha_pixels[x, y] >= 128:
                foot_pixels.append(x)
    foot_center_x = sum(foot_pixels) / len(foot_pixels) if foot_pixels else (left + right) / 2

    scale = target_height / (bottom - top)
    crop = frame.crop(bounds)
    resized = crop.resize(
        (round(crop.width * scale), target_height),
        Image.Resampling.LANCZOS,
    )
    paste_x = round(anchor_x - (foot_center_x - left) * scale)
    paste_y = baseline_y - target_height
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.alpha_composite(resized, (paste_x, paste_y))
    return canvas


def interpolate_frames(frames: list[Image.Image]) -> tuple[list[Image.Image], list[int]]:
    selected_indices = [0, 1, 2, 3, 4, 5, 7]
    selected = [frames[index] for index in selected_indices]
    output: list[Image.Image] = []
    durations: list[int] = []
    for index, current in enumerate(selected):
        following = selected[(index + 1) % len(selected)]
        blink_transition = 2 in (
            selected_indices[index],
            selected_indices[(index + 1) % len(selected)],
        )
        duration = 50 if blink_transition else 140
        for step in range(3):
            output.append(Image.blend(current, following, step / 3))
            durations.append(duration)
    return output, durations


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
        frames.append(normalize_frame(frame))

    output.parent.mkdir(parents=True, exist_ok=True)
    smooth_frames, durations = interpolate_frames(frames)
    gif_frames = [to_gif_frame(frame) for frame in smooth_frames]
    gif_frames[0].save(
        output,
        save_all=True,
        append_images=gif_frames[1:],
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
