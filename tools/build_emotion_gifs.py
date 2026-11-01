from __future__ import annotations

import argparse
import math
from pathlib import Path

from build_idle_gif import to_gif_frame
from PIL import Image

CANVAS_SIZE = (384, 512)
BASELINE_Y = 496
EMOTIONS = {
    "happy": {"amplitude": 9.0, "cycles": 1, "duration": 75},
    "sad": {"amplitude": 4.0, "cycles": 1, "duration": 110},
    "surprised": {"amplitude": 7.0, "cycles": 1, "duration": 85},
    "angry": {"amplitude": 9.0, "cycles": 2, "duration": 70},
    "thinking": {"amplitude": 5.0, "cycles": 1, "duration": 100},
}


def normalize_character(source: Image.Image) -> Image.Image:
    source = source.convert("RGBA")
    bounds = source.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Emotion source has no visible pixels")
    crop = source.crop(bounds)
    scale = min(480 / crop.height, 376 / crop.width)
    resized = crop.resize(
        (round(crop.width * scale), round(crop.height * scale)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    paste_x = (CANVAS_SIZE[0] - resized.width) // 2
    paste_y = BASELINE_Y - resized.height
    canvas.alpha_composite(resized, (paste_x, paste_y))
    return canvas


def anchored_sway(frame: Image.Image, offset_at_top: float) -> Image.Image:
    shear = offset_at_top / BASELINE_Y
    return frame.transform(
        CANVAS_SIZE,
        Image.Transform.AFFINE,
        (1.0, shear, -shear * BASELINE_Y, 0.0, 1.0, 0.0),
        resample=Image.Resampling.BICUBIC,
    )


def build_emotion_gif(source: Path, output: Path, emotion: str) -> None:
    settings = EMOTIONS[emotion]
    normalized = normalize_character(Image.open(source))
    frames = []
    frame_count = 24
    for index in range(frame_count):
        phase = 2 * math.pi * settings["cycles"] * index / frame_count
        offset = settings["amplitude"] * math.sin(phase)
        frames.append(to_gif_frame(anchored_sway(normalized, offset)))
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=int(settings["duration"]),
        loop=0,
        disposal=2,
        optimize=False,
        transparency=255,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Maid-chan emotion GIFs")
    parser.add_argument("assets", type=Path, help="Directory containing maid_<emotion>.png")
    args = parser.parse_args()
    for emotion in EMOTIONS:
        source = args.assets / f"maid_{emotion}.png"
        output = args.assets / f"maid_{emotion}.gif"
        build_emotion_gif(source, output, emotion)
        print(output)


if __name__ == "__main__":
    main()
