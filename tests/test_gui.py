import functools
import sys
import types
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from alds import aitk, gui, build, identity, positives, negatives, cancel
from alds.i18n import use
from test_preservation import ProjectTest


class GuiTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.gui_root = patch.object(gui, "PROJECTS_DIR", self.p.dir.parent)
        self.gui_root.start()
        self.addCleanup(self.gui_root.stop)
        self.settings = patch.object(aitk, "SETTINGS", self.p.dir / "settings.json")
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def test_both_languages_build_with_new_controls_and_callbacks(self):
        for language, label in (("ar", "🕘 نسخ البناء المحفوظة"), ("en", "🕘 Saved build versions")):
            ui = gui.build_ui(language)
            config = ui.get_config_file()
            self.assertTrue(any(c["props"].get("label") == label for c in config["components"]))
            self.assertTrue(any(fn.fn and fn.fn.__name__ == "do_preview" for fn in ui.fns.values()))
            self.assertTrue(any(fn.fn and fn.fn.__name__ == "do_restore_frames" for fn in ui.fns.values()))
            self.assertTrue(any(fn.fn and fn.fn.__name__ == "confirm_image" for fn in ui.fns.values()))
            self.assertTrue(any(fn.fn and fn.fn.__name__ == "do_feedback_preview" for fn in ui.fns.values()))
            confirm_label = "✅ هذه الشخصية بالتأكيد" if language == "ar" else "✅ Definitely this character"
            self.assertTrue(any(c["props"].get("value") == confirm_label for c in config["components"]))

    def test_versions_callbacks_and_arabic_comparison(self):
        self.write_build()
        with use("ar"):
            log, dropdown, undo = gui.do_version(self.p.name, "hero")
            self.assertEqual(undo, [])
            self.assertEqual(len(dropdown["choices"]), 1)
            self.assertIn("حفظ يدوي", dropdown["choices"][0][0])
            self.assertIn("المحفوظة", gui.version_comparison(self.p.name, "hero", dropdown["value"]))

    def test_preview_reasons_switch_language_without_changing_results(self):
        data = {"frames": 12, "accepted": 1,
                "items": [{"file": "sample.jpg", "reason": "accepted", "score": 0.05}]}
        with use("ar"):
            gallery, summary = gui.preview_view(data)
        self.assertIn("مقبولة", gallery[0][1])
        with use("en"):
            gallery, summary = gui.preview_view(data)
        self.assertIn("accepted", gallery[0][1])
        self.assertIn("12 sampled frames", summary)

    def feedback_fixture(self):
        from test_feedback import distances
        char = self.write_build()
        for file in (char / "sorted").rglob("*.png"):
            Image.new("RGB", (64, 64), (100, 90, 120)).save(file)
        np.savez(char / "ccip.npz", stems=["a", "b"], feats=[[0.12, 1], [0.04, 1]], refs=[[0, 1]])
        meta = self.p.load("characters/hero/build.json")
        for item in meta["items"]:
            item.update(t=0, vid=1, type="full", ccip=0.12, sharp=100)
        self.p.save("characters/hero/build.json", meta)
        self.enterContext(patch.object(build, "ccip_cross", side_effect=distances))
        self.enterContext(patch.object(identity, "ccip_cross", side_effect=distances))
        return char, gui.list_files(self.p.name, "hero", "all")

    def test_confirmation_rejection_undo_and_reference_management(self):
        char, files = self.feedback_fixture()
        self.assertTrue(files[0].endswith("a.png"))
        self.assertEqual(len(gui.list_files(self.p.name, "hero", "_uncertain")), 1)
        confirmed = gui.confirm_image(self.p.name, "hero", "all", files, 0)
        self.assertEqual(len(gui.list_files(self.p.name, "hero", "_uncertain")), 0)
        self.assertEqual(len(gui.list_files(self.p.name, "hero", "_confirmed")), 1)
        self.assertIn("a", gui.confirmed_choices(self.p.name, "hero")["choices"])
        files, idx = confirmed[4:6]
        rejected = gui.reject_image(self.p.name, "hero", "all", files, idx, [])
        self.assertEqual(positives.load(char)[0], [])
        self.assertEqual(negatives.load(char)[0], ["a"])
        undone = gui.undo_delete(self.p.name, "hero", "all", rejected[4], rejected[5], rejected[7])
        self.assertEqual(positives.load(char)[0], ["a"])
        self.assertEqual(negatives.load(char)[0], [])
        gui.unconfirm_image(self.p.name, "hero", "all", undone[4], undone[5], "a")
        self.assertEqual(positives.load(char)[0], [])
        self.assertEqual(len(gui.list_files(self.p.name, "hero", "_uncertain")), 1)

    def test_rejection_move_failure_restores_label_and_images(self):
        char, files = self.feedback_fixture()
        positives.confirm(char, files[0])
        before = self.files(char)
        with patch.object(negatives, "move_pair", side_effect=OSError("locked file")):
            with self.assertRaises(OSError):
                gui.reject_image(self.p.name, "hero", "all", files, 0, [])
        self.assertEqual(self.files(char), before)

    def test_feedback_preview_switches_language_and_clears_stale_result(self):
        data = {"before": 2, "after": 3, "added": 1, "removed": 0, "switched": 0,
                "confirmed": 1, "rejected": 0,
                "items": [{"vid": 1, "t": 12, "change": "new match", "before": None, "after": 0.03}]}
        with use("ar"):
            summary, rows = gui.impact_view(data)
            self.assertIn("الإطارات المطابقة", summary)
            self.assertEqual(rows.iloc[0, 2], "مطابقة جديدة")
        with use("en"):
            summary, rows = gui.impact_view(data)
            self.assertIn("Matched frames", summary)
            self.assertEqual(rows.iloc[0, 2], "new match")
        cleared = gui.clear_impact()
        self.assertEqual(cleared[-1], {})
        self.assertEqual(cleared[-2], [])
        self.assertIsNone(gui.confirmed_view(None, None)[1])

    def test_cancelled_feedback_preview_does_not_block_later_review(self):
        self.feedback_fixture()
        cancel.request()
        with patch("alds.feedback.preview_impact", side_effect=cancel.Cancelled):
            with self.assertRaises(gui.gr.Error):
                gui.do_feedback_preview(self.p.name, "hero")
        cancel.check()
        self.assertEqual(len(gui.list_files(self.p.name, "hero", "all")), 2)

    def test_review_edits_wait_only_for_the_character_being_rebuilt(self):
        char, files = self.feedback_fixture()
        with gui.working_on(char):
            with self.assertRaises(gui.gr.Error):
                gui.delete_image(self.p.name, "hero", "all", files, 0, [])
            with self.assertRaises(gui.gr.Error):
                gui.save_caption(self.p.name, "hero", files, 0, "new caption")
            with use("en"):
                self.assertIn("rebuilt", gui.version_comparison(self.p.name, "hero", "any"))
        with gui.working_on(self.p.char_dir("other")):
            gui.save_caption(self.p.name, "hero", files, 0, "new caption")
        self.assertEqual(Path(files[0]).with_suffix(".txt").read_text(encoding="utf-8"), "new caption")

    def test_images_to_check_stay_first_after_ambiguous_ones(self):
        char, _ = self.feedback_fixture()
        a = next((char / "sorted").rglob("a.png"))
        b = next((char / "sorted").rglob("b.png"))
        review = char / "sorted" / "_review" / b.relative_to(char / "sorted")
        review.parent.mkdir(parents=True)
        b.rename(review)
        b.with_suffix(".txt").rename(review.with_suffix(".txt"))
        np.savez(char / "ccip.npz", stems=["a", "b", "c"], feats=[[0.05, 1], [0.04, 1], [0.12, 1]], refs=[[0, 1]])
        c = a.with_name("c.png")
        Image.new("RGB", (64, 64)).save(c)
        files = gui.list_files(self.p.name, "hero", "all")
        self.assertEqual([Path(f).stem for f in files], ["c", "b", "a"])

    def test_deleting_a_version_needs_confirmation(self):
        self.write_build()
        _, dropdown, _ = gui.do_version(self.p.name, "hero")
        with self.assertRaises(gui.gr.Error):
            gui.do_delete_version(self.p.name, "hero", dropdown["value"], False)
        log, dropdown, confirm = gui.do_delete_version(self.p.name, "hero", dropdown["value"], True)
        self.assertEqual(dropdown["choices"], [])
        self.assertFalse(confirm)

    def test_long_actions_free_the_models_when_done(self):
        module = types.ModuleType("imgutils.fake")
        module.open_model = functools.lru_cache()(lambda name: object())
        with patch.dict(sys.modules, {"imgutils.fake": module}):
            gui.releasing(lambda: module.open_model("tagger"))()
            self.assertEqual(module.open_model.cache_info().currsize, 0)
            def failing_build():
                module.open_model("tagger")
                raise RuntimeError("build failed")
            with self.assertRaises(RuntimeError):
                gui.releasing(failing_build)()
            self.assertEqual(module.open_model.cache_info().currsize, 0)
