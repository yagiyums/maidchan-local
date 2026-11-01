import runpy
from pathlib import Path


def test_main_file_can_be_loaded_as_a_standalone_entrypoint() -> None:
    main_file = Path(__file__).parents[1] / "src" / "maidchan" / "main.py"
    namespace = runpy.run_path(str(main_file), run_name="pyinstaller_entrypoint_check")
    assert callable(namespace["main"])
