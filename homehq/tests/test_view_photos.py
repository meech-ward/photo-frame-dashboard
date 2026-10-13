"""Photo decoder recovery and slot reuse through the real native view."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1] / "badge" / "homehq"
sys.path.insert(0, str(APP))


def native_view(loader):
    """Supply only the native drawing API; execute the unchanged product class."""
    spec = importlib.util.spec_from_file_location("homehq_photo_test_view", APP / "view.py")
    module = importlib.util.module_from_spec(spec)
    module.color = SimpleNamespace(rgb=lambda *values: values)
    module.font = SimpleNamespace(load=lambda _: "face", smart="smart", badgewaremax="badge")
    module.shape = SimpleNamespace(rounded_rectangle=lambda *values: values)
    module.rect = lambda *values: values
    module.image = SimpleNamespace(load=loader, ELLIPSES=0, RIGHT=1, TOP=2, LEFT=3)
    module.screen = SimpleNamespace(text=Mock(), rectangle=Mock(), blit=Mock(), shape=Mock())
    ui = SimpleNamespace(_FACES={}, CHROME_FACE="chrome",
                         Chrome=lambda **_: SimpleNamespace(font="face", font_size=18))
    # Importing the view must not replace another test's real/shared ui module.
    with patch.dict(sys.modules, {"ui": ui}):
        spec.loader.exec_module(module)
    return module.HomeView("/app"), module.screen


def photo_app(path="household/first.png"):
    row = {"id": "p1", "path": path, "caption": "Family photo", "place": "Home"}
    app = SimpleNamespace(selected=lambda: row, index=lambda: 0, current_rows=lambda: [row])
    return app, row


class PhotoViewTests(unittest.TestCase):
    def test_failed_decode_retries_same_content_on_next_draw(self):
        for failure in (ValueError("decode failed"), None):
            with self.subTest(failure=type(failure).__name__):
                pixels = object()
                loader = Mock(side_effect=[failure, pixels])
                view, screen = native_view(loader)
                app, _ = photo_app()
                view.photos(app, "/state/homehq-photo-0.png")
                screen.blit.assert_not_called()
                view.photos(app, "/state/homehq-photo-0.png")
                self.assertEqual(loader.call_count, 2)
                self.assertIs(screen.blit.call_args.args[0], pixels)

    def test_reused_slot_loads_different_immutable_storage_content(self):
        first, second = object(), object()
        loader = Mock(side_effect=[first, second])
        view, screen = native_view(loader)
        app, row = photo_app()
        view.photos(app, "/state/homehq-photo-0.png")
        self.assertIs(screen.blit.call_args.args[0], first)
        # Uploads use content-hash paths. A replacement can keep the row ID and
        # local cache slot while the source image changes underneath both.
        row["path"] = "household/second.png"
        view.photos(app, "/state/homehq-photo-0.png")
        self.assertEqual(loader.call_count, 2)
        self.assertIs(screen.blit.call_args.args[0], second)

    def test_successful_same_content_is_decoded_only_once(self):
        pixels = object()
        loader = Mock(return_value=pixels)
        view, screen = native_view(loader)
        app, _ = photo_app()
        for _ in range(3):
            view.photos(app, "/state/homehq-photo-0.png")
        loader.assert_called_once_with("/state/homehq-photo-0.png")
        self.assertEqual(screen.blit.call_count, 3)
        self.assertTrue(all(call.args[0] is pixels for call in screen.blit.call_args_list))


if __name__ == "__main__":
    unittest.main()
