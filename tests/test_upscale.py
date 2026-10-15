import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import huggingface_hub
import numpy as np
from PIL import Image

from alds import gui, upscale
from alds.i18n import use


class FakeCache:
    def __init__(self, repos):
        self.repos = [types.SimpleNamespace(repo_id=repo, size_on_disk=size,
                                            revisions=[types.SimpleNamespace(commit_hash=repo + "@rev")])
                      for repo, size in repos.items()]
        self.deleted = []

    def delete_revisions(self, *hashes):
        self.deleted += hashes
        return types.SimpleNamespace(execute=lambda: None)


class ModelFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def cached(self, present):
        def lookup(repo, file):
            if (repo, file) not in present:
                return None
            path = Path(self.tmp.name) / file.replace("/", "_")
            path.write_bytes(b"x" * 1000)
            return str(path)
        return patch.object(huggingface_hub, "try_to_load_from_cache", side_effect=lookup)

    def test_a_model_counts_as_downloaded_only_with_all_its_files(self):
        files = upscale.files("waifu2x")
        with self.cached(set(files)):
            self.assertEqual(upscale.downloaded_size("waifu2x"), 2000)
        with self.cached({files[0]}):
            self.assertEqual(upscale.downloaded_size("waifu2x"), 0)

    def test_delete_removes_only_the_chosen_model(self):
        cache = FakeCache({"deepghs/waifu2x_onnx": 36_000_000, "Kim2091/AnimeSharp": 34_000_000,
                           "deepghs/ccip_onnx": 500_000_000})
        with patch.object(huggingface_hub, "scan_cache_dir", return_value=cache), \
                patch("alds.common.release_models") as release:
            freed = upscale.delete("waifu2x")
        self.assertEqual(cache.deleted, ["deepghs/waifu2x_onnx@rev"])
        self.assertEqual(freed, 36_000_000)
        release.assert_called_once()

    def test_download_fetches_every_file_of_the_model(self):
        with patch.object(huggingface_hub, "hf_hub_download") as fetch:
            upscale.download("animesharp")
        self.assertEqual([c.args for c in fetch.call_args_list], upscale.files("animesharp"))

    def test_tiled_upscale_matches_the_requested_size(self):
        def fake_session(model, scale):
            run = lambda _, feed: [np.repeat(np.repeat(next(iter(feed.values())), scale, 2), scale, 3)]
            return types.SimpleNamespace(run=run), "input", np.float32, 0
        with patch.object(upscale, "_session", side_effect=fake_session):
            out = upscale.upscale_image(Image.new("RGB", (300, 170), (40, 80, 120)), 1.5, "animesharp")
        self.assertEqual(out.size, (450, 255))
        self.assertEqual(out.getpixel((200, 100)), (40, 80, 120))


class ModelPickerTests(unittest.TestCase):
    def test_choosing_a_model_downloads_it_and_shows_its_state(self):
        sizes = {"animevideov3": 0}
        with patch.object(upscale, "downloaded_size", side_effect=lambda m, v="auto": sizes[m]), \
                patch.object(upscale, "download", side_effect=lambda m, v="auto": sizes.update({m: 2_500_000})) as fetch, \
                use("en"):
            self.assertEqual(gui.do_model(False, "animevideov3", "auto", lambda *a, **k: None)[0], gui.gr.update())
            fetch.assert_not_called()
            status, delete_button = gui.do_model(True, "animevideov3", "auto", lambda *a, **k: None)
        fetch.assert_called_once_with("animevideov3", "auto")
        self.assertIn("is downloaded (2.5 MB)", status)
        self.assertTrue(delete_button["visible"])

    def test_failed_download_explains_what_to_do(self):
        with patch.object(upscale, "downloaded_size", return_value=0), \
                patch.object(upscale, "download", side_effect=OSError("offline")), use("en"):
            with self.assertRaises(gui.gr.Error) as err:
                gui.do_model(True, "waifu2x", "auto", lambda *a, **k: None)
        self.assertIn("internet connection", str(err.exception))

    def test_deleting_a_model_hides_the_button(self):
        with patch.object(upscale, "delete", return_value=36_000_000), \
                patch.object(upscale, "downloaded_size", return_value=0), use("en"):
            status, delete_button = gui.delete_model("waifu2x")
        self.assertIn("isn't downloaded yet", status)
        self.assertFalse(delete_button["visible"])

    def test_every_model_has_an_explanation_in_both_languages(self):
        import json
        info = json.loads(gui.model_info_json())
        self.assertEqual(set(info), set(upscale.MODELS))
        for key, texts in info.items():
            self.assertNotEqual(texts["en"][1], texts["ar"][1], key)

    def test_one_version_downloads_only_that_version(self):
        with patch.object(upscale, "downloaded_size", return_value=0), \
                patch.object(upscale, "download") as fetch, use("en"):
            status, _ = gui.do_model(True, "waifu2x", "4", lambda *a, **k: None)
        fetch.assert_called_once_with("waifu2x", "4")
        self.assertIn("· 4x", status)

    def test_version_choice_shows_only_for_models_with_two_versions(self):
        self.assertTrue(gui.model_versions("waifu2x", "4")["visible"])
        self.assertEqual(gui.model_versions("waifu2x", "4")["value"], "4")
        hidden = gui.model_versions("animevideov3", "2")
        self.assertFalse(hidden["visible"])
        self.assertEqual(hidden["value"], "auto")


class VersionTests(unittest.TestCase):
    def test_versions_pick_files_and_scales(self):
        self.assertEqual(len(upscale.files("waifu2x")), 2)
        self.assertEqual(upscale.files("waifu2x", "2"), [upscale.MODELS["waifu2x"][2][:2]])
        self.assertEqual(upscale.files("animevideov3", "2"), upscale.files("animevideov3"))
        self.assertEqual([upscale.scale_for("waifu2x", f) for f in (1.3, 2.5)], [2, 4])
        self.assertEqual(upscale.scale_for("waifu2x", 1.3, "4"), 4)
        self.assertEqual(upscale.scale_for("waifu2x", 2.5, "2"), 2)
        self.assertEqual(upscale.size_mb("apisr", "4"), 6.5)

    def test_command_line_refuses_a_missing_version(self):
        from alds.__main__ import main
        with self.assertRaises(SystemExit) as err:
            main(["build", "-p", "nothing", "-n", "x", "--upscale", "--upscaler", "animevideov3",
                  "--upscaler-version", "2"])
        self.assertIn("only a 4x version", str(err.exception))


if __name__ == "__main__":
    unittest.main()
