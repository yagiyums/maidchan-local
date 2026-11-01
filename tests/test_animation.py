from importlib.resources import files

from PIL import Image


def test_idle_animation_is_transparent_looping_gif() -> None:
    path = files("maidchan").joinpath("assets/maid_idle.gif")
    with Image.open(path) as animation:
        assert animation.format == "GIF"
        assert animation.n_frames == 8
        assert animation.info["loop"] == 0
        animation.seek(0)
        assert animation.info.get("transparency") is not None
        first_frame = animation.convert("RGBA")
        assert first_frame.getpixel((0, 0))[3] == 0
