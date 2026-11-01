from importlib.resources import files

from PIL import Image


def test_idle_animation_is_transparent_looping_gif() -> None:
    path = files("maidchan").joinpath("assets/maid_idle.gif")
    with Image.open(path) as animation:
        assert animation.format == "GIF"
        assert animation.n_frames == 21
        assert animation.info["loop"] == 0
        animation.seek(0)
        assert animation.info.get("transparency") is not None
        first_frame = animation.convert("RGBA")
        assert first_frame.getpixel((0, 0))[3] == 0

        bottoms: list[int] = []
        heights: list[int] = []
        for index in range(animation.n_frames):
            animation.seek(index)
            bounds = animation.convert("RGBA").getchannel("A").getbbox()
            assert bounds is not None
            bottoms.append(bounds[3])
            heights.append(bounds[3] - bounds[1])
        assert max(bottoms) - min(bottoms) <= 1
        assert max(heights) - min(heights) <= 2


def test_emotion_animations_are_fixed_size_smooth_transparent_gifs() -> None:
    for emotion in ("happy", "sad", "surprised", "angry", "thinking"):
        path = files("maidchan").joinpath(f"assets/maid_{emotion}.gif")
        with Image.open(path) as animation:
            assert animation.format == "GIF"
            assert animation.size == (384, 512)
            assert animation.n_frames == 24
            assert animation.info["loop"] == 0
            assert animation.info.get("transparency") is not None

            bottoms = []
            for index in range(animation.n_frames):
                animation.seek(index)
                bounds = animation.convert("RGBA").getchannel("A").getbbox()
                assert bounds is not None
                bottoms.append(bounds[3])
            assert max(bottoms) - min(bottoms) <= 1
